"""Windows facial capture; all timestamps are software observations, not exposures."""
from __future__ import annotations

import csv
import json
import math
import re
import subprocess
import threading
import time
from pathlib import Path


class FacialRecordingError(RuntimeError):
    pass


FRAME = re.compile(r'\bn:\s*(\d+).*?pts_time:\s*([-+\d.eE]+)')


def reserve_path(directory, code, *, suffix='facial', log_filename='facial_recording_log.jsonl'):
    """Exclusive reservation also protects orphaned/partial recordings."""
    if not code or any(c in code for c in '<>:"/\\|?*'):
        raise FacialRecordingError('无效的情绪视频编码。')
    directory = Path(directory)
    used = []
    pattern = re.compile(re.escape(code + '_' + suffix) + r'(?:_(\d+))?\.mp4$')
    for p in directory.iterdir():
        match = pattern.fullmatch(p.name)
        if match:
            used.append(int(match[1] or 1))
    log = directory / log_filename
    if log.exists():
        for line in log.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
                if row.get('code') == code:
                    used.append(int(row['number']))
            except (ValueError, KeyError, TypeError):
                continue
    number = max(used, default=0) + 1
    while True:
        number_suffix = '' if number == 1 else f'_{number:02d}'
        path = directory / f'{code}_{suffix}{number_suffix}.mp4'
        try:
            with path.open('xb'):
                pass
            return path, number
        except FileExistsError:
            number += 1


def validate_coverage(frames, onset, offset, duration, decoded_duration):
    values = (onset, offset, duration, decoded_duration)
    if not frames or not all(math.isfinite(x) for x in values) or offset <= onset or duration <= 0:
        raise FacialRecordingError('录像时间或材料时长无效。')
    times = [f[1] for f in frames]
    pts = [f[2] for f in frames]
    if any(b <= a for a, b in zip(times, times[1:])) or any(b <= a for a, b in zip(pts, pts[1:])):
        raise FacialRecordingError('摄像头帧时间戳未严格递增。')
    if times[0] > onset - .5 or times[-1] < offset + .5:
        raise FacialRecordingError('录像未覆盖视频及前后各0.5秒。')
    if decoded_duration < max(duration, offset - onset):
        raise FacialRecordingError('录像时长短于情绪视频时长。')
    if max((b-a for a, b in zip(times, times[1:])), default=0) > 1:
        raise FacialRecordingError('摄像头帧间隔超过1秒。')


def onset_frame_alignment(frames, onset, encoded_pts):
    """Locate the onset in software arrival time, retaining both bracketing frames."""
    result = dict(time_basis='FFmpeg frame arrival versus presentation flip callback',
                  exposure_alignment_verified=False)
    if onset is None or not math.isfinite(onset) or not frames:
        return dict(result, status='unavailable', reason='missing onset or frames')
    times = [row[1] for row in frames]
    if not all(math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        return dict(result, status='unavailable', reason='invalid frame arrival times')
    before = [i for i, value in enumerate(times) if value <= onset]
    after = [i for i, value in enumerate(times) if value >= onset]
    if not before or not after:
        return dict(result, status='unavailable', reason='onset outside observed frames')
    left, right = before[-1], after[0]
    nearest = min((left, right), key=lambda i: abs(times[i] - onset))

    def frame_record(index):
        number, arrival, pts = frames[index]
        return dict(frame=number, arrival_monotonic_sec=arrival,
                    relative_video_onset_sec=arrival-onset, capture_pts_sec=pts,
                    encoded_pts_sec=encoded_pts[index] if index < len(encoded_pts) else None)

    return dict(result, status='software_observation_only', onset_monotonic_sec=onset,
                before=frame_record(left), after=frame_record(right),
                nearest=frame_record(nearest), bracket_interval_sec=times[right]-times[left])


class FacialRecorder:
    device = 'UGREEN Camera 4K'
    filename_suffix = 'facial'
    log_filename = 'facial_recording_log.jsonl'
    relative_time_column = 'relative_video_onset_sec'

    def __init__(self, directory, code, attempt, *, device_type=None):
        from imageio_ffmpeg import get_ffmpeg_exe
        if device_type == 'neuracle':
            self.device = 'facialcamera'
        self.exe = get_ffmpeg_exe()
        self.directory, self.code, self.attempt = Path(directory), code, attempt
        self.frames, self.errors, self.events = [], [], {}
        self.input_width, self.input_height = 1920, 1080
        self.input_pixel_format = None
        self.input_codec = None
        self.process = None
        self.closed = False
        self.path = None
        self.clock = dict(monotonic_sec=time.perf_counter(), timestamp_unix_sec=time.time())

    def _command(self, args, **kwargs):
        timeout = kwargs.pop('timeout', 30)
        return subprocess.run([self.exe, *args], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                              capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, **kwargs)

    def preflight(self):
        devices = self._command(['-hide_banner', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy']).stderr
        # DirectShow lists FriendlyName here; never use an index or an alternative
        # device when the required name is missing or ambiguous.
        # Some Windows drivers enumerate their camera with the type "none".
        names = re.findall(r'"([^"]+)" \((?:video|none)\)', devices)
        if names.count(self.device) != 1:
            raise FacialRecordingError(f'摄像头缺失或同名歧义：{self.device}')
        options = self._command(['-hide_banner', '-list_options', 'true',
                                 '-f', 'dshow', '-i', f'video={self.device}']).stderr
        # list_options deliberately exits with an error; parse advertised modes,
        # then verify the selected mode by actually opening and encoding frames.
        candidates = []
        pattern = (r'(pixel_format|vcodec)=(\w+)\s+min s=(\d+)x(\d+) fps=([\d.]+)'
                   r'\s+max s=(\d+)x(\d+) fps=([\d.]+)')
        for kind, pixel, w, h, low, max_w, max_h, high in re.findall(pattern, options):
            size = (int(w), int(h))
            if (size == (int(max_w), int(max_h)) and
                    size in ((1920, 1080), (2560, 1440)) and
                    ((kind == 'pixel_format' and pixel in ('nv12', 'yuyv422')) or
                     (kind == 'vcodec' and pixel == 'mjpeg')) and float(low) <= 30 <= float(high)):
                candidates.append((size, kind, pixel))
        if not candidates:
            raise FacialRecordingError('摄像头未报告可用的1080p或1440p/30帧模式：' + options[-1800:])
        size, kind, pixel = min(candidates, key=lambda item: (
            item[0] != (1920, 1080), {'mjpeg': 0, 'nv12': 1, 'yuyv422': 2}[item[2]]))
        self.input_width, self.input_height = size
        self.input_pixel_format = pixel if kind == 'pixel_format' else None
        self.input_codec = pixel if kind == 'vcodec' else None
        probe = self._command(['-hide_banner', *self._input_args(), '-t', '0.2', '-an',
            '-vf', self._video_filter(), '-c:v', 'libx264', '-preset', 'ultrafast',
            '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough', '-f', 'null', '-'])
        if probe.returncode or not re.search(r'1920x1080.*30 fps', probe.stderr):
            raise FacialRecordingError('摄像头输入模式或1080p/30帧H.264输出预检失败：' + probe.stderr[-1800:])
        if not self.directory.is_dir():
            raise FacialRecordingError('Session保存目录不存在。')

    def start(self, on_started=None):
        self.preflight()
        self.path, self.number = reserve_path(self.directory, self.code,
            suffix=self.filename_suffix, log_filename=self.log_filename)
        self._log('reserved')
        args = [self.exe, '-hide_banner', '-y', '-copyts', '-start_at_zero', *self._input_args(),
                '-an', '-vf', self._video_filter(), '-c:v', 'libx264',
                '-preset', 'ultrafast', '-crf', '20', '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough',
                '-movflags', '+frag_keyframe+empty_moov+default_base_moof', str(self.path)]
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        deadline = time.perf_counter() + 15
        start_reported = False
        while time.perf_counter() < deadline:
            self.check(startup=True)
            if self.frames and not start_reported:
                frame, observed, pts = self.frames[0]
                fields = {f'{self.filename_suffix}_file': self.path.name,
                    f'{self.filename_suffix}_attempt': self.attempt,
                    f'{self.filename_suffix}_number': self.number}
                fields.update(camera_first_frame=frame,
                    camera_first_frame_monotonic_sec=observed, camera_first_frame_pts_sec=pts,
                    camera_start_observed_monotonic_sec=time.perf_counter(),
                    camera_time_basis='software observation of first FFmpeg frame')
                self.boundary('recording_start', fields)
                if on_started is not None:
                    on_started(**fields)
                self._log('recording_started', **fields)
                start_reported = True
            if (len(self.frames) >= 16 and self.frames[-1][1] - self.frames[0][1] >= .5
                    and self.path.stat().st_size > 0):
                return
            time.sleep(.01)
        raise FacialRecordingError('摄像头未在15秒内稳定输出1080p/30帧录像。')

    def _input_args(self):
        return ['-f', 'dshow', '-rtbufsize', '256M', '-video_size',
                f'{self.input_width}x{self.input_height}', '-framerate', '30',
                *(['-pixel_format', self.input_pixel_format] if self.input_pixel_format else []),
                *(['-vcodec', self.input_codec] if self.input_codec else []),
                '-i', f'video={self.device}']

    def _video_filter(self):
        scale = 'scale=1920:1080,' if (self.input_width, self.input_height) != (1920, 1080) else ''
        return 'setpts=PTS-STARTPTS,' + scale + 'showinfo'

    def _read(self):
        try:
            for raw in iter(self.process.stderr.readline, b''):
                line = raw.decode('utf-8', errors='replace')
                match = FRAME.search(line)
                if match and 'showinfo' in line:
                    self.frames.append((int(match[1]), time.perf_counter(), float(match[2])))
                self.errors.append(line.rstrip())
                if len(self.errors) > 80:
                    del self.errors[0]
        except Exception as exc:
            self.errors.append(str(exc))

    def check(self, startup=False):
        if self.process is None:
            return
        if self.process.poll() is not None:
            raise FacialRecordingError('摄像头录制进程退出：' + '\n'.join(self.errors[-8:]))
        if not startup and (not self.frames or time.perf_counter() - self.frames[-1][1] > 1):
            raise FacialRecordingError('摄像头超过1秒没有新帧。')

    def boundary(self, name, event):
        self.events[name] = dict(event)

    def _log(self, status, **fields):
        row = dict(code=self.code, number=self.number, attempt=self.attempt, file=self.path.name,
                   device=self.device, width=1920, height=1080, requested_fps=30,
                   input_width=self.input_width, input_height=self.input_height,
                   input_pixel_format=self.input_pixel_format, input_codec=self.input_codec,
                   spatial_resize=(self.input_width, self.input_height) != (1920, 1080),
                   status=status, clock_mapping=self.clock, events=self.events, **fields)
        with (self.directory / self.log_filename).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            stream.flush()

    def _validate_coverage(self, onset, offset, duration, decoded):
        validate_coverage(self.frames, onset, offset, duration, decoded)

    def finish(self, complete=False, material_duration=0):
        if self.closed:
            return
        self.closed = True
        failure = None
        try:
            if self.process is not None:
                if complete:
                    deadline = time.perf_counter() + 3
                    target = self.events['video_off']['monotonic_sec'] + .5
                    while not self.frames or self.frames[-1][1] < target:
                        self.check()
                        if time.perf_counter() > deadline:
                            raise FacialRecordingError('录像后录时间不足。')
                        time.sleep(.01)
        except Exception as exc:
            failure = exc
        finally:
            if self.process is not None:
                try:
                    self.process.stdin.write(b'q\n')
                    self.process.stdin.flush()
                    self.process.wait(timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    self.process.kill()
                    self.process.wait(timeout=5)
                    failure = failure or FacialRecordingError('摄像头关闭失败。')
                self.thread.join(timeout=5)
                self.process.stdin.close()
                self.process.stderr.close()
                if self.process.returncode:
                    failure = failure or FacialRecordingError('录像编码失败。')
        if self.path is None:
            if failure:
                raise failure
            return
        onset = self.events.get('video_on', {}).get('monotonic_sec')
        try:
            encoded_pts = []
            decoded = None
            if self.frames and self.path.stat().st_size:
                try:
                    probe = self._command(['-hide_banner', '-xerror', '-i', str(self.path), '-an', '-vf', 'showinfo',
                        '-fps_mode', 'passthrough', '-f', 'null', '-'],
                        timeout=max(30, float(material_duration or 0) * 2))
                    encoded_pts = [float(m[1]) for m in FRAME.findall(probe.stderr)]
                    if probe.returncode or len(encoded_pts) < 2 or len(encoded_pts) != len(self.frames):
                        raise FacialRecordingError('录像解码或帧数核验失败。')
                    decoded = encoded_pts[-1] - encoded_pts[0] + (encoded_pts[-1] - encoded_pts[-2])
                except Exception as exc:
                    failure = failure or exc
            with self.path.with_suffix('.timestamps.csv').open('x', newline='', encoding='utf-8') as stream:
                writer = csv.writer(stream)
                writer.writerow(['frame', 'arrival_monotonic_sec', 'capture_pts_sec', 'encoded_pts_sec',
                                 self.relative_time_column])
                for i, (n, arrival, pts) in enumerate(self.frames):
                    writer.writerow([n, arrival, pts, encoded_pts[i] if i < len(encoded_pts) else '',
                                     arrival-onset if onset is not None else ''])
            alignment = onset_frame_alignment(self.frames, onset, encoded_pts)
            self._log('onset_frame_alignment', alignment=alignment)
            if complete and failure is None:
                if decoded is None:
                    raise FacialRecordingError('没有可验证的录像帧。')
                self._validate_coverage(onset, self.events['video_off']['monotonic_sec'],
                                        float(material_duration), decoded)
            if failure:
                raise failure
            self._log('passed' if complete else 'interrupted', frame_count=len(self.frames),
                      decoded_duration_sec=decoded, material_duration_sec=material_duration,
                      max_observed_frame_interval_sec=max((b[1]-a[1] for a,b in zip(self.frames,self.frames[1:])),default=0),
                      software_preroll_sec=(onset-self.frames[0][1] if onset is not None and self.frames else None),
                      software_postroll_sec=(self.frames[-1][1]-self.events['video_off']['monotonic_sec']
                          if 'video_off' in self.events and self.frames else None))
        except Exception as exc:
            self._log('failed', error=str(exc), frame_count=len(self.frames))
            raise FacialRecordingError(str(exc)) from exc
