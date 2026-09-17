import json
import threading
import time
from types import SimpleNamespace
import numpy as np
import pytest
from video_eeg.experiment.eeg_health import SampleWatchdog,EegAcquisitionError,failure_message
from video_eeg.experiment.video_protocol import EegSessionManager
from video_eeg.storage.session_recorder import SessionRecorder
from video_eeg.utils.markers import NoOpMarkerBackend


def test_video_runner_exports_after_latched_eeg_fault(tmp_path):
    from unittest.mock import Mock
    from video_eeg.experiment.video_runner import VideoRunner
    r=object.__new__(VideoRunner)
    r.manager=Mock(session_dir=tmp_path)
    r.manager.raise_if_background_failed.side_effect=EegAcquisitionError('empty EEG')
    r.progress_dir=tmp_path;r.state=None;r.trial_records=[];r.attention_records=[]
    r._write_trial_log();r._write_attention_log()
    r.manager.raise_if_background_failed.assert_not_called()


class Source:
    metadata=SimpleNamespace(sfreq=1000.,n_channels=2,name='test',eeg_channel_count=None)
    def __init__(self,mode):self.mode=mode;self.reads=0
    def start_stream(self):pass
    def stop_stream(self):
        if self.mode=='exception':raise OSError('test stop failure')
    def get_new_samples(self):
        self.reads+=1
        if self.reads==1 and self.mode!='empty':return np.ones((2,20),np.float32),np.arange(20)
        if self.mode=='exception':raise ConnectionError('test connection lost')
        return np.empty((2,0),np.float32),np.empty(0)


def test_behavior_write_error_cannot_prevent_final_eeg_export(tmp_path):
    from unittest.mock import Mock
    from video_eeg.experiment.video_runner import VideoRunner
    m=EegSessionManager(Source('stalled'),NoOpMarkerBackend(),sfreq=1000,records_dir=tmp_path,subject_id='TEST',session_id=1)
    m.start(output_dir=tmp_path)
    deadline=time.monotonic()+2
    while m.recorder.sample_count==0 and time.monotonic()<deadline:time.sleep(.01)
    m._latch_fault('no_samples_timeout','test')
    r=object.__new__(VideoRunner);r.manager=m;r.progress_dir=tmp_path;r.state=None
    r.trial_records=[];r.attention_records=[];r.termination_reason='eeg_background_error';r.completed=False;r._run_traceback=None
    r._write_rest_log=Mock(side_effect=OSError('simulated behavior file failure'));r._checkpoint=Mock()
    r._state_completed_duration=lambda:0.;r.library=SimpleNamespace(root=tmp_path)
    r.config={'sfreq':1000,'hardware_dummy_mode':True}
    r.protocol=SimpleNamespace(attention_tasks_per_session=18,fixation_sec=1.5,rest_min_net_minutes=30,rest_max_net_minutes=45)
    r._stop_and_export()
    assert np.load(tmp_path/'continuous_eeg.npy').shape==(2,20)
    metadata=json.loads((tmp_path/'metadata.json').read_text(encoding='utf-8'))
    assert metadata['termination_reason']=='eeg_background_error'
    assert 'simulated behavior file failure' in metadata['behavior_export_errors'][0]


def test_watchdog_counts_not_signal_amplitude():
    w=SampleWatchdog(100.,timeout=5.,startup_timeout=10.)
    assert w.observe(0,109.)['status']=='ok'
    assert w.observe(0,110.)['status']=='no_samples_timeout'
    assert w.observe(20,111.)['status']=='ok'
    assert w.observe(20,115.99)['status']=='ok'
    assert w.observe(20,116.)['status']=='no_samples_timeout'
    assert w.observe(40,116.1)['status']=='ok'


@pytest.mark.parametrize('mode',['empty','stalled','exception'])
def test_fault_persisted_and_export_survives(mode,tmp_path):
    m=EegSessionManager(Source(mode),NoOpMarkerBackend(),sfreq=1000,records_dir=tmp_path,
        subject_id='test',session_id=1,no_sample_timeout_sec=.15,startup_timeout_sec=.3)
    m.start(output_dir=tmp_path)
    deadline=time.monotonic()+3
    while m.background_error is None and time.monotonic()<deadline:time.sleep(.01)
    with pytest.raises(EegAcquisitionError):m.raise_if_background_failed()
    assert m._stop_event.wait(2)
    error=json.loads((tmp_path/'eeg_error_part_001.json').read_text(encoding='utf-8'))
    assert error['hardware_cause']=='unknown'
    assert error['code']==('acquisition_exception' if mode=='exception' else 'no_samples_timeout')
    m.emit('video_off',completed=True)
    assert m.recorder.events[-1].payload['completed'] is False
    m.stop_and_export()
    assert np.load(tmp_path/'continuous_eeg.npy').shape==(2,0 if mode=='empty' else 20)
    assert json.loads((tmp_path/'metadata.json').read_text(encoding='utf-8'))['termination_reason']=='eeg_background_error'
    assert 'eeg_acquisition_error' in [r['name'] for r in json.loads((tmp_path/'events.json').read_text(encoding='utf-8'))]
    assert (tmp_path/'eeg_health_part_001.jsonl').stat().st_size>0


def test_frozen_recorder_rejects_late_blocked_sdk_read(tmp_path):
    release=threading.Event();entered=threading.Event()
    class Blocked(Source):
        def get_new_samples(self):
            entered.set();release.wait(2)
            return np.ones((2,20),np.float32),np.arange(20)
    r=SessionRecorder(Blocked('stalled'),sfreq=1000,n_channels=2)
    r.start_spooling(tmp_path)
    t=threading.Thread(target=r.pull);t.start();assert entered.wait(1)
    r.freeze();r.export(tmp_path,metadata={},pull_final=False)
    release.set();t.join(2)
    assert r.sample_count==0 and np.load(tmp_path/'continuous_eeg.npy').shape==(2,0)


def test_external_recording_does_not_claim_stream_monitoring(tmp_path):
    m=EegSessionManager(Source('empty'),NoOpMarkerBackend(),sfreq=1000,records_dir=tmp_path,
        subject_id='test',session_id=1,record_local_eeg=False)
    m.start(output_dir=tmp_path);m.stop_and_export()
    assert not list(tmp_path.glob('eeg_health*'))
    assert json.loads((tmp_path/'metadata.json').read_text(encoding='utf-8'))['eeg_health_monitor']['enabled'] is False


def test_independent_watchdog_detects_blocked_sdk_reader(tmp_path):
    release=threading.Event();entered=threading.Event()
    class Blocked(Source):
        def get_new_samples(self):
            entered.set();release.wait(3)
            return np.ones((2,20),np.float32),np.arange(20)
    m=EegSessionManager(Blocked('blocked'),NoOpMarkerBackend(),sfreq=1000,records_dir=tmp_path,
        subject_id='test',session_id=1,no_sample_timeout_sec=.15,startup_timeout_sec=.3)
    m.start(output_dir=tmp_path);assert entered.wait(1)
    assert m._stop_event.wait(2)
    with pytest.raises(EegAcquisitionError):m.raise_if_background_failed()
    release.set();m.stop_and_export()
    assert np.load(tmp_path/'continuous_eeg.npy').shape==(2,0)


def test_message_does_not_claim_battery_diagnosis():
    message=failure_message(EegAcquisitionError('连续5秒未收到新的EEG样本'))
    assert '未收到' in message and '不等于确认放大器没电或关机' in message
