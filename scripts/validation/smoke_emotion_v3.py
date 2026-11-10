"""Real PsychoPy windows, dummy EEG; collection, ratings, abort and resume."""
import copy
import hashlib
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from video_eeg.experiment.emotion_v3_runner import EmotionV3Runner, eeg_saved, base, configure_emotion_only
from video_eeg.utils.emotion_protocol import prepare


def main():
    if '--facial-synthetic' in sys.argv or '--action-synthetic' in sys.argv:
        # Test-only synthetic source; production keeps strict named-camera checks.
        from video_eeg.experiment.facial_recording import FacialRecorder
        FacialRecorder.preflight = lambda self: None
        FacialRecorder._input_args = lambda self: ['-re', '-f', 'lavfi', '-i', 'testsrc2=size=1920x1080:rate=30']
    base._load_psychopy()
    cfg = base.load_config(base.CONFIG_DIR / 'video_emotion_v3_demo_config.yaml')
    cfg.update(_project_dir=str(base.PROJECT_ROOT), subject_id='AUTO_V3_' + str(time.time_ns()), explicit_run_seed=20260912, _integrated_startup=True)
    cfg['facial_recording_enabled'] = '--no-facial' not in sys.argv
    cfg['action_recording_enabled'] = '--action-synthetic' in sys.argv
    if cfg['action_recording_enabled']:
        cfg['device_type'] = 'neuracle'
    cfg['protocol'].update(fixation_sec=.1, post_video_rest_seconds=.1, random_seed=20260912)
    cfg['storage']['records_dir'] = 'data/sourcedata/demo/v3_smoke'
    if '--emotion-only' in sys.argv:
        configure_emotion_only(cfg)
    library, playlist = prepare(cfg, True)
    nas_test='--nas-material-root' in sys.argv
    if nas_test:
        import csv
        from video_eeg.utils.emotion_protocol import EmotionLibrary
        from video_eeg.utils.video_library import VideoAsset
        nas=Path(sys.argv[sys.argv.index('--nas-material-root')+1])
        manifest=base.CONFIG_DIR/'session_manifest_v2_active.csv'
        with manifest.open(encoding='utf-8-sig',newline='') as stream:
            rows=[r for r in csv.DictReader(stream) if r['session_id']=='1' and r['trial_type']=='emotion']
        selected=[min((r for r in rows if r['three_class_label']==label),key=lambda r:float(r['video_duration_sec']))
                  for label in ['positive','neutral','negative']]
        library=EmotionLibrary(selected,{'original':nas/'videos','emotion':nas/'emotion_video/selected'})
        playlist=[VideoAsset(r['video_id'],r['video_path'],float(r['video_duration_sec']),'emotion','valid') for r in selected]
        cfg.update(_material_roots_explicit=True,session_manifest_hash=hashlib.sha256(manifest.read_bytes()).hexdigest())
        cfg['storage']['records_dir']='data/sourcedata/demo/v3_nas_smoke'
        cfg['protocol'].update(video_library_dir=str(nas/'videos'),emotion_library_dir=str(nas/'emotion_video'))
    if cfg['protocol'].get('emotion_only'):
        assert len(playlist) == 3 and all(r['trial_type'] == 'emotion' for r in library.rows.values())
    win = base.visual.Window(size=(1100, 800), fullscr=False, units='height', color='black')

    class Keyboard:
        def __init__(self, interrupt=False):
            self.runner = None; self.interrupt = interrupt; self.fired = False; self.speed = 0
        def clearEvents(self):
            pass
        def getKeys(self, keys, **kwargs):
            if keys == ['space']:
                return ['space']
            if keys == ['escape', 'f', 'j']:
                return ['f']
            if keys == ['escape', '1', '2', '3']:
                self.speed += 1
                return [str((self.speed - 1) % 3 + 1)]
            if 'a' in keys:
                return ['1']
            if '5' in keys:
                if 'FATIGUE_ONSET' in self.runner._event_times:
                    return ['5']
                if 'AROUSAL_RATING_ONSET' in self.runner._event_times:
                    if self.interrupt and not self.fired:
                        self.fired = True
                        return ['escape']
                    return ['4']
                return ['7']
            return []

    def create(stage, interrupt=False):
        config = copy.deepcopy(cfg); config['emotion_stage'] = stage
        keyboard = Keyboard(interrupt)
        runner = EmotionV3Runner(win=win, keyboard=keyboard, config=config,
            protocol=base.VideoExperimentConfig.from_config(config), project_dir=base.PROJECT_ROOT,
            playlist=playlist, library=library)
        keyboard.runner = runner
        return runner, keyboard

    try:
        action_partial = None
        interrupted_events = []
        if cfg['action_recording_enabled']:
            interrupted, _ = create('eeg')
            original_check = interrupted._check_abort
            def abort_acquisition():
                original_check()
                recorder = getattr(interrupted, '_action_recorder', None)
                onset = recorder.events.get('video_on', {}).get('monotonic_sec') if recorder else None
                if onset is not None and time.perf_counter() - onset >= 2:
                    raise base.ExperimentAbort()
            interrupted._check_abort = abort_acquisition
            interrupted.run()
            assert not interrupted.state.session_completed
            assert not getattr(interrupted, '_action_recording_error', None)
            action_partial = interrupted.progress_dir / 'experiment_action.mp4'
            partial_hash = hashlib.sha256(action_partial.read_bytes()).hexdigest()
            interrupted_events = json.loads((interrupted.manager.session_dir /
                interrupted.manager.recorder.events_filename).read_text(encoding='utf-8'))
        runner, _ = create('eeg')
        runner.run()
        assert runner.termination_reason == 'completed', runner._run_traceback
        assert runner.state.session_completed
        attempts = [a for a in runner.state.video_attempts if 'emotion_rating' in a]
        assert len(attempts) == 3 and all(eeg_saved(a) for a in attempts)
        assert all(not a['emotion_rating']['completed'] for a in attempts)
        passed = []
        events = json.loads((runner.manager.session_dir / runner.manager.recorder.events_filename).read_text(encoding='utf-8'))
        if cfg['facial_recording_enabled']:
            facial_rows = [json.loads(line) for line in
                (runner.progress_dir / 'facial_recording_log.jsonl').read_text(encoding='utf-8').splitlines()]
            passed = [row for row in facial_rows if row['status'] == 'passed']
            assert len(passed) == 3
            alignments = [row['alignment'] for row in facial_rows if row['status'] == 'onset_frame_alignment']
            assert len(alignments) == 3
            assert all(row['status'] == 'software_observation_only' for row in alignments)
            assert all(row['before']['relative_video_onset_sec'] <= 0 <=
                       row['after']['relative_video_onset_sec'] for row in alignments)
            assert all(row['decoded_duration_sec'] >= row['material_duration_sec'] for row in passed)
            assert all(row['events']['video_off']['sample_index'] > row['events']['video_on']['sample_index'] for row in passed)
            events = json.loads((runner.manager.session_dir / runner.manager.recorder.events_filename).read_text(encoding='utf-8'))
            facial_events = interrupted_events + events
            camera_events = [e for e in facial_events if e['name'] == 'CAMERA_RECORDING_ONSET']
            assert len(camera_events) == 3
            assert all(e['payload']['marker_code'] == 164 for e in camera_events)
            assert all('stimulus_flip_monotonic_sec' in e['payload'] for e in events
                       if e['name'] == 'EMOTION_VIDEO_ONSET')
            emotion_onsets = [e for e in facial_events if e['name'] == 'EMOTION_VIDEO_ONSET']
            assert len(emotion_onsets) == 3
            category_codes = {'positive': 171, 'negative': 172, 'neutral': 173}
            assert all(e['payload']['marker_code'] == category_codes[e['payload']['three_class_label']]
                       for e in emotion_onsets)
            assert all(e['payload']['marker_code'] == 175 for e in events
                       if e['name'] == 'EMOTION_VIDEO_OFFSET')
            assert not any(e['payload'].get('marker_code') in (150, 151) for e in events)
            assert {e['payload']['facial_file'] for e in camera_events} == {row['file'] for row in passed}
        else:
            assert not (runner.progress_dir / 'facial_recording_log.jsonl').exists()
            assert not any(e['name'] == 'CAMERA_RECORDING_ONSET' for e in events)
        if cfg['action_recording_enabled']:
            assert not getattr(runner, '_action_recording_error', None)
            action_rows = [json.loads(line) for line in (runner.progress_dir / 'action_recording_log.jsonl').read_text(encoding='utf-8').splitlines()]
            action_passed = [row for row in action_rows if row['status'] == 'passed']
            assert len(action_passed) == 2
            assert action_passed[0]['experiment_completed'] is False
            assert action_partial.name != action_passed[1]['file']
            assert hashlib.sha256(action_partial.read_bytes()).hexdigest() == partial_hash
            row = action_passed[1]
            assert row['device'] == 'Action_CAMERA' and row['experiment_completed']
            assert row['software_preroll_sec'] >= .5 and row['software_postroll_sec'] >= .5
            assert row['decoded_duration_sec'] > row['material_duration_sec']
            names = [e['name'] for e in events]
            assert names.count('ACTION_RECORDING_ONSET') == 1
            assert names.index('ACTION_RECORDING_ONSET') < names.index('session_start')
            assert next(e for e in events if e['name'] == 'ACTION_RECORDING_ONSET')['payload']['marker_code'] == 165
            action_before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in runner.progress_dir.glob('*action*')}
        assert not any('RATING' in e['name'] for e in events)
        if cfg['protocol'].get('emotion_only'):
            assert not any(e['name'].startswith(('LIKING', 'ALARM', 'FATIGUE')) for e in events)
            assert len(runner.state.video_ids) == 3 and runner.state.completed_attention_count == 0
        metadata = json.loads((runner.manager.session_dir / runner.manager.recorder.metadata_filename).read_text(encoding='utf-8'))
        assert metadata['rating_stage_present'] is False
        queue = list(runner.state.queue_video_ids)
        durations = (runner.state.completed_net_video_duration_sec, runner.state.continuous_net_video_duration_sec)
        eeg_files = [p for p in runner.progress_dir.rglob('*') if p.is_file() and
                     (p.suffix.lower() in {'.edf', '.npy'} or p.name.startswith(('events', 'metadata', 'eeg_health')))]
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in eeg_files}
        with patch.object(base, 'build_acquirer', side_effect=AssertionError('Behavior attempted EEG acquisition')):
            behavior, keyboard = create('ratings', True)
            behavior.run()
            assert keyboard.fired
            assert not any(a.get('emotion_rating', {}).get('completed') for a in behavior.state.video_attempts)
            behavior, _ = create('ratings')
            behavior.run()
            rated = [a['emotion_rating'] for a in behavior.state.video_attempts if 'emotion_rating' in a]
            assert all(r['completed'] and r['valence_rating'] == 7 and r['arousal_rating'] == 4 for r in rated)
            assert {r['behavior_playback_speed'] for r in rated} == {1., 1.5, 2.}
            assert all(r['valence_onset_sample_index'] is None and r['arousal_response_sample_index'] is None for r in rated)
            assert behavior.state.queue_video_ids == queue
            assert (behavior.state.completed_net_video_duration_sec, behavior.state.continuous_net_video_duration_sec) == durations
            assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in eeg_files}
            assert set(eeg_files) == {p for p in behavior.progress_dir.rglob('*') if p.is_file() and
                (p.suffix.lower() in {'.edf', '.npy'} or p.name.startswith(('events', 'metadata', 'eeg_health')))}
        if cfg['action_recording_enabled']:
            assert action_before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in runner.progress_dir.glob('*action*')}
        report = dict(status='PASS', real_hardware=False, action_synthetic=cfg['action_recording_enabled'], path=str(behavior.progress_dir),
            ratings=3, speeds=[1, 1.5, 2], eeg_files_unchanged=True, abort_resume=True,
            facial_source='disabled' if not cfg['facial_recording_enabled'] else 'synthetic' if '--facial-synthetic' in sys.argv else 'UGREEN Camera 4K',
            facial_validated=len(passed),nas_input=nas_test)
        (base.PROJECT_ROOT / 'logs' / 'emotion_v3_smoke.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
    finally:
        win.close()
    base.core.quit()


if __name__ == '__main__':
    main()
