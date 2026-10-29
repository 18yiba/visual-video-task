import copy
import importlib.util
import json
from types import SimpleNamespace

import pytest


def module():
    name = 'video_eeg.utils.emotivpro_guard'
    assert importlib.util.find_spec(name), 'Missing external-recorder environment guard'
    return __import__(name, fromlist=['EnvironmentGuard'])


def observation():
    return dict(processes=[dict(name='EmotivPRO.exe', pid=42, started=100.,
                               window=True, responding=True)],
                receivers=[dict(vid=0x1915, pid=0xc00a, serial_number='USB-ONE',
                                location='1-3', port='COM29')])


@pytest.mark.parametrize('change,code', [
    (lambda s: s.update(processes=[]), 'app_missing'),
    (lambda s: s['processes'][0].update(name='EMOTIV Launcher.exe'), 'app_missing'),
    (lambda s: s['processes'][0].update(window=False), 'app_window_missing'),
    (lambda s: s['processes'][0].update(responding=False), 'app_unresponsive'),
    (lambda s: s.update(receivers=[]), 'receiver_missing'),
    (lambda s: s['receivers'].append(dict(s['receivers'][0], serial_number='USB-TWO')), 'receiver_ambiguous'),
])
def test_unready_environment_blocks_start(change, code):
    m = module(); state = observation(); change(state)
    with pytest.raises(m.GuardError) as exc:
        m.EnvironmentGuard(observer=lambda: state)
    assert exc.value.code == code


@pytest.mark.parametrize('change,code', [
    (lambda s: s.update(processes=[]), 'app_missing'),
    (lambda s: s['processes'][0].update(pid=43), 'environment_changed'),
    (lambda s: s['processes'][0].update(started=200.), 'environment_changed'),
    (lambda s: s.update(receivers=[]), 'receiver_missing'),
    (lambda s: s['receivers'][0].update(serial_number='USB-TWO'), 'environment_changed'),
    (lambda s: s['processes'][0].update(responding=False), 'app_unresponsive'),
])
def test_midrun_fault_latches_even_after_reconnection(change, code):
    m = module(); state = observation()
    g = m.EnvironmentGuard(observer=lambda: copy.deepcopy(state))
    change(state)
    with pytest.raises(m.GuardError) as exc: g.poll()
    assert exc.value.code == code
    state = observation()
    with pytest.raises(m.GuardError): g.check_health()
    assert g.metadata()['error']['code'] == code
    g.close()


def test_com_number_is_not_receiver_identity_and_eeg_state_remains_unknown():
    m = module(); state = observation()
    g = m.EnvironmentGuard(observer=lambda: state)
    state['receivers'][0]['port'] = 'COM37'
    g.poll(); g.check_health()
    report = g.metadata()
    assert report['observation']['receiver_port'] == 'COM37'
    assert report['recording_verified'] is False
    assert report['headset_wireless_verified'] is False
    assert report['marker_received_verified'] is False
    g.close()


def test_stale_monitor_stops_instead_of_silently_resuming():
    m = module(); clock = [10.]
    g = m.EnvironmentGuard(observer=observation, monotonic=lambda: clock[0])
    clock[0] = 14.
    with pytest.raises(m.GuardError) as exc: g.check_health()
    assert exc.value.code == 'monitor_stale'
    g.close()


def test_scanner_errors_are_not_treated_as_connected():
    m = module()
    def unavailable(): raise OSError('cannot enumerate USB')
    with pytest.raises(m.GuardError) as exc: m.EnvironmentGuard(observer=unavailable)
    assert exc.value.code == 'monitor_error'


def test_thread_records_only_environment_evidence(tmp_path):
    m = module(); g = m.EnvironmentGuard(observer=observation)
    g.start_recording(tmp_path, 1); g.check_health(); g.close()
    rows = [json.loads(s) for s in (tmp_path/'emotivpro_guard_part_001.jsonl').read_text().splitlines()]
    assert rows and rows[0]['status'] == 'ok'
    assert rows[0]['observation']['app_pid'] == 42
    assert not g.metadata()['recording_verified']


def test_real_serial_backend_closes_port_when_emotiv_is_missing(monkeypatch):
    m = module()
    import serial
    from video_eeg.utils import serial_ports
    from video_eeg.utils.serial_markers import EmotivProSerialBackend
    connection = serial.serial_for_url('loop://')
    monkeypatch.setattr(serial_ports, 'require_trigger_port', lambda p: {'port': p})
    monkeypatch.setattr(serial, 'Serial', lambda *a, **k: connection)
    monkeypatch.setattr(m, 'observe_environment', lambda: dict(processes=[], receivers=[]))
    with pytest.raises(m.GuardError): EmotivProSerialBackend('COM42')
    assert not connection.is_open


def test_fault_saves_part_and_stops_all_subsequent_markers(tmp_path):
    m = module(); state = observation()
    import serial
    from video_eeg.utils.serial_markers import EmotivProSerialBackend
    from video_eeg.experiment.video_protocol import EegSessionManager
    from video_eeg.experiment import video_runner
    g = m.EnvironmentGuard(observer=lambda: copy.deepcopy(state))
    port = serial.serial_for_url('loop://', timeout=.1)
    b = EmotivProSerialBackend('TEST', connection=port, environment_guard=g)
    acq = video_runner.build_acquirer(device_name='emotivpro', config={})
    manager = EegSessionManager(acq, b, sfreq=1000, records_dir=tmp_path,
                               subject_id='TEST', session_id=1, record_local_eeg=False)
    manager.start(output_dir=tmp_path)
    manager.emit('video_on')
    state['receivers'] = []
    with pytest.raises(m.GuardError): g.poll()
    with pytest.raises(RuntimeError): manager.raise_if_background_failed()
    manager.emit('video_off', completed=False)
    assert port.read(10) == bytes([101, 132])
    manager.stop_and_export()
    meta = json.loads((tmp_path/'metadata.json').read_text(encoding='utf-8'))
    assert meta['background_error']
    assert meta['external_environment_guard']['error']['code'] == 'receiver_missing'
    assert meta['local_eeg_recorded'] is False
    assert (tmp_path/'eeg_error_part_001.json').exists()
    assert not list(tmp_path.glob('continuous_eeg*'))


def test_guard_fault_cannot_be_registered_as_complete_eeg(tmp_path):
    from video_eeg.utils.emotivpro_recording import confirm_recording
    p = tmp_path/'metadata.json'
    p.write_text(json.dumps(dict(eeg_recording_mode='emotivpro_external', recording_uuid='r',
        external_environment_guard={'error': {'code': 'receiver_missing'}})))
    with pytest.raises(ValueError, match='故障|异常'):
        confirm_recording(p, tmp_path/'missing.edf', operator_confirmed=True)


def test_guard_fault_inside_flip_clears_callbacks_before_error_page():
    from unittest.mock import Mock
    from video_eeg.experiment import video_runner as runner
    m = module(); r = object.__new__(runner.VideoRunner)
    r.config = {'device_type': 'emotivpro'}; r.state = None
    r._active_movie = Mock(); r.win = SimpleNamespace(_toCall=[object()])
    r._show_instructions = Mock(side_effect=m.GuardError('app_missing', 'app stopped'))
    r._checkpoint = Mock(); r._stop_and_export = Mock(return_value=None)
    def error_page(*args, **kwargs):
        assert r.win._toCall == []
        r._active_movie.stop.assert_called_once()
    r._show_text = error_page
    r.run()
    assert r.termination_reason == 'eeg_background_error'


def test_start_button_rechecks_environment_after_operator_confirmation(monkeypatch):
    from video_eeg.experiment import video_runner as runner
    m = module(); r = object.__new__(runner.VideoRunner)
    r.config = {'device_type': 'emotivpro'}
    calls = []
    def probe(config):
        calls.append(1)
        if len(calls) > 1: raise m.GuardError('app_missing', 'EmotivPRO closed while waiting')
        return dict(serial_port='COM10', external_environment_guard={'enabled': True})
    screens = []
    def screen(**kwargs):
        screens.append(kwargs)
        if len(screens) == 1: return 'start'
        raise runner.ExperimentAbort()
    monkeypatch.setattr(runner, 'probe_eeg_connection', probe)
    r._device_check_action_screen = screen
    with pytest.raises(runner.ExperimentAbort): r._run_device_check_screen()
    assert len(calls) >= 2
    assert 'closed while waiting' in screens[-1]['body']


def test_operator_confirmation_button_uses_action_key_not_old_label(monkeypatch):
    from video_eeg.experiment import video_runner as runner
    r = object.__new__(runner.VideoRunner)
    def widget(*args, **kwargs):
        return SimpleNamespace(pos=kwargs.get('pos'), draw=lambda: None)
    monkeypatch.setattr(runner, 'visual', SimpleNamespace(Rect=widget, TextStim=widget))
    r.win = SimpleNamespace(flip=lambda: None)
    r.keyboard = SimpleNamespace(getKeys=lambda *a, **k: ['space'])
    r._clear_keyboard = lambda: None
    r._draw_device_status = lambda **kw: None
    r.mouse = None
    assert r._device_check_action_screen(title='environment', body='operator review', accent='#facc15',
        primary_label='主试已核对录制', secondary_label='重新检测', primary_key='space', secondary_key='r') == 'start'
