import copy
import csv
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from video_eeg.experiment.emotion_v2_runner import EmotionV2Runner, base
from video_eeg.utils import material_exclusions as policy
from video_eeg.utils.emotion_protocol import prepare
from video_eeg.utils.session_protocol import SessionState, load_state, save_state_atomic

ROOT = Path(__file__).resolve().parents[1]


def test_effective_manifest_is_exact_subsequence_no_regrouping():
    path = ROOT / 'video_eeg/config/session_manifest_emotion_v1.csv'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == policy.MANIFEST_SHA256
    with path.open(encoding='utf-8-sig') as handle:
        original = list(csv.DictReader(handle))
    with (path.parent / 'session_manifest_v2_active.csv').open(encoding='utf-8-sig') as handle:
        active = list(csv.DictReader(handle))
    assert active == [r for r in original if r['video_id'] not in policy.REMOVALS]
    assert len(active) == 11084
    assert sum(r['trial_type'] == 'emotion' for r in active) == 3138
    assert policy.excluded_filenames('v1') == set()
    assert policy.excluded_filenames('v2') == {'6076.mp4', '2693.mp4', '6241.mp4'}


def make_runner(tmp_path, monkeypatch, sid=20, subject='S', apply=True):
    monkeypatch.setattr(base, 'visual', SimpleNamespace(TextStim=Mock()))
    monkeypatch.setattr(base, 'event', None)
    cfg = base.load_config(ROOT / 'video_eeg/config/video_emotion_config.yaml')
    cfg.update(_project_dir=str(ROOT), subject_id=subject, session_id=sid, explicit_run_seed=123)
    cfg['storage']['records_dir'] = str(tmp_path)
    library, playlist = prepare(cfg, False)
    if not apply:
        cfg.pop('excluded_video_ids', None)
        cfg.pop('material_exclusion_revision', None)
    return EmotionV2Runner(win=Mock(), keyboard=Mock(), config=cfg,
                           protocol=base.VideoExperimentConfig.from_config(cfg),
                           project_dir=ROOT, playlist=playlist, library=library)


@pytest.mark.parametrize('sid,excluded', [(20, 'original:vid_6076'), (24, 'original:vid_2693'),
                                         (33, 'original:vid_6241'), (3, None)])
def test_new_session_excludes_only_authorized_clip_and_keeps_nine_questions(tmp_path, monkeypatch, sid, excluded):
    r = make_runner(tmp_path, monkeypatch, sid)
    assert r.state.excluded_video_ids == ([excluded] if excluded else [])
    assert len(r.state.attention_schedule) == 9
    assert all(i['video_id'] != excluded for i in r.state.attention_schedule)
    assert excluded not in r.state.queue_video_ids
    assert not r.state.completed_video_ids
    restored = load_state(r.state_path)
    assert restored.queue_video_ids == r.state.queue_video_ids
    assert restored.remaining_video_ids == r.state.remaining_video_ids
    assert excluded not in restored.remaining_video_ids
    assert restored.to_mapping()["state_version"] == (2 if excluded else 1)
    assert not list(r.progress_dir.glob('session_state.before_*'))


def test_old_interrupted_session_preserves_answers_queue_and_backup_rebinds_one_question(tmp_path, monkeypatch):
    old = make_runner(tmp_path, monkeypatch, apply=False)
    state = old.state
    bad = 'original:vid_6076'
    chosen = next(v for v in state.queue_video_ids if v != bad)
    state.commit_completed_video(chosen, 11.)
    state.preserve_aborted_video(bad)
    state.video_attempts = [{'video_id': bad, 'completed': False, 'actual_video_sec': 6.1,
                             'ordinary_behavior': {'liked': 1, 'completed': False}}]
    state.attention_schedule[0]['video_id'] = bad
    # Another previously answered question is never touched.
    state.completed_attention_ids = [state.attention_schedule[1]['attention_id']]
    state.completed_net_video_duration_sec = 32.5
    state.rest_events = [{'duration_sec': 55}]
    save_state_atomic(old.state_path, state)
    before = old.state_path.read_bytes()
    saved = copy.deepcopy(state)
    snapshot = (old.progress_dir / 'question_bank_snapshot.json').read_bytes()
    resumed = make_runner(tmp_path, monkeypatch)
    now = resumed.state
    assert now.video_attempts == saved.video_attempts
    assert now.completed_video_ids == saved.completed_video_ids
    assert now.completed_attention_ids == saved.completed_attention_ids
    assert now.rest_events == saved.rest_events
    assert now.completed_net_video_duration_sec == 32.5
    assert now.manifest_hash == saved.manifest_hash
    assert now.queue_video_ids == [v for v in saved.queue_video_ids if v != bad]
    assert now.current_video_id is None
    assert now.attention_schedule[1:] == saved.attention_schedule[1:]
    assert now.attention_schedule[0]['video_id'] in now.queue_video_ids
    assert now.attention_schedule[0]['replaced_video_id'] == bad
    assert len({i['video_id'] for i in now.attention_schedule}) == 9
    backups = list(old.progress_dir.glob('session_state.before_*'))
    assert len(backups) == 1 and backups[0].read_bytes() == before
    assert (old.progress_dir / 'question_bank_snapshot.json').read_bytes() == snapshot
    again = make_runner(tmp_path, monkeypatch)
    assert again.state.material_exclusion_history == now.material_exclusion_history
    assert again.state.attention_schedule == now.attention_schedule
    assert len(list(old.progress_dir.glob('session_state.before_*'))) == 1


def test_completed_session_retains_historical_contract(tmp_path, monkeypatch):
    old = make_runner(tmp_path, monkeypatch, apply=False)
    old.state.completed_video_ids = old.state.video_ids[:]
    old.state.queue_video_ids = []
    old.state.session_completed = True
    old.state.completed_attention_ids = [i['attention_id'] for i in old.state.attention_schedule]
    save_state_atomic(old.state_path, old.state)
    resumed = make_runner(tmp_path, monkeypatch)
    assert resumed.state.completed_video_ids == old.state.completed_video_ids
    assert resumed.state.attention_schedule == old.state.attention_schedule
    assert resumed.state.session_completed and not resumed.state.queue_video_ids
    assert not resumed.state.excluded_video_ids
    assert not resumed.state.material_exclusion_history


def test_no_safe_question_replacement_stops_without_writing(tmp_path):
    state = SessionState('S', 20, 'test', 'hash', ['bad'], ['bad'])
    state.attention_schedule = [dict(video_id='bad', attention_id=1, planned_trigger_net_sec=600)]
    path = tmp_path / 'session_state.json'
    save_state_atomic(path, state)
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='未修改进度'):
        policy.apply_to_state(state, ['bad'], {}, {}, path)
    assert path.read_bytes() == before and not state.excluded_video_ids
    assert list(tmp_path.iterdir()) == [path]


def test_unknown_manifest_cannot_claim_same_exclusion():
    row = dict(video_id='original:vid_6076', session_id=20, video_path='original/6076.mp4', trial_type='ordinary')
    with pytest.raises(RuntimeError, match='另一份固定分组'):
        policy.exclusion_ids({'protocol': {'kind': 'emotion-v2'}}, [row], 'wrong')
    assert policy.exclusion_ids({'protocol': {'kind': 'emotion-v1'}}, [row], 'wrong') == []


def test_missing_excluded_file_is_not_opened_by_formal_entry(monkeypatch):
    from video_eeg.experiment import emotion_runner, emotion_v2_runner
    from video_eeg.utils import emotion_protocol
    from video_eeg.utils.video_library import VideoAsset
    bad = VideoAsset('original:vid_6076', 'original/6076.mp4', 30.4)
    good = VideoAsset('good', 'original/good.mp4', 5.)
    seen = []
    def prepared(cfg, demo):
        cfg['excluded_video_ids'] = [bad.asset_id]
        def available(asset):
            assert asset != bad
            seen.append(asset.asset_id)
            return True
        return SimpleNamespace(is_available=available, resolve=lambda a: Path(a.rel_path)), [bad, good]
    runner = Mock()
    monkeypatch.setattr(emotion_protocol, 'prepare', prepared)
    monkeypatch.setattr(emotion_v2_runner, 'EmotionV2Runner', runner)
    monkeypatch.setattr(base, '_load_psychopy', lambda: None)
    monkeypatch.setattr(base, 'visual', SimpleNamespace(Window=Mock()))
    monkeypatch.setattr(base, 'Keyboard', Mock)
    monkeypatch.setattr(base, 'core', Mock())
    assert emotion_runner.main(['--no-dialog', '--session-id', '20', '--windowed']) == 0
    assert seen == ['good'] and runner.return_value.run.called


def test_revised_schema_cannot_lose_its_exclusion_audit():
    state = SessionState('S', 20, 'test', 'hash', ['v'], ['v'])
    payload = state.to_mapping()
    payload['state_version'] = 2
    with pytest.raises(ValueError, match='missing its material exclusion record'):
        SessionState.from_mapping(payload)
