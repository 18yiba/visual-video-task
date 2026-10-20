import json

import pytest

from video_eeg.experiment import video_runner as runner
from video_eeg.experiment.video_protocol import EegSessionManager
from video_eeg.utils.markers import PROTOCOL_EVENT_CODES


def backend():
    from video_eeg.utils.serial_markers import EmotivProSerialBackend
    import serial
    return EmotivProSerialBackend('TEST', connection=serial.serial_for_url('loop://', timeout=.2))


def test_every_protocol_code_is_one_unsigned_byte_without_framing():
    b = backend()
    try:
        for name, code in PROTOCOL_EVENT_CODES.items():
            b.send_event(name)
            assert b._serial.read(2) == bytes([code])
        for invalid in (0, 256, -1, 1.5, True):
            with pytest.raises(ValueError):
                b.send(invalid)
        assert b._serial.read(1) == b''
    finally:
        b.close()


def test_serial_failure_is_sticky_and_not_claimed_received(tmp_path):
    b = backend()
    b.start_recording(tmp_path, 1, 'test')
    b._serial.close()
    with pytest.raises(RuntimeError):
        b.send_event('video_on')
    with pytest.raises(RuntimeError):
        b.send_event('video_off')
    b.close()
    rows = [json.loads(x) for x in (tmp_path/b.receipt_filename).read_text().splitlines()]
    assert len(rows) == 1 and rows[0]['status'] == 'failed'
    assert rows[0]['emotivpro_received'] is None
    assert b.recording_metadata()['serial_write_error']


def test_emotivpro_backend_has_no_eeg_stream_and_preserves_parts(tmp_path, monkeypatch):
    cfg = dict(device_type='emotivpro', sfreq=1000, device={})
    assert runner.uses_external_recording(cfg)
    acq = runner.build_acquirer(device_name='emotivpro', config=cfg)
    monkeypatch.setattr(acq, 'start_stream', lambda: pytest.fail('must not acquire EEG'))
    for part in (1, 2):
        b = backend()
        manager = EegSessionManager(acq, b, sfreq=1000, records_dir=tmp_path,
            subject_id='TEST', session_id=1, record_local_eeg=False)
        manager.start(output_dir=tmp_path)
        manager.emit('video_on')
        manager.emit('video_off')
        manager.stop_and_export()
        metadata = json.loads((tmp_path/manager.recorder.metadata_filename).read_text())
        assert metadata['eeg_recording_mode'] == 'emotivpro_external'
        assert metadata['sfreq'] is None and metadata['n_channels'] is None
        assert metadata['expected_sampling_rate_hz'] is None
        assert metadata['local_eeg_recorded'] is False
        assert metadata['eeg_health_monitor']['enabled'] is False
        events = json.loads((tmp_path/manager.recorder.events_filename).read_text())
        assert [e['payload']['marker_code'] for e in events] == [101, 132, 133, 102]
        assert all(e['sample_index'] is None for e in events)
        assert all(e['payload']['marker_delivery'] == 'serial_written_unconfirmed' for e in events)
        assert (tmp_path/f'emotivpro_serial_part_{part:03d}.jsonl').exists()
    assert not list(tmp_path.glob('continuous_eeg*'))
    segments = json.loads((tmp_path/'eeg_segments.json').read_text())['segments']
    assert len(segments) == 2 and all(s['sfreq'] is None for s in segments)


def test_missing_port_stops_formal_but_demo_never_opens_port():
    cfg = dict(device_type='emotivpro', device={'emotivpro_transport':'serial'})
    assert runner.parse_args(['--device-type', 'emotivpro']).device_type == 'emotivpro'
    with pytest.raises(ValueError, match='串口'):
        runner.build_marker_backend(cfg)
    cfg['hardware_dummy_mode'] = True
    assert not runner.uses_external_recording(cfg)
    assert type(runner.build_marker_backend(cfg)).__name__ == 'NoOpMarkerBackend'


def test_preflight_checks_port_only_and_never_claims_eeg(monkeypatch):
    b = backend()
    monkeypatch.setattr(runner, 'build_marker_backend', lambda config: b)
    result = runner.probe_eeg_connection(dict(device_type='emotivpro', device={'emotivpro_transport':'serial','emotivpro_serial_port':'TEST'}))
    assert result['recording_mode'] == 'emotivpro_external'
    assert result['samples'] is None and result['sfreq'] is None
    assert result['emotivpro_recording_confirmed'] is False
    assert not b._serial.is_open










def test_short_write_aborts_before_trial_can_complete(tmp_path):
    from video_eeg.utils.serial_markers import EmotivProSerialBackend
    class BrokenPort:
        def write(self, data): return 0
        def close(self): pass
    b = EmotivProSerialBackend('TEST', connection=BrokenPort())
    with pytest.raises(RuntimeError, match='complete marker'):
        b.send_event('video_on')
    assert b.recording_metadata()['serial_markers_written'] == 0
    b.close()


def test_first_marker_failure_saves_external_metadata(tmp_path):
    b = backend()
    b._serial.close()
    acq = runner.build_acquirer(device_name='emotivpro', config={'sfreq':1000})
    m = EegSessionManager(acq, b, sfreq=1000, records_dir=tmp_path,
        subject_id='TEST', session_id=3, record_local_eeg=False)
    with pytest.raises(RuntimeError):
        m.start(output_dir=tmp_path, metadata={'operator_confirmed_recording':True})
    metadata = json.loads((tmp_path/'metadata.json').read_text())
    assert metadata['sfreq'] is None
    assert metadata['n_channels'] is None
    assert metadata['eeg_recording_mode'] == 'emotivpro_external'
    assert metadata['serial_write_error']
    assert metadata['subject_id'] == 'TEST' and metadata['session_id'] == 3
    assert metadata['operator_confirmed_recording'] is True
    assert metadata['completed'] is False


def test_log_failure_preserves_written_byte_in_event(tmp_path):
    b = backend()
    acq = runner.build_acquirer(device_name='emotivpro', config={'sfreq':1000})
    m = EegSessionManager(acq, b, sfreq=1000, records_dir=tmp_path,
        subject_id='TEST', session_id=1, record_local_eeg=False)
    m.start(output_dir=tmp_path)
    original = b._receipt
    class FullDisk:
        def write(self, text): raise OSError('disk full')
        def flush(self): pass
        def close(self): original.close()
    b._receipt = FullDisk()
    with pytest.raises(RuntimeError, match='disk full'):
        m.emit('video_on')
    assert b._serial.read(2) == bytes([101,132])
    assert m.recorder.events[-1].payload['external_marker_sent'] is True
    assert m.recorder.events[-1].payload['external_marker_received'] is None
    m.stop_and_export()


def test_serial_flip_failure_clears_callbacks_and_stops_movie_before_error_ui(tmp_path):
    from unittest.mock import Mock
    from types import SimpleNamespace
    r = object.__new__(runner.VideoRunner)
    r.config = {'device_type':'emotivpro'}
    r._active_movie = Mock()
    r.win = SimpleNamespace(_toCall=[lambda: pytest.fail('stale callback repeated')])
    r._show_instructions = Mock(side_effect=RuntimeError('serial write failed inside flip'))
    r._checkpoint = Mock()
    r._stop_and_export = Mock(return_value=tmp_path)
    r._run_traceback = ''
    def show(*args, **kwargs):
        assert not r.win._toCall
        r._active_movie.stop.assert_called_once()
    r._show_text = show
    r.run()




def test_port_discovery_is_fresh_and_rejects_removed_port(monkeypatch):
    from serial.tools import list_ports
    from serial.tools.list_ports_common import ListPortInfo
    from video_eeg.utils.serial_ports import available_ports, require_trigger_port
    port = ListPortInfo('COM17');port.description='USB UART';port.hwid='USB VID:PID=0403:6001 SER=test'
    monkeypatch.setattr(list_ports, 'comports', lambda: [port])
    assert available_ports()[0]['port'] == 'COM17'
    assert require_trigger_port('com17')['port'] == 'COM17'
    monkeypatch.setattr(list_ports, 'comports', lambda: [])
    with pytest.raises(ValueError, match='不存在|已拔出'):
        require_trigger_port('COM17')


def test_ble_interface_blocked_but_virtual_pair_accepted(monkeypatch):
    from serial.tools import list_ports
    from serial.tools.list_ports_common import ListPortInfo
    from video_eeg.utils.serial_ports import require_trigger_port
    port = ListPortInfo('COM29');port.vid=0x1915;port.pid=0xc00a
    monkeypatch.setattr(list_ports, 'comports', lambda: [port])
    with pytest.raises(ValueError, match='通信接口'):
        require_trigger_port('COM29')
    port.vid=None;port.pid=None;port.description='com0com virtual serial port'
    assert require_trigger_port('COM29')['port_kind'] == 'virtual_pair'
    port.description = 'Eterlogic Virtual Serial Port (COM29)'
    assert require_trigger_port('COM29')['port_kind'] == 'virtual_pair'


def test_disconnected_serial_is_detected_without_sending_a_marker(tmp_path):
    b = backend()
    acq = runner.build_acquirer(device_name='emotivpro', config={'sfreq':1000})
    m = EegSessionManager(acq, b, sfreq=1000, records_dir=tmp_path,
        subject_id='TEST', session_id=1, record_local_eeg=False)
    m.start(output_dir=tmp_path)
    b._serial.close()
    with pytest.raises(RuntimeError, match='串口'):
        m.raise_if_background_failed()
    m.stop_and_export()
    assert json.loads((tmp_path/'metadata.json').read_text())['serial_write_error']


def test_driver_removal_latches_error_without_writing():
    from video_eeg.utils.serial_markers import EmotivProSerialBackend
    class RemovedAdapter:
        is_open = True  # pySerial retains this flag after physically unplugging USB.
        @property
        def in_waiting(self):
            raise OSError('ClearCommError failed')
        def write(self, data):
            pytest.fail('health check must not send a byte')
        def close(self): pass
    b = EmotivProSerialBackend('TEST', connection=RemovedAdapter())
    with pytest.raises(RuntimeError, match='ClearCommError'):
        b.check_health()
    with pytest.raises(RuntimeError, match='ClearCommError'):
        b.send(101)
    assert b.recording_metadata()['serial_markers_written'] == 0


def test_formal_backend_revalidates_port_before_opening(monkeypatch):
    from serial.tools import list_ports
    from serial.tools.list_ports_common import ListPortInfo
    from video_eeg.utils.serial_markers import EmotivProSerialBackend
    import serial
    port = ListPortInfo('COM29');port.vid=0x1915;port.pid=0xc00a
    monkeypatch.setattr(list_ports, 'comports', lambda: [port])
    monkeypatch.setattr(serial, 'Serial', lambda *a, **kw: pytest.fail('must not open BLE interface'))
    with pytest.raises(ValueError, match='通信接口'):
        EmotivProSerialBackend('COM29')
    monkeypatch.setattr(list_ports, 'comports', lambda: [])
    with pytest.raises(ValueError, match='已拔出'):
        EmotivProSerialBackend('COM29')


def test_occupied_port_gives_actionable_error_without_claiming_owner(monkeypatch):
    from serial.tools import list_ports
    from serial.tools.list_ports_common import ListPortInfo
    from video_eeg.utils.serial_markers import EmotivProSerialBackend
    import serial
    port = ListPortInfo('COM17');port.description='USB UART'
    monkeypatch.setattr(list_ports, 'comports', lambda: [port])
    def denied(*args, **kwargs):
        raise serial.SerialException('PermissionError(13, access denied)')
    monkeypatch.setattr(serial, 'Serial', denied)
    with pytest.raises(RuntimeError, match='可能被占用'):
        EmotivProSerialBackend('COM17')


def test_physical_usb_cdc_named_virtual_com_port_is_not_a_virtual_pair(monkeypatch):
    from serial.tools import list_ports
    from serial.tools.list_ports_common import ListPortInfo
    from video_eeg.utils.serial_ports import require_trigger_port
    port = ListPortInfo('COM23');port.description='STM32 Virtual ComPort'
    port.vid=0x0483;port.pid=0x5740
    monkeypatch.setattr(list_ports, 'comports', lambda: [port])
    assert require_trigger_port('COM23')['blocked_reason'] == ''
