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


def reserve_path(directory, code):
    """Exclusive reservation also protects orphaned/partial recordings."""
    if not code or any(c in code for c in '<>:"/\\|?*'):
        raise FacialRecordingError('无效的情绪视频编码。')
    directory = Path(directory)
    used = []
    pattern = re.compile(re.escape(code) + r'_facial(?:_(\d+))?\.mp4$')
    for p in directory.iterdir():
        match = pattern.fullmatch(p.name)
        if match:
            used.append(int(match[1] or 1))
    log = directory / 'facial_recording_log.jsonl'
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
        suffix = '' if number == 1 else f'_{number:02d}'
        path = directory / f'{code}_facial{suffix}.mp4'
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


class FacialRecorder:
    device = 'UGREEN Camera 4K'

    def __init__(self, directory, code, attempt):
        from imageio_ffmpeg import get_ffmpeg_exe
        self.exe = get_ffmpeg_exe()
        self.directory, self.code, self.attempt = Path(directory), code, attempt
        self.frames, self.errors, self.events = [], [], {}
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
        # Some Windows drivers enumerate their camera with the type "none".
        names = re.findall(r'"([^"]+)" \((?:video|none)\)', devices)
        if names.count(self.device) != 1:
            raise FacialRecordingError(f'摄像头缺失或同名歧义：{self.device}')
        probe = self._command(['-hide_banner', '-f', 'dshow', '-video_size', '1920x1080',
            '-framerate', '30', '-i', f'video={self.device}', '-t', '0.2', '-an',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-f', 'null', '-'])
        if probe.returncode or not re.search(r'1920x1080.*30 fps', probe.stderr):
            raise FacialRecordingError('摄像头1080p/30帧或H.264预检失败：' + probe.stderr[-1800:])
        if not self.directory.is_dir():
            raise FacialRecordingError('Session保存目录不存在。')

    def start(self):
        self.preflight()
        self.path, self.number = reserve_path(self.directory, self.code)
        self._log('reserved')
        args = [self.exe, '-hide_banner', '-y', '-copyts', '-start_at_zero', *self._input_args(),
                '-an', '-vf', 'setpts=PTS-STARTPTS,showinfo', '-c:v', 'libx264',
                '-preset', 'ultrafast', '-crf', '20', '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough',
                '-movflags', '+frag_keyframe+empty_moov+default_base_moof', str(self.path)]
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        deadline = time.perf_counter() + 15
        while time.perf_counter() < deadline:
            self.check(startup=True)
            if (len(self.frames) >= 16 and self.frames[-1][1] - self.frames[0][1] >= .5
                    and self.path.stat().st_size > 0):
                return
            time.sleep(.01)
        raise FacialRecordingError('摄像头未在15秒内稳定输出1080p/30帧录像。')

    def _input_args(self):
        return ['-f', 'dshow', '-rtbufsize', '256M', '-video_size', '1920x1080',
                '-framerate', '30', '-i', f'video={self.device}']

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
                   status=status, clock_mapping=self.clock, events=self.events, **fields)
        with (self.directory / 'facial_recording_log.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            stream.flush()

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
                                 'relative_video_onset_sec'])
                for i, (n, arrival, pts) in enumerate(self.frames):
                    writer.writerow([n, arrival, pts, encoded_pts[i] if i < len(encoded_pts) else '',
                                     arrival-onset if onset is not None else ''])
            if complete and failure is None:
                if decoded is None:
                    raise FacialRecordingError('没有可验证的录像帧。')
                validate_coverage(self.frames, onset, self.events['video_off']['monotonic_sec'],
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
