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
    base._load_psychopy()
    cfg = base.load_config(base.CONFIG_DIR / 'video_emotion_v3_demo_config.yaml')
    cfg.update(_project_dir=str(base.PROJECT_ROOT), subject_id='AUTO_V3_' + str(time.time_ns()), explicit_run_seed=20260912, _integrated_startup=True)
    cfg['protocol'].update(fixation_sec=.1, post_video_rest_seconds=.1, random_seed=20260912)
    cfg['storage']['records_dir'] = 'data/sourcedata/demo/v3_smoke'
    if '--emotion-only' in sys.argv:
        configure_emotion_only(cfg)
    library, playlist = prepare(cfg, True)
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
        runner, _ = create('eeg')
        runner.run()
        assert runner.termination_reason == 'completed', runner._run_traceback
        assert runner.state.session_completed
        attempts = [a for a in runner.state.video_attempts if 'emotion_rating' in a]
        assert len(attempts) == 3 and all(eeg_saved(a) for a in attempts)
        assert all(not a['emotion_rating']['completed'] for a in attempts)
        events = json.loads((runner.manager.session_dir / runner.manager.recorder.events_filename).read_text(encoding='utf-8'))
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
        report = dict(status='PASS', real_hardware=False, path=str(behavior.progress_dir),
            ratings=3, speeds=[1, 1.5, 2], eeg_files_unchanged=True, abort_resume=True)
        (base.PROJECT_ROOT / 'logs' / 'emotion_v3_smoke.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
    finally:
        win.close()
    base.core.quit()


if __name__ == '__main__':
    main()
