import json
import queue
import time
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
import pytest

from video_eeg.devices.emotiv_cortex_acquirer import EmotivCortexAcquirer, CortexMarker
from video_eeg.devices.cortex_transport import CortexTransport


class Client:
    def __init__(self):
        self.samples = queue.Queue()
        self.token, self.session = 'secret', None
        self.error, self.closed = None, False
        self.calls = []
        self.headset = dict(id='flex', status='connected', sensors=['A', 'B'], settings=dict(eegRate=256))
        self.sessions = []

    def login(self): pass
    def check(self):
        if self.error: raise self.error
    def close(self): self.closed = True
    def call(self, method, params=None, **kwargs):
        self.calls.append((method, params))
        return {'queryHeadsets': [self.headset], 'querySessions': self.sessions,
            'createSession': dict(id='s', headset=self.headset),
            'subscribe': dict(success=[dict(streamName='eeg', cols=['COUNTER', 'INTERPOLATED', 'B', 'A', 'MARKERS'])]),
            'createRecord': dict(record=dict(uuid='r')), 'stopRecord': {},
            'injectMarker': dict(marker=dict(uuid='m'), sessionId='s', recordId='r')}[method]


def acquirer():
    c = Client()
    a = EmotivCortexAcquirer(client_factory=lambda:c)
    a.start_stream()
    return a, c


def packet(c, counter, *, interp=0, stamp=None, sid='s'):
    c.samples.put((time.perf_counter_ns(), dict(sid=sid, time=stamp if stamp is not None else 100+counter/256,
        eeg=[counter, interp, 20., 10., []])))


def test_layout_real_rate_and_native_save(tmp_path):
    from video_eeg.experiment.video_protocol import EegSessionManager
    a, c = acquirer()
    marker = CortexMarker()
    manager = EegSessionManager(a, marker, sfreq=256, records_dir=tmp_path,
        subject_id='00000001', session_id=1)
    directory = manager.start()
    for i in range(20): packet(c, i)
    deadline = time.monotonic()+2
    while manager.recorder.sample_count < 20 and time.monotonic()<deadline: time.sleep(.01)
    manager.stop_and_export()
    m = json.loads((directory/'metadata.json').read_text())
    data = np.load(directory/m['eeg_file'])
    assert data.shape == (2, 20)
    assert np.all(data[0] == 20) and np.all(data[1] == 10)
    assert m['channel_names'] == ['B','A'] and m['sfreq'] == 256
    assert m['device_type'] == 'emotiv_cortex' and m['cortex_record_id'] == 'r'
    journal = (directory/'cortex_packets_part_001.jsonl').read_text()
    assert 'secret' not in journal and 'host_arrival_ns' in journal
    methods = [method for method, _ in c.calls]
    assert methods.index('createRecord') < methods.index('injectMarker') < methods.index('stopRecord')
    assert next(p for method,p in c.calls if method=='stopRecord') == dict(cortexToken='secret', session='s')
    assert next(p for method,p in c.calls if method=='injectMarker')['time'] > 1e12


def test_marker_wrong_session_aborts_and_saves_metadata(tmp_path):
    from video_eeg.experiment.video_protocol import EegSessionManager
    from video_eeg.experiment.video_runner import _marker_mode
    a,c=acquirer(); marker=CortexMarker()
    assert _marker_mode(marker) == 'cortex_software_marker'
    original=c.call
    def call(method,params=None,**kwargs):
        if method=='injectMarker':
            return dict(marker=dict(uuid='m'), sessionId='wrong', recordId='r')
        return original(method,params,**kwargs)
    c.call=call
    manager=EegSessionManager(a,marker,sfreq=256,records_dir=tmp_path,subject_id='00000001',session_id=1)
    with pytest.raises(RuntimeError,match='acknowledgement'): manager.start()
    m=json.loads((manager.session_dir/'metadata.json').read_text())
    assert m['background_error'] and c.closed


@pytest.mark.parametrize('change,match', [
    ({'counter':2}, 'counter'), ({'counter':0}, 'counter'),
    ({'counter':1,'interp':1}, 'interpolated'),
    ({'counter':1,'stamp':99}, 'timestamp'),
    ({'counter':1,'stamp':101}, 'timestamp'),
    ({'counter':1,'sid':'other'}, 'session'),
])
def test_bad_packets_stop(change, match):
    a,c = acquirer()
    packet(c,0); a.get_new_samples()
    packet(c,**change)
    with pytest.raises(RuntimeError, match=match): a.get_new_samples()


@pytest.mark.parametrize('last', [255,65535])
def test_known_counter_wraps(last):
    a,c=acquirer()
    packet(c,last,stamp=100); a.get_new_samples()
    packet(c,0,stamp=100+1/256)
    assert a.get_new_samples()[0].shape == (2,1)


def test_refuses_other_session_without_closing_it():
    c=Client(); c.sessions=[dict(headset=dict(id='flex'))]
    with pytest.raises(RuntimeError,match='already'):
        EmotivCortexAcquirer(client_factory=lambda:c)
    assert not any(method == 'updateSession' for method,_ in c.calls)


class Socket:
    def __init__(self): self.incoming=queue.Queue(); self.sent=[]
    def recv(self,timeout):
        try: return self.incoming.get(timeout=.02)
        except queue.Empty: raise TimeoutError
    def send(self,value): self.sent.append(json.loads(value))
    def close(self): pass


def test_transport_overflow_is_visible_and_bounded():
    ws=Socket(); t=CortexTransport(connection=ws,capacity=1)
    try:
        ws.incoming.put(json.dumps(dict(eeg=[1]))); ws.incoming.put(json.dumps(dict(eeg=[2])))
        deadline=time.monotonic()+1
        while not t.error and time.monotonic()<deadline: time.sleep(.005)
        with pytest.raises(RuntimeError,match='overflow'): t.check()
        assert t.samples.qsize()==1
    finally: t.close()


def test_transport_dead_reader_and_rpc_timeout():
    ws=Socket(); t=CortexTransport(connection=ws)
    with pytest.raises(RuntimeError,match='timed out'): t.call('test',timeout=.03)
    assert not t.pending
    ws.incoming.put('')
    deadline=time.monotonic()+1
    while not t.error and time.monotonic()<deadline: time.sleep(.005)
    with pytest.raises(RuntimeError,match='reader failed'): t.call('test')
    t.close()


def test_success_warnings_do_not_break_stream_but_disconnect_does():
    ws=Socket(); t=CortexTransport(connection=ws)
    for code in [2,9,18,32,104]: ws.incoming.put(json.dumps(dict(warning=dict(code=code))))
    ws.incoming.put(json.dumps(dict(eeg=[1])))
    deadline=time.monotonic()+1
    while t.samples.empty() and time.monotonic()<deadline: time.sleep(.005)
    t.check()
    assert t.warning_codes == [2,9,18,32,104]
    ws.incoming.put(json.dumps(dict(warning=dict(code=103))))
    while not t.error and time.monotonic()<deadline: time.sleep(.005)
    with pytest.raises(RuntimeError,match='warning 103'): t.check()
    t.close()


def test_rpc_routes_responses_and_allows_own_session_close():
    class ReplySocket(Socket):
        def send(self,value):
            super().send(value)
            request=json.loads(value)
            if request['method']=='updateSession':
                self.incoming.put(json.dumps(dict(warning=dict(code=0,message=dict(sessionId='s')))))
            self.incoming.put(json.dumps(dict(id=request['id'],result=dict(ok=True))))
    ws=ReplySocket(); t=CortexTransport(connection=ws)
    assert t.call('test') == dict(ok=True)
    t.session='s'; t.token='secret'
    t.close(); t.close()
    assert t.error is None and not t.thread.is_alive() and not t.pending


def test_disabled_camera_never_preflights_or_records(monkeypatch,tmp_path):
    from video_eeg.experiment.emotion_v3_runner import EmotionV3Runner, EmotionV2Runner
    runner=object.__new__(EmotionV3Runner)
    runner.config={'facial_recording_enabled':False}
    runner.stage='eeg'; runner.state=SimpleNamespace(queue_video_ids=['v'])
    runner.library=SimpleNamespace(rows={'v':dict(trial_type='emotion')})
    runner.manager=SimpleNamespace(emit=Mock())
    camera=Mock(side_effect=AssertionError('camera must stay unused'))
    monkeypatch.setattr('video_eeg.experiment.facial_recording.FacialRecorder',camera)
    monkeypatch.setattr(EmotionV2Runner,'_start_eeg',lambda *args:None)
    monkeypatch.setattr(EmotionV2Runner,'_run_trial',lambda *args:None)
    runner._start_eeg({}); runner._run_trial(1,SimpleNamespace(asset_id='v'))
    camera.assert_not_called()


def test_cortex_configuration_does_not_change_historical_root(monkeypatch):
    from scripts.launch_emotion_v3 import configuration
    monkeypatch.setenv('VIDEO_EEG_BACKEND','emotivpro')
    monkeypatch.setenv('VIDEO_EEG_EMOTIV_TRANSPORT','serial'); old=configuration()
    monkeypatch.setenv('VIDEO_EEG_EMOTIV_TRANSPORT','cortex'); new=configuration()
    assert old['storage']==new['storage']
    from video_eeg.experiment.acquisition import uses_emotivpro_recording
    assert uses_emotivpro_recording(old) and not uses_emotivpro_recording(new)
