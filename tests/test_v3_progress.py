import json

import pytest

from video_eeg.utils.v3_progress import inspect_progress, valid_subject
from video_eeg.utils.session_protocol import SessionState, save_state_atomic


@pytest.mark.parametrize('layout', ['src/video_eeg/config', 'video_eeg/config'])
def test_formal_progress_resolves_saved_manifest_path(tmp_path, layout):
    manifest = tmp_path / layout / 'session_manifest_emotion_v1.csv'
    manifest.parent.mkdir(parents=True)
    manifest.write_text('session_id,video_id,trial_type\n1,original:one,ordinary\n', encoding='utf-8')
    path = tmp_path / 'data/sourcedata/v3_neuracle/13467638/session_01/session_state.json'
    state = SessionState(subject_id='13467638', session_id=1, manifest_version='test', manifest_hash='test',
        video_ids=['original:one'], completed_video_ids=['original:one'], queue_video_ids=[],
        session_completed=True, attention_task_type='emotion_v3_separate_eeg_ratings_7')
    save_state_atomic(path, state)
    before = path.read_bytes()
    cfg = dict(storage=dict(records_dir='data/sourcedata/v3_neuracle'),
               protocol=dict(session_manifest='video_eeg/config/session_manifest_emotion_v1.csv', num_sessions=1))
    result = inspect_progress(cfg, '13467638', tmp_path)
    assert result[0]['videos_completed'] == 1 and result[0]['eeg_complete']
    assert path.read_bytes() == before


@pytest.mark.parametrize('subject', ['', '../S001', 'a/b', 'NUL', 'COM1', 'a:1'])
def test_subject_cannot_escape_record_root(subject):
    with pytest.raises(ValueError):
        valid_subject(subject)


def test_new_subject_progress_does_not_create_records(tmp_path):
    cfg = dict(demo_mode=True, storage=dict(records_dir='records'))
    rows = inspect_progress(cfg, 'NEW', tmp_path)
    assert len(rows) == 1
    assert rows[0]['videos_total'] == 4 and rows[0]['emotion_total'] == 3
    assert rows[0]['videos_completed'] == rows[0]['ratings_completed'] == 0
    assert not (tmp_path / 'records').exists()


def test_progress_deduplicates_attempts_requires_eeg_and_preserves_bytes(tmp_path):
    root = tmp_path / 'records/S001/run_20260912/session_01'
    eeg = root / 'record'; eeg.mkdir(parents=True)
    (eeg / 'continuous_eeg.npy').write_bytes(b'EEG')
    (eeg / 'metadata.json').write_text(json.dumps(dict(eeg_part=1, local_eeg_recorded=True,
        sample_count=100, eeg_file='continuous_eeg.npy')))
    ids = [f'practice:{i}' for i in range(4)]
    state = SessionState(subject_id='S001', session_id=1, manifest_version='test', manifest_hash='test',
        attention_task_type='emotion_v3_separate_eeg_ratings_7', video_ids=ids,
        completed_video_ids=ids, queue_video_ids=[], session_completed=True)
    a = dict(video_id='practice:1', video_completed_naturally=True, emotion_rating=dict(
        video_onset_sample_index=0, video_offset_sample_index=80,
        eeg_part=1, eeg_recording_dir=str(eeg), completed=True))
    state.video_attempts = [a, a, dict(video_id='practice:2', video_completed_naturally=False, emotion_rating=a['emotion_rating'])]
    save_state_atomic(root / 'session_state.json', state)
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    rows = inspect_progress(dict(demo_mode=True, storage=dict(records_dir='records')), 'S001', tmp_path)
    r = rows[0]
    assert r['eeg_complete'] and r['videos_completed'] == 4
    assert r['emotion_eeg_saved'] == r['ratings_completed'] == 1
    assert not r['ratings_complete']
    assert before == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    (eeg / 'continuous_eeg.npy').unlink()
    assert inspect_progress(dict(demo_mode=True, storage=dict(records_dir='records')), 'S001', tmp_path)[0]['ratings_completed'] == 0


def test_mismatched_protocol_stops_progress(tmp_path):
    path = tmp_path / 'records/S001/run_20260912/session_01/session_state.json'
    state = SessionState(subject_id='S001', session_id=1, manifest_version='test', manifest_hash='test',
        video_ids=[f'practice:{i}' for i in range(4)], queue_video_ids=[f'practice:{i}' for i in range(4)],
        attention_task_type='emotion_v2_mcq_fatigue_liking_7')
    save_state_atomic(path, state)
    with pytest.raises(ValueError, match='协议'):
        inspect_progress(dict(demo_mode=True, storage=dict(records_dir='records')), 'S001', tmp_path)


@pytest.mark.parametrize('keep_original', [False, True])
def test_moved_session_uses_local_eeg_for_progress_and_rating(tmp_path, keep_original):
    import shutil
    from video_eeg.experiment.emotion_v3_runner import eeg_saved, eeg_status
    original = tmp_path / 'old/records/S001/run_20260912/session_01'
    recording = original / '20261022_120000'
    recording.mkdir(parents=True)
    (recording / 'continuous_eeg.npy').write_bytes(b'EEG')
    metadata = dict(eeg_part=1, local_eeg_recorded=True, sample_count=100,
                    eeg_file='continuous_eeg.npy', device_type='neuracle')
    (recording / 'metadata.json').write_text(json.dumps(metadata))
    ids = [f'practice:{i}' for i in range(4)]
    attempt = dict(video_id='practice:1', video_completed_naturally=True, emotion_rating=dict(
        video_onset_sample_index=0, video_offset_sample_index=80,
        eeg_part=1, eeg_recording_dir=str(recording), completed=False))
    state = SessionState(subject_id='S001', session_id=1, manifest_version='test', manifest_hash='test',
        attention_task_type='emotion_v3_separate_eeg_ratings_7', video_ids=ids,
        completed_video_ids=ids, queue_video_ids=[], session_completed=True)
    state.video_attempts = [attempt]
    save_state_atomic(original / 'session_state.json', state)
    project = tmp_path / 'new'
    current = project / 'records/S001/run_20260912/session_01'
    shutil.copytree(original, current)
    if not keep_original:
        (recording / 'continuous_eeg.npy').unlink()
    before = {str(p): p.read_bytes() for p in current.rglob('*') if p.is_file()}
    row = inspect_progress(dict(demo_mode=True, storage=dict(records_dir='records')), 'S001', project)[0]
    assert row['emotion_viewed'] == 3
    assert row['emotion_eeg_saved'] == 1 and row['ratings_completed'] == 0
    assert eeg_saved(attempt, current)
    assert before == {str(p): p.read_bytes() for p in current.rglob('*') if p.is_file()}
    (current / recording.name / 'continuous_eeg.npy').unlink()
    assert eeg_status(attempt, current) == 'missing_eeg_file'
    assert not eeg_saved(attempt, current)  # Never borrow a surviving old copy.


def test_migration_does_not_cross_subject_or_accept_trigger_fault(tmp_path):
    from video_eeg.experiment.emotion_v3_runner import eeg_status
    current = tmp_path / 'v3_neuracle/S001/session_01'
    recording = current / '20261022_120000'
    recording.mkdir(parents=True)
    (recording / 'eeg.edf').write_bytes(b'EEG')
    meta = dict(eeg_part=1, local_eeg_recorded=True, sample_count=100, eeg_file='eeg.edf',
                device_type='neuracle', neuracle_trigger=dict(error='failed'))
    (recording / 'metadata.json').write_text(json.dumps(meta))
    attempt = dict(video_completed_naturally=True, emotion_rating=dict(
        video_onset_sample_index=0, video_offset_sample_index=80, eeg_part=1,
        eeg_recording_dir='Z:/old/v3_neuracle/S001/session_01/20261022_120000'))
    assert eeg_status(attempt, current) == 'acquisition_error'
    attempt['emotion_rating']['eeg_recording_dir'] = 'Z:/old/v3_neuracle/OTHER/session_01/20261022_120000'
    assert eeg_status(attempt, current) == 'missing_directory'


def test_full_session_246_includes_69_rating_eligible_emotion_videos(tmp_path):
    import csv
    import shutil
    from pathlib import Path
    manifest = Path(__file__).resolve().parents[1] / 'src/video_eeg/config/session_manifest_v2_active.csv'
    rows = [r for r in csv.DictReader(manifest.open(encoding='utf-8-sig')) if int(r['session_id']) == 1]
    ids = [r['video_id'] for r in rows]
    emotion = [r['video_id'] for r in rows if r['trial_type'] == 'emotion']
    assert len(ids) == 246 and len(emotion) == 69
    local_manifest = tmp_path / 'src/video_eeg/config/manifest.csv'
    local_manifest.parent.mkdir(parents=True)
    shutil.copyfile(manifest, local_manifest)
    session = tmp_path / 'data/sourcedata/v3_neuracle/13467638/session_01'
    recording = session / '20261022_120000'
    recording.mkdir(parents=True)
    (recording / 'eeg.npy').write_bytes(b'synthetic EEG')
    (recording / 'metadata.json').write_text(json.dumps(dict(eeg_part=1, local_eeg_recorded=True,
        sample_count=100, eeg_file='eeg.npy', device_type='neuracle')))
    state = SessionState(subject_id='13467638', session_id=1, manifest_version='test', manifest_hash='test',
        attention_task_type='emotion_v3_separate_eeg_ratings_7', video_ids=ids,
        completed_video_ids=ids, queue_video_ids=[], session_completed=True)
    state.video_attempts = [dict(video_id=v, video_completed_naturally=True, emotion_rating=dict(
        video_onset_sample_index=0, video_offset_sample_index=80, eeg_part=1, completed=False,
        eeg_recording_dir='Z:/old/data/sourcedata/v3_neuracle/13467638/session_01/20261022_120000')) for v in emotion]
    save_state_atomic(session / 'session_state.json', state)
    cfg = dict(storage=dict(records_dir='data/sourcedata/v3_neuracle'),
               protocol=dict(session_manifest='video_eeg/config/manifest.csv', num_sessions=1))
    row = inspect_progress(cfg, '13467638', tmp_path)[0]
    assert row['videos_completed'] == 246
    assert row['emotion_viewed'] == row['emotion_eeg_saved'] == 69
    assert row['ratings_completed'] == 0 and row['eeg_problems'] == {}
