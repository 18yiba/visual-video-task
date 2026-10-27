"""V2 acquisition with independently resumable, EEG-free emotion ratings."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from dataclasses import replace

from video_eeg.experiment.emotion_v2_runner import EmotionV2Runner, base
from video_eeg.experiment.emotion_runner import EmotionVideoRunner


def configure_emotion_only(config):
    if not config.get('protocol', {}).get('separate_emotion_ratings'):
        raise ValueError('仅情绪视频模式仅适用于 v3。')
    if not config['protocol'].get('emotion_only'):
        config['storage']['records_dir'] += '_emotion_only'
    config['protocol'].update(emotion_only=True, attention_enabled=False, attention_tasks_per_session=0)


def eeg_saved(attempt):
    """Require a complete playback, growing sample indices and its saved EEG part."""
    row = attempt.get('emotion_rating', {})
    if row.get('eeg_recording_mode') == 'emotivpro_external':
        from video_eeg.utils.emotivpro_recording import external_eeg_saved
        return external_eeg_saved(attempt)
    onset, offset = row.get('video_onset_sample_index'), row.get('video_offset_sample_index')
    if not attempt.get('video_completed_naturally') or not isinstance(onset, int) or not isinstance(offset, int) or offset <= onset:
        return False
    directory = Path(row.get('eeg_recording_dir', ''))
    for path in directory.glob('metadata*.json'):
        try:
            metadata = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if metadata.get('eeg_part') != row.get('eeg_part'):
            continue
        if metadata.get('device_type') == 'neuracle' and metadata.get('neuracle_trigger') is not None:
            trigger = metadata['neuracle_trigger']
            if metadata.get('neuracle_saved_trigger_required') and metadata.get('neuracle_saved_trigger', {}).get('status') != 'passed':
                return False
            if (metadata.get('background_error') or trigger.get('error') or trigger.get('pending_codes')
                    or trigger.get('confirmed_count', 0) != trigger.get('sent_count', 0)
                    or metadata.get('neuracle_forwarding', {}).get('error')):
                return False
        filename = metadata.get('eeg_file')
        return bool(metadata.get('local_eeg_recorded') and metadata.get('sample_count', 0) >= offset
                    and filename and Path(filename).name == filename
                    and (directory / filename).is_file() and (directory / filename).stat().st_size > 0)
    return False


class BehaviorEvents:
    """Only wall/monotonic timestamps; never instantiate an EEG device or marker."""
    def __init__(self, runner):
        self.runner = runner

    def raise_if_background_failed(self):
        pass

    def emit(self, name, **payload):
        self.runner._event_times[name] = dict(monotonic_sec=time.perf_counter(),
            timestamp_unix_sec=time.time(), sample_index=None, relative_time_sec=None)


class EmotionV3Runner(EmotionV2Runner):
    task_type = 'emotion_v3_separate_eeg_ratings_7'
    protocol_version = 'emotion-v3'
    acquisition_rating_stage_present = False

    def _start_eeg(self, connection):
        from video_eeg.experiment.facial_recording import FacialRecorder
        pending = [v for v in self.state.queue_video_ids if self.library.rows[v]['trial_type'] == 'emotion']
        if pending:
            FacialRecorder(self.progress_dir, 'preflight', 0).preflight()
        return super()._start_eeg(connection)

    def _run_trial(self, trial_idx, asset):
        from video_eeg.experiment.facial_recording import FacialRecorder
        facial = None
        if self.stage == 'eeg' and self.library.rows[asset.asset_id]['trial_type'] == 'emotion':
            facial = FacialRecorder(self.progress_dir, Path(asset.rel_path).stem,
                self._attempt_counter_by_video.get(asset.asset_id, 0) + 1)
        self._facial_recorder = facial
        original_emit = self.manager.emit
        def emit(name, **payload):
            original_emit(name, **payload)
            if facial is not None and name in {'video_on', 'video_off'}:
                facial.boundary(name, self._event_times[name])
        self.manager.emit = emit
        try:
            return super()._run_trial(trial_idx, asset)
        except BaseException:
            if facial is not None and hasattr(getattr(self, 'win', None), '_toCall'):
                self.win._toCall.clear()
            raise
        finally:
            self.manager.emit = original_emit
            self._facial_recorder = None
            if facial is not None:
                try:
                    facial.finish()
                finally:
                    movie = getattr(self, '_active_movie', None)
                    if movie is not None:
                        movie.unload()

    def __init__(self, **kwargs):
        cfg = kwargs['config']
        self.stage = cfg.get('emotion_stage', 'eeg')
        if self.stage == 'eeg' and not cfg.get('demo_mode') and not cfg.get('hardware_dummy_mode'):
            from video_eeg.utils import eegqc_export as q
            participant, code = q.v3_capture_identity(cfg)
            cfg.update(platform_participant_id=participant, paradigm_code=code)
        emotion_only = cfg['protocol'].get('emotion_only', False)
        if emotion_only:
            from video_eeg.utils.emotion_protocol import EmotionLibrary
            rows = [r for r in kwargs['library'].rows.values() if r['trial_type'] == 'emotion']
            if not rows:
                raise ValueError('本Session没有情绪视频。')
            kwargs['library'] = EmotionLibrary(rows, kwargs['library'].roots)
            kwargs['playlist'] = [a for a in kwargs['playlist'] if a.asset_id in kwargs['library'].rows]
            kwargs['protocol'] = replace(kwargs['protocol'], attention_enabled=False, attention_tasks_per_session=0)
            cfg['excluded_video_ids'] = []
            self.task_type = 'emotion_v3_emotion_only_7'
            self.questions = {}; self.question_bank_sha256 = ''; self.fatigue_scale_max = 5
            self.interval_sec = float(cfg['protocol'].get('alarm_interval_net_sec', 600))
            cfg['session_manifest_hash'] += ':emotion-only'
        # A new contract and directory: never reinterpret an existing v2 Session.
        cfg['session_manifest_hash'] += ':emotion-v3-separated-v1'
        if self.stage == 'ratings':
            root = base._records_dir(cfg) / str(cfg.get('subject_id', 'S001'))
            if cfg.get('demo_mode'):
                root /= f"run_{kwargs['protocol'].random_seed}"
            if not (root / f"session_{int(cfg.get('session_id', 1)):02d}" / 'session_state.json').is_file():
                raise RuntimeError('本 v3 Session 尚无 EEG 采集进度，不能进行行为评分。')
        if emotion_only:
            EmotionVideoRunner.__init__(self, **kwargs)
        else:
            super().__init__(**kwargs)
        self._event_times = {}
        self._write_emotion_list()

    def _write_emotion_list(self):
        rows = []
        for video_id in self.state.video_ids:
            source = self.library.rows[video_id]
            if source['trial_type'] != 'emotion':
                continue
            attempts = [a for a in self.state.video_attempts if a['video_id'] == video_id]
            eligible = [a for a in attempts if eeg_saved(a)]
            rows.append(dict(video_id=video_id, video_path=source['video_path'],
                original_label=source['original_label'], three_class_label=source['three_class_label'],
                eeg_saved=bool(eligible), rating_completed=any(a['emotion_rating'].get('completed') for a in eligible)))
        self._write_csv('emotion_video_list.csv', rows)

    def _show_instructions(self):
        if self.config['protocol'].get('emotion_only'):
            self._show_text('v3 仅情绪视频EEG采集：只观看本Session的情绪视频，不评分。\n'
                '采集保存退出后，在相同视频范围下进入行为评分。\n'
                'S 暂时跳过并重播；Esc 保存退出。\n\n按空格继续。')
            return
        self._show_text('v3 EEG采集：情绪视频完整观看后不评分。\n'
            '普通视频喜好、内容抽查、疲劳和休息与 v2 相同。\n'
            '情绪评分请在采集保存退出后，通过“行为评分”入口进行。\n'
            'S 暂时跳过并重播；Esc 保存退出。\n\n按空格继续。')

    def _run_post_video_rest(self, *, trial_idx, asset, record):
        if self.library.rows[asset.asset_id]['trial_type'] != 'emotion':
            return super()._run_post_video_rest(trial_idx=trial_idx, asset=asset, record=record)
        attempt = self.state.video_attempts[-1]
        self._require_manager()
        row = attempt['emotion_rating']
        onset, offset = row.get('video_onset_sample_index'), row.get('video_offset_sample_index')
        if base.uses_emotivpro_recording(getattr(self, 'config', {})):
            self.manager.raise_if_background_failed()
            begin, end = row.get('video_onset_unix_sec'), row.get('video_offset_unix_sec')
            if not attempt.get('video_completed_naturally') or begin is None or end is None or end <= begin:
                raise RuntimeError('情绪视频未完整播放并发送起止标记，保留待重播。')
            row['eeg_recording_mode'] = 'emotivpro_external'
        elif not isinstance(onset, int) or not isinstance(offset, int) or offset <= onset:
            raise RuntimeError('情绪视频未收到 EEG 样本，不能标记采集完成或开放评分。')
        attempt['completed'] = True
        self.state.commit_completed_video(asset.asset_id, 0.)
        self.manager.emit('trial_end', completed=True, ratings_completed=False, eeg_only=True)
        self._checkpoint('emotion_eeg_completed_rating_pending')
        return base.VideoRunner._run_post_video_rest(self, trial_idx=trial_idx, asset=asset, record=record)

    def _stop_and_export(self):
        directory = super()._stop_and_export()
        self._write_emotion_list()
        return directory

    def _replay(self, asset, speed):
        self._active_row = self.library.rows[asset.asset_id]
        movie = self._create_movie(self.library.resolve(asset))
        try:
            if speed != 1:
                if movie._audio_data is not None:
                    from imageio_ffmpeg import get_ffmpeg_exe
                    import soundfile as sf
                    with tempfile.TemporaryDirectory() as temporary:
                        target = Path(temporary) / 'speed.wav'
                        subprocess.run([get_ffmpeg_exe(), '-y', '-i', str(movie._audio_temp_path),
                            '-af', f'atempo={speed}', str(target)], check=True, capture_output=True)
                        movie._audio_data, movie._audio_rate = sf.read(str(target), dtype='float32')
                movie._fps *= speed
                movie._frame_interval /= speed
            movie.play()
            self._clear_keyboard()
            while not movie.isFinished:
                self._check_abort()
                movie.draw()
                self.win.flip()
                base.core.wait(.001)
            if movie._ended_prematurely:
                raise RuntimeError('行为重播未完整解码，未提交评分。')
        finally:
            movie.unload()

    def _rate_attempt(self, attempt):
        if not eeg_saved(attempt):
            raise RuntimeError('该视频尚无完整、已保存的 EEG 采集，不允许评分。')
        row = attempt['emotion_rating']
        try:
            self._event_times = {}
            key = self._choice_page({}, 'replay_speed', '请选择本次行为重播速度。',
                ['1  原速', '2  1.5倍速', '3  2倍速'], ['1', '2', '3'], 'REPLAY_SPEED')
            speed = {'1': 1., '2': 1.5, '3': 2.}[key]
            self._replay(self._asset_by_id[attempt['video_id']], speed)
            row.update(behavior_eeg_recorded=False, behavior_playback_speed=speed, completed=False)
            for page, wording, anchors in self.rating_pages:
                self._rating_page(row, page, wording, anchors)
            row.update(completed=True, interrupted=False)
            self._checkpoint('emotion_behavior_completed')
        except BaseException:
            row['interrupted'] = True
            self._checkpoint('emotion_behavior_interrupted')
            raise
        finally:
            self._write_rating_log()
            self._write_emotion_list()

    def run(self):
        if self.stage == 'eeg':
            return super().run()
        self.manager = BehaviorEvents(self)
        try:
            self._show_text('v3 行为评分：本阶段不连接或采集 EEG。\n'
                '只重播已完整采集且保存 EEG 的情绪视频。\n'
                '选择原速、1.5或2倍速；之后效价和唤醒均按1–7评分。\n'
                'Esc 保存退出；未完成评分续跑时重播并重答两项。\n\n按空格继续。')
            # One completed EEG attempt per video, in the saved viewing order.
            selected = {}
            for attempt in self.state.video_attempts:
                if 'emotion_rating' in attempt and eeg_saved(attempt):
                    selected.setdefault(attempt['video_id'], attempt)
            for attempt in selected.values():
                if not attempt['emotion_rating'].get('completed'):
                    self._rate_attempt(attempt)
            self._show_text('已保存全部可评分视频的行为结果。\n未采集或未保存 EEG 的视频不可评分。\n\n按空格退出。')
        except base.ExperimentAbort:
            self._checkpoint('emotion_behavior_exit')
        finally:
            self._write_rating_log()
            self._write_emotion_list()
            self.manager = None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(arg in {'--demo', '--dummy-eeg'} for arg in argv):
        raise ValueError('v3已移除Dummy测试入口，请使用真实EEG采集或独立行为评分。')
    if not any(arg.split('=')[0] == '--device-type' for arg in argv):
        argv += ['--device-type', 'emotivpro']
    args = base.parse_args(argv)
    if args.device_type == 'emotivpro' and args.emotion_stage == 'eeg' and not args.emotivpro_port and not args.doctor:
        from video_eeg.utils.emotivpro_port_dialog import select_port
        port = select_port()
        if not port:
            return 0
        argv += ['--emotivpro-port', port]
    return base.main(argv, default_config_filename='video_emotion_v3_config.yaml',
                     demo_config_filename='video_emotion_v3_demo_config.yaml')


if __name__ == '__main__':
    raise SystemExit(main())
