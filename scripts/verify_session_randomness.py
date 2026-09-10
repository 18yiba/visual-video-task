"""Exercise real catalog sampling and checkpoint round trips without EEG hardware."""
import json
from pathlib import Path
import secrets
import sys
from tempfile import TemporaryDirectory

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from video_eeg.experiment.video_runner import load_config
from video_eeg.utils.video_library import load_video_library, build_fast_valid_playlist
from video_eeg.utils.session_protocol import SessionManifest, SessionState, save_state_atomic, load_state


def main():
    config = load_config(PROJECT / 'video_eeg/config/video_demo_config.yaml')
    config['_project_dir'] = str(PROJECT)
    library = load_video_library(config)
    manifest = SessionManifest.load(PROJECT / 'video_eeg/config/session_manifest.csv')
    result = {}
    for label in ['Demo A', 'Demo B']:
        seed = secrets.randbits(63)
        assets, _ = build_fast_valid_playlist(library, trials_per_session=10, random_seed=seed+1)
        state = SessionState.new(subject_id='DEMO', session_id=1, manifest=manifest, assets=assets,
                                 random_seed=seed, attention_task_count=3, rest_min_minutes=30,
                                 rest_max_minutes=45, demo_mode=True)
        result[label] = dict(seed=seed, order=state.queue_video_ids)
    states = []
    for subject in ['testA', 'testB']:
        seed = secrets.randbits(63)
        state = SessionState.new(subject_id=subject, session_id=1, manifest=manifest,
                                 assets=manifest.session_assets(1), random_seed=seed,
                                 attention_task_count=18, rest_min_minutes=30, rest_max_minutes=45)
        states.append(state)
        result[subject] = dict(seed=seed, first20=state.queue_video_ids[:20])
    assert set(states[0].video_ids) == set(states[1].video_ids)
    assert states[0].queue_video_ids != states[1].queue_video_ids
    with TemporaryDirectory(dir=PROJECT / 'tests') as tmp:
        path = Path(tmp) / 'state.json'
        save_state_atomic(path, states[0])
        restored = load_state(path)
        assert restored.queue_video_ids == states[0].queue_video_ids
        assert restored.attention_schedule == states[0].attention_schedule
        result['testA_resume'] = dict(order_unchanged=True, first20=restored.queue_video_ids[:20])
    assert result['Demo A']['order'] != result['Demo B']['order']
    (library.root.parent / 'RANDOMNESS_VERIFICATION.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
