import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from video_eeg.experiment.facial_recording import (
    FacialRecorder, FacialRecordingError, reserve_path, validate_coverage,
)


def test_reservation_preserves_orphans_and_log_number(tmp_path):
    first, n = reserve_path(tmp_path, 'E001')
    first.write_bytes(b'original')
    second, n = reserve_path(tmp_path, 'E001')
    assert second.name == 'E001_facial_02.mp4'
    (tmp_path / 'facial_recording_log.jsonl').write_text(
        json.dumps(dict(code='E001', number=99)) + '\npartial', encoding='utf-8')
    third, n = reserve_path(tmp_path, 'E001')
    assert third.name == 'E001_facial_100.mp4'
    assert first.read_bytes() == b'original'
    assert third.parent == tmp_path


@pytest.mark.parametrize('code', ['../v', 'emotion:v', '', 'a/b'])
def test_unsafe_code_rejected(tmp_path, code):
    with pytest.raises(FacialRecordingError):
        reserve_path(tmp_path, code)


def frames():
    return [(i, i / 30, i / 30) for i in range(91)]


def test_cover_material_and_actual_duration():
    validate_coverage(frames(), .5, 2.5, 2, 3)


@pytest.mark.parametrize('onset,offset,material,decoded', [
    (.4, 2.5, 2, 3), (.5, 2.6, 2, 3), (.5, 2.5, 4, 3),
    (.5, 2.5, 1, 1.99), (.5, 2.5, float('nan'), 3),
])
def test_short_or_uncovered_rejected(onset, offset, material, decoded):
    with pytest.raises(FacialRecordingError):
        validate_coverage(frames(), onset, offset, material, decoded)


def test_duplicate_pts_rejected():
    rows = frames()
    rows[2] = (2, 2/30, 1/30)
    with pytest.raises(FacialRecordingError):
        validate_coverage(rows, .5, 2.5, 2, 3)


def test_preflight_rejects_missing_duplicate_and_unavailable(tmp_path):
    r = FacialRecorder(tmp_path, 'v', 1)
    for devices in ['', '"UGREEN Camera 4K" (video)\n' * 2]:
        r._command = Mock(return_value=SimpleNamespace(stderr=devices))
        with pytest.raises(FacialRecordingError):
            r.preflight()
    r._command = Mock(side_effect=[
        SimpleNamespace(stderr='"UGREEN Camera 4K" (none)'),
        SimpleNamespace(returncode=1, stderr='device busy')])
    with pytest.raises(FacialRecordingError, match='device busy'):
        r.preflight()
    assert not list(tmp_path.glob('*.mp4'))


def test_interruption_timestamps_and_clock_mapping(tmp_path):
    r = FacialRecorder(tmp_path, 'v', 1)
    r.path, r.number = reserve_path(tmp_path, 'v')
    r.frames = frames()
    r.boundary('video_on', dict(monotonic_sec=.5, sample_index=100))
    r.finish()
    lines = r.path.with_suffix('.timestamps.csv').read_text().splitlines()
    assert len(lines) == 92
    assert lines[1].endswith(',-0.5')
    log = json.loads((tmp_path/'facial_recording_log.jsonl').read_text(encoding='utf-8'))
    assert log['status'] == 'interrupted'
    assert log['events']['video_on']['sample_index'] == 100
    assert set(log['clock_mapping']) == {'monotonic_sec', 'timestamp_unix_sec'}
    r.finish()  # idempotent cleanup


def test_dead_camera_detected(tmp_path):
    r = FacialRecorder(tmp_path, 'v', 1)
    r.process = Mock()
    r.process.poll.return_value = 1
    with pytest.raises(FacialRecordingError):
        r.check()
    r.process.poll.return_value = None
    with pytest.raises(FacialRecordingError):
        r.check()


@pytest.mark.parametrize('stage,trial_type,expected', [('eeg', 'emotion', 1),
    ('eeg', 'ordinary', 0), ('ratings', 'emotion', 0)])
def test_v3_capture_scope_and_cleanup(monkeypatch, tmp_path, stage, trial_type, expected):
    from video_eeg.experiment.emotion_v3_runner import EmotionV3Runner, EmotionV2Runner
    r = object.__new__(EmotionV3Runner)
    r.stage = stage
    r.library = SimpleNamespace(rows={'v': {'trial_type': trial_type}})
    r.progress_dir = tmp_path
    r._attempt_counter_by_video = {}
    original_emit = Mock()
    r.manager = SimpleNamespace(emit=original_emit)
    recorder = Mock()
    factory = Mock(return_value=recorder)
    monkeypatch.setattr('video_eeg.experiment.facial_recording.FacialRecorder', factory)
    def trial(self, idx, asset):
        self._event_times = dict(video_on=dict(monotonic_sec=1., sample_index=4))
        self.manager.emit('video_on')
        raise RuntimeError('playback failed')
    monkeypatch.setattr(EmotionV2Runner, '_run_trial', trial)
    with pytest.raises(RuntimeError, match='playback failed'):
        r._run_trial(1, SimpleNamespace(asset_id='v', rel_path='emotion/E01.mp4'))
    assert factory.call_count == expected
    assert recorder.finish.call_count == expected
    assert recorder.boundary.call_count == expected
    assert r.manager.emit is original_emit
    assert r._facial_recorder is None


def test_failed_length_keeps_video_and_timestamps(tmp_path):
    r = FacialRecorder(tmp_path, 'short', 1)
    r.path, r.number = reserve_path(tmp_path, 'short')
    r.path.write_bytes(b'preserved recording')
    r.frames = frames()
    r.events = dict(video_on=dict(monotonic_sec=.5), video_off=dict(monotonic_sec=2.5))
    r._command = Mock(return_value=SimpleNamespace(returncode=0,
        stderr='\n'.join(f'[showinfo] n: {i} pts_time: {i/30}' for i in range(91))))
    with pytest.raises(FacialRecordingError, match='时长'):
        r.finish(complete=True, material_duration=4)
    assert r.path.read_bytes() == b'preserved recording'
    assert r.path.with_suffix('.timestamps.csv').is_file()
    row = json.loads((tmp_path/'facial_recording_log.jsonl').read_text(encoding='utf-8'))
    assert row['status'] == 'failed'
