"""Emotion trials in the existing VideoRunner/continuous EEG framework."""
from __future__ import annotations
import csv
import os
import time
from dataclasses import asdict
from pathlib import Path
from video_eeg.experiment import video_runner as base
from video_eeg.utils.emotion_protocol import RATING_PAGES, parse_rating, presentation_order
from video_eeg.utils.session_protocol import save_state_atomic

class EmotionVideoRunner(base.VideoRunner):
    task_type = 'emotion_rating'
    natural_eof_only = True

    def _initialize_new_state(self):
        self.state.attention_task_type = self.task_type
        self.state.manifest_hash = self.config['session_manifest_hash']
        self.state.queue_video_ids = presentation_order(list(self.library.rows.values()),
                self.state.random_seed, self.state.subject_id, self.state.session_id)

    def _show_instructions(self):
        self._show_text(
            '本实验将连续播放多段视频，请保持舒适坐姿、认真观看并尽量减少动作。\n\n'
            '部分视频结束后，请依次评价自己的情绪感受和唤醒程度。\n'
            '按数字键 1–9 作答，没有标准答案，答题不限时。\n\n'
            '视频之间有短暂休息，空格可提前继续。累计观看约 30–45 分钟后可较长休息，'
            '按 F 继续，按 J 保存退出。\n\n'
            'S 可暂时跳过当前视频，稍后重新观看；Esc 可保存退出。\n'
            '未完整观看或尚未完成两项评分的视频，会在继续实验时重新播放。\n\n按空格键继续。')

    def _start_eeg(self, connection):
        super()._start_eeg(connection)
        self._event_times = {}
        self._active_row = None
        self._warnings = []
        original_emit = self.manager.emit
        def emit(name, **payload):
            source_name = name
            row = self._active_row
            if name=='trial_end' and row and row['trial_type']=='emotion' and payload.get('completed') and not payload.get('ratings_completed'):
                return  # A complete emotion trial includes both ratings.
            context = dict(protocol_version='emotion-v1', timestamp_unix_sec=time.time(),
                           monotonic_sec=time.perf_counter(), eeg_part=self.manager.eeg_part)
            if row:
                context.update(trial_type=row['trial_type'], video_id=row['video_id'],
                    trial_id=self._active_trial, attempt_id=self._active_attempt,
                    original_label=row['original_label'], three_class_label=row['three_class_label'])
                if row['trial_type']=='emotion':
                    name = {'video_on':'EMOTION_VIDEO_ONSET', 'video_off':'EMOTION_VIDEO_OFFSET'}.get(name, name)
                name = {'break_start':'SHORT_REST_ONSET', 'break_end':'SHORT_REST_OFFSET'}.get(name, name)
            context.update(payload)
            original_emit(name, **context)
            # Store the exact sample index assigned by the recorder, not a later sample count.
            recorded = self.manager.recorder.events[-1]
            self._event_times[source_name] = dict(monotonic_sec=context['monotonic_sec'],
                timestamp_unix_sec=context['timestamp_unix_sec'], sample_index=recorded.sample_index,
                relative_time_sec=recorded.relative_time_sec)
        self.manager.emit = emit

    def _run_trial(self, trial_idx, asset):
        self._active_row = self.library.rows[asset.asset_id]
        self._active_trial = trial_idx
        self._active_attempt = self._attempt_counter_by_video.get(asset.asset_id, 0)+1
        self._event_times = {}
        result = super()._run_trial(trial_idx, asset)
        if not result and self.state.video_attempts[-1].get('abort_reason') in {'playback_error','premature_eof'}:
            raise RuntimeError('视频未能完整解码，当前视频保留待重播。请主试核验材料与播放器。')
        return result

    def _create_movie(self, media_path):
        # Preserve the production player. A player failure must not silently switch to muted playback.
        movie = base.OpenCVVideoPlayer(self.win, str(media_path), autoLog=False)
        expected_audio = str(self._active_row.get('has_audio', '')).lower()=='true'
        if expected_audio and movie._audio_data is None:
            movie.unload()
            raise RuntimeError('该视频应有音轨，但音频加载失败。请检查音频依赖与临时目录。')
        old_start_audio = movie._start_audio
        def checked_start_audio():
            old_start_audio()
            if movie._audio_data is not None and not movie._audio_started:
                raise RuntimeError('音频输出启动失败，请检查扬声器/耳机和系统音频设备。')
        movie._start_audio = checked_start_audio
        width, height = movie.getVideoSize()
        scale = min(self.win.size[0]/width, self.win.size[1]/height)
        movie.size = width*scale, height*scale
        return movie

    def _record_video_attempt(self, record, *, completed_naturally, skipped):
        row = self.library.rows[record.asset_id]
        record.trial_type = row['trial_type']
        actual = max(0., record.actual_video_sec)
        self.state.completed_net_video_duration_sec += actual
        self.state.continuous_net_video_duration_sec += actual
        record.session_completed_net_sec = self.state.completed_net_video_duration_sec
        attempt = dict(**asdict(record), video_id=record.asset_id,
                       completed=completed_naturally and row['trial_type']=='ordinary',
                       original_label=row['original_label'], three_class_label=row['three_class_label'],
                       image_onset=record.eeg_relative_onset_sec, image_offset=record.eeg_relative_offset_sec)
        if row['trial_type']=='emotion':
            onset, offset = self._event_times.get('video_on', {}), self._event_times.get('video_off', {})
            attempt['emotion_rating'] = dict(subject_id=self.state.subject_id, session_id=self.state.session_id,
                trial_id=record.trial_idx, attempt_id=record.attempt_id, video_id=record.asset_id,
                video_path=record.rel_path, original_label=row['original_label'], three_class_label=row['three_class_label'],
                duration_sec=record.video_duration_sec, actual_video_sec=actual,
                video_onset=onset.get('monotonic_sec', record.video_onset), video_offset=offset.get('monotonic_sec', record.video_offset),
                video_onset_unix_sec=onset.get('timestamp_unix_sec'), video_offset_unix_sec=offset.get('timestamp_unix_sec'),
                video_onset_sample_index=onset.get('sample_index'), video_offset_sample_index=offset.get('sample_index'),
                eeg_part=record.eeg_part, eeg_recording_dir=str(self.manager.session_dir),
                completed=False, interrupted=not completed_naturally, replacement_reason=row.get('replacement_reason',''),
                **{f'{page}_{field}':None for page,_,_ in RATING_PAGES for field in
                   ('rating','rt_sec','onset','response','key','onset_unix_sec','response_unix_sec','onset_sample_index','response_sample_index')})
        self.state.video_attempts.append(attempt)
        if attempt['completed']:
            self.state.commit_completed_video(record.asset_id, 0.)
        elif skipped:
            self.state.requeue_skipped_video(record.asset_id)
        else:
            self.state.preserve_aborted_video(record.asset_id)
        self._checkpoint('rating_pending' if completed_naturally and not attempt['completed'] else record.status)
        self._write_rating_log()

    def _run_post_video_rest(self, *, trial_idx, asset, record):
        if self.library.rows[asset.asset_id]['trial_type']=='emotion':
            attempt = self.state.video_attempts[-1]
            row = attempt['emotion_rating']
            try:
                for page, wording, anchors in RATING_PAGES:
                    self._rating_page(row, page, wording, anchors)
                assert all(isinstance(row[p+'_rating'], int) and 1<=row[p+'_rating']<=9 for p,_,_ in RATING_PAGES)
                self.manager.emit('trial_end', completed=True, ratings_completed=True, status='completed')
                row['completed'], row['interrupted'] = True, False
                attempt['completed'] = True
                self.state.commit_completed_video(asset.asset_id, 0.)
                self._checkpoint('emotion_video_and_ratings_completed')
            except BaseException:
                row['interrupted'] = True
                try:
                    self.manager.emit('trial_end', completed=False, ratings_completed=False, status='rating_interrupted')
                except Exception as exc:
                    self._warn(f'interrupted trial marker: {exc}')
                self.state.preserve_aborted_video(asset.asset_id)
                self._checkpoint('emotion_rating_interrupted')
                raise
            finally:
                self._write_rating_log()
        super()._run_post_video_rest(trial_idx=trial_idx, asset=asset, record=record)

    def _rating_page(self, row, page, wording, anchors):
        self._clear_keyboard()
        self.message.text = wording+'\n\n'+anchors+'\n\n1    2    3    4    5    6    7    8    9\n\n请按数字键 1–9 作答，答题不限时。'
        self.message.height = .032
        self.message.pos = (0, 0)
        self.message.draw()
        event_name = page.upper()+'_RATING_ONSET'
        if hasattr(self.keyboard, 'clock'):
            self.win.callOnFlip(self.keyboard.clock.reset)
        self.win.callOnFlip(self.manager.emit, event_name)
        self.win.flip()
        stamp = self._event_times[event_name]
        row[page+'_onset'] = stamp['monotonic_sec']
        row[page+'_onset_unix_sec'] = stamp['timestamp_unix_sec']
        row[page+'_onset_sample_index'] = stamp['sample_index']
        self._checkpoint(page+'_onset')
        # The preceding page's held key must be released before the next answer.
        released = not hasattr(self.keyboard, 'getState') or not any(self.keyboard.getState(list('123456789')))
        while True:
            self._require_manager()
            keys = self.keyboard.getKeys(['escape']+list('123456789')+['num_'+str(i) for i in range(1,10)], waitRelease=False, clear=True)
            if any(str(getattr(k,'name',k)).lower()=='escape' for k in keys):
                raise base.ExperimentAbort()
            if not released:
                released = not any(self.keyboard.getState(list('123456789')))
                base.core.wait(.005)
                continue
            for key in keys:
                rating = parse_rating(key)
                if rating is None:
                    continue
                detected_time = time.perf_counter()
                key_rt = getattr(key, 'rt', None)
                rt = max(0., float(key_rt)) if key_rt is not None else max(0., detected_time-row[page+'_onset'])
                response_time = row[page+'_onset']+rt
                event_name = page.upper()+'_RATING_RESPONSE'
                self.manager.emit(event_name, rating=rating, response_key=str(getattr(key,'name',key)), response_rt_sec=rt,
                                  response_monotonic_sec=response_time, response_detected_monotonic_sec=detected_time)
                stamp = self._event_times[event_name]
                row.update({page+'_rating':rating, page+'_rt_sec':rt,
                    page+'_response':response_time, page+'_key':str(getattr(key,'name',key)),
                    page+'_response_unix_sec':stamp['timestamp_unix_sec'],
                    page+'_response_sample_index':stamp['sample_index']})
                self._checkpoint(page+'_response')
                self._write_rating_log()
                return
            base.core.wait(.005)

    def _checkpoint(self, reason):
        if self.state is None or self.state_path is None:
            return
        self.state.last_exit_reason = reason
        self.state.latest_resume_timestamp = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        # State is authoritative; a spreadsheet holding a derived CSV open cannot lose progress.
        save_state_atomic(self.state_path, self.state, last_exit_reason=reason)
        try:
            self._write_session_summary()
        except OSError as exc:
            self._warn(f'session_summary: {exc}')

    def _warn(self, message):
        if not hasattr(self, '_warnings'):
            self._warnings = []
        self._warnings.append(str(message))
        print('Export warning: '+str(message), flush=True)

    def _write_csv(self, name, rows):
        if not rows:
            return
        path = self.progress_dir/name
        temp = path.with_name(path.name+'.writing')
        with temp.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=sorted({k for row in rows for k in row}))
            writer.writeheader(); writer.writerows(rows)
            f.flush(); os.fsync(f.fileno())
        try:
            temp.replace(path)
        except PermissionError:
            fallback = path.with_name(path.stem+f'.recovered_{time.time_ns()}.csv')
            temp.replace(fallback)
            self._warn(f'{name} locked; current complete export saved to {fallback.name}')

    def _write_rating_log(self):
        self._write_csv('emotion_rating_log.csv', [r['emotion_rating'] for r in self.state.video_attempts if 'emotion_rating' in r])

    def _write_trial_log(self):
        self._write_csv('trial_log.csv', [{k:v for k,v in r.items() if k!='emotion_rating'} for r in self.state.video_attempts])

    def _write_attention_log(self):
        pass

    def _write_rest_log(self):
        self._write_csv('rest_log.csv', self.state.rest_events)

    def _session_progress(self):
        assigned = sum(float(a.duration_sec or 0) for a in self.playlist)
        completed = sum(float(self._asset_by_id[k].duration_sec or 0) for k in self.state.completed_video_ids)
        return 100*completed/assigned if assigned else 0.

    def _session_exit_text(self):
        return (f'本 Session 已完成 {self._session_progress():.1f}%。\n\n'
                f'已完成视频：{len(self.state.completed_video_ids)}/{len(self.state.video_ids)}\n'
                f'累计实际观看：{self.state.completed_net_video_duration_sec/60:.1f} 分钟（含重播部分）\n\n'
                '数据已保存。未完成的视频将在续跑时重播。')

    def _stop_and_export(self):
        if self.manager is None:
            return None
        for write in (self._write_trial_log, self._write_rating_log, self._write_rest_log,
                      lambda: self._checkpoint(self.termination_reason)):
            try:
                write()
            except Exception as exc:
                self._warn(repr(exc))
        return self.manager.stop_and_export(metadata=dict(protocol_version='emotion-v1',
            completed=self.completed, termination_reason=self.termination_reason,
            session_completed=self.state.session_completed, completed_video_trials=len(self.state.completed_video_ids),
            rating_stage_present=True, attention_enabled=False, attention_tasks_per_session=0,
            emotion_rating_log=str(self.progress_dir/'emotion_rating_log.csv'),
            actual_net_video_duration_sec=self.state.completed_net_video_duration_sec,
            net_clock_definition='actual ordinary + emotion playback including partial attempts; excludes ratings/rest',
            rating_scale='integer 1-9', rating_order=['valence','arousal'],
            export_warnings=getattr(self, '_warnings', []), real_hardware_validation='pending'))

def main(argv=None):
    old_demo, old_default = base.DEMO_CONFIG_FILENAME, base.DEFAULT_CONFIG_FILENAME
    try:
        base.DEMO_CONFIG_FILENAME = 'video_emotion_demo_config.yaml'
        base.DEFAULT_CONFIG_FILENAME = 'video_emotion_config.yaml'
        return base.main(argv)
    finally:
        base.DEMO_CONFIG_FILENAME, base.DEFAULT_CONFIG_FILENAME = old_demo, old_default

if __name__=='__main__':
    raise SystemExit(main())
