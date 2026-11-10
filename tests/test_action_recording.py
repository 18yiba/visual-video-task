import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from video_eeg.experiment.action_recording import ActionRecorder
from video_eeg.experiment.facial_recording import FacialRecordingError, reserve_path
from video_eeg.experiment.emotion_v3_runner import EmotionV3Runner, EmotionV2Runner


def test_action_name_and_independent_reservation(tmp_path):
    recorder = ActionRecorder(tmp_path)
    assert recorder.device == 'Action_CAMERA'
    recorder._command = Mock(return_value=SimpleNamespace(stderr='"facialcamera" (video)'))
    with pytest.raises(FacialRecordingError, match='Action_CAMERA'):
        recorder.preflight()
    recorder._command.assert_called_once()
    first, number = reserve_path(tmp_path, 'experiment', suffix='action', log_filename=recorder.log_filename)
    first.write_bytes(b'partial preserved')
    second, next_number = reserve_path(tmp_path, 'experiment', suffix='action', log_filename=recorder.log_filename)
    assert (first.name, second.name, number, next_number) == ('experiment_action.mp4', 'experiment_action_02.mp4', 1, 2)
    assert first.read_bytes() == b'partial preserved'


def test_action_marker_precedes_session_start_with_live_eeg(tmp_path):
    from video_eeg.experiment.video_protocol import EegSessionManager
    from video_eeg.devices.dummy_acquirer import DummyAcquirer
    from video_eeg.utils.markers import NoOpMarkerBackend, PROTOCOL_EVENT_CODES
    manager = EegSessionManager(DummyAcquirer(sfreq=1000, n_channels=2), NoOpMarkerBackend(),
        sfreq=1000, records_dir=tmp_path, subject_id='TEST', session_id=1)
    def before():
        assert manager.running
        manager.emit('ACTION_RECORDING_ONSET', action_file='experiment_action.mp4')
    try:
        manager.start(output_dir=tmp_path, before_session_start=before)
    finally:
        manager.stop_and_export()
    events = json.loads((tmp_path / 'events.json').read_text(encoding='utf-8'))
    assert [e['name'] for e in events] == ['ACTION_RECORDING_ONSET', 'session_start', 'session_end']
    assert events[0]['payload']['marker_code'] == 165
    assert PROTOCOL_EVENT_CODES['CAMERA_RECORDING_ONSET'] == 164


def test_start_callback_and_disabled_scope(monkeypatch, tmp_path):
    runner = object.__new__(EmotionV3Runner)
    runner.config = dict(device_type='neuracle', action_recording_enabled=False)
    runner.stage = 'eeg'
    runner.progress_dir = tmp_path
    runner.manager = Mock()
    recorder = Mock(device='Action_CAMERA')
    factory = Mock(return_value=recorder)
    monkeypatch.setattr('video_eeg.experiment.action_recording.ActionRecorder', factory)
    runner._before_session_start()
    factory.assert_not_called()
    runner.config['action_recording_enabled'] = True
    recorder.start.side_effect = lambda on_started: on_started(action_file='experiment_action.mp4')
    runner._before_session_start()
    runner.manager.emit.assert_called_once_with('ACTION_RECORDING_ONSET',
        action_file='experiment_action.mp4', device='Action_CAMERA', time_basis='software_first_frame_observation')
    recorder.boundary.assert_called_once()
    runner.stage = 'ratings'
    with pytest.raises(ValueError):
        runner._before_session_start()
    runner.stage = 'eeg'
    runner.config['device_type'] = 'brainco'
    with pytest.raises(ValueError):
        runner._before_session_start()


@pytest.mark.parametrize('eeg_fails,camera_fails', [(False, False), (False, True), (True, False)])
def test_export_and_video_cleanup_are_independent(monkeypatch, tmp_path, eeg_fails, camera_fails):
    runner = object.__new__(EmotionV3Runner)
    runner.completed = False
    runner.termination_reason = 'esc_emergency'
    runner._write_emotion_list = Mock()
    runner._show_text = Mock()
    recorder = runner._action_recorder = Mock(closed=False)
    recorder.events = {'video_on': {'monotonic_sec': time.perf_counter() - 2}}
    order = []
    def export(self):
        order.append('eeg')
        if eeg_fails:
            raise RuntimeError('EEG save failed')
        return tmp_path
    def finish(**kwargs):
        order.append('video')
        assert kwargs['complete'] and kwargs['material_duration'] >= 2
        if camera_fails:
            raise FacialRecordingError('camera failed')
    recorder.finish.side_effect = finish
    monkeypatch.setattr(EmotionV2Runner, '_stop_and_export', export)
    if eeg_fails:
        with pytest.raises(RuntimeError, match='EEG save failed'):
            runner._stop_and_export()
    else:
        assert runner._stop_and_export() == tmp_path
    assert order == ['eeg', 'video']
    assert recorder.experiment_completed is False
    assert runner._show_text.call_count == int(camera_fails)


def test_camera_fault_checked_outside_video():
    runner = object.__new__(EmotionV3Runner)
    runner.manager = Mock()
    runner._action_recorder = Mock(closed=False)
    runner._action_recorder.check.side_effect = FacialRecordingError('no frames')
    with pytest.raises(FacialRecordingError, match='no frames'):
        runner._check_abort()
    # Playback and question/rest loops use the manager guard rather than polling
    # Escape through _check_abort; both paths must check continuous capture.
    with pytest.raises(FacialRecordingError, match='no frames'):
        runner._require_manager()


def test_action_requires_strictly_longer_video(tmp_path):
    recorder = ActionRecorder(tmp_path)
    recorder.frames = [(i, i / 10, i / 10) for i in range(31)]
    with pytest.raises(FacialRecordingError, match='长于'):
        recorder._validate_coverage(.5, 2.5, 2, 2)
    recorder._validate_coverage(.5, 2.5, 2, 3)


def test_cli_action_default_and_device_guard():
    from video_eeg.experiment.video_runner import parse_args, apply_cli_overrides
    config = dict(device_type='neuracle', protocol={'separate_emotion_ratings': True})
    apply_cli_overrides(config, parse_args([]))
    assert config['action_recording_enabled'] is False
    apply_cli_overrides(config, parse_args(['--action-recording']))
    assert config['action_recording_enabled'] is True
    apply_cli_overrides(config, parse_args(['--no-action-recording']))
    assert config['action_recording_enabled'] is False
    with pytest.raises(ValueError, match='博睿康'):
        apply_cli_overrides(config, parse_args(['--action-recording', '--device-type', 'brainco']))


def test_camera_startup_failure_is_not_an_eeg_fault(tmp_path):
    from video_eeg.experiment.video_protocol import EegSessionManager
    from video_eeg.devices.dummy_acquirer import DummyAcquirer
    from video_eeg.utils.markers import NoOpMarkerBackend
    backend = NoOpMarkerBackend()
    backend.fail_closed_on_marker_error = True
    manager = EegSessionManager(DummyAcquirer(sfreq=1000, n_channels=2), backend,
        sfreq=1000, records_dir=tmp_path, subject_id='TEST', session_id=1)
    try:
        with pytest.raises(FacialRecordingError, match='missing'):
            manager.start(output_dir=tmp_path,
                before_session_start=Mock(side_effect=FacialRecordingError('missing camera')))
        assert manager.running and manager.background_error is None
    finally:
        manager.stop_and_export(metadata={'completed': False, 'termination_reason': 'python_exception'})
    assert (tmp_path / 'metadata.json').exists()
    assert json.loads((tmp_path / 'metadata.json').read_text())['termination_reason'] == 'python_exception'
