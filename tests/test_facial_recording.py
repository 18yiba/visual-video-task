import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from video_eeg.experiment.facial_recording import (
    FacialRecorder, FacialRecordingError, reserve_path, validate_coverage, onset_frame_alignment,
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
        SimpleNamespace(stderr='vcodec=mjpeg min s=1920x1080 fps=30 max s=1920x1080 fps=60.0002'),
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
    log = json.loads((tmp_path/'facial_recording_log.jsonl').read_text(encoding='utf-8').splitlines()[-1])
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


@pytest.mark.parametrize('fails_before_frame', [False, True])
def test_camera_start_marker_once_after_first_frame(monkeypatch, tmp_path, fails_before_frame):
    r = FacialRecorder(tmp_path, 'start', 2)
    r.preflight = Mock()
    monkeypatch.setattr('video_eeg.experiment.facial_recording.subprocess.Popen', Mock())
    monkeypatch.setattr('video_eeg.experiment.facial_recording.threading.Thread', Mock())
    monkeypatch.setattr('video_eeg.experiment.facial_recording.time.sleep', Mock())
    callback = Mock()
    checks = []

    def check(startup=False):
        assert startup
        checks.append(True)
        if fails_before_frame:
            raise FacialRecordingError('no frame')
        if len(checks) == 1:
            r.frames = [(0, 10., 0.)]
        else:
            r.frames = [(i, 10. + i / 30, i / 30) for i in range(17)]
            r.path.write_bytes(b'video header')

    r.check = check
    if fails_before_frame:
        with pytest.raises(FacialRecordingError, match='no frame'):
            r.start(on_started=callback)
        callback.assert_not_called()
    else:
        r.start(on_started=callback)
        callback.assert_called_once()
        fields = callback.call_args.kwargs
        assert fields['facial_attempt'] == 2
        assert fields['camera_first_frame_monotonic_sec'] == 10.
        assert fields['facial_file'] == 'start_facial.mp4'
        rows = [json.loads(line) for line in
                (tmp_path / 'facial_recording_log.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [row['status'] for row in rows] == ['reserved', 'recording_started']
@pytest.mark.parametrize('stage,trial_type,expected', [('eeg', 'emotion', 1),
    ('eeg', 'ordinary', 0), ('ratings', 'emotion', 0)])
def test_v3_capture_scope_and_cleanup(monkeypatch, tmp_path, stage, trial_type, expected):
    from video_eeg.experiment.emotion_v3_runner import EmotionV3Runner, EmotionV2Runner
    r = object.__new__(EmotionV3Runner)
    r.config = {"facial_recording_enabled": True, "device_type": "neuracle"}
    r.stage = stage
    r.library = SimpleNamespace(rows={'v': {'trial_type': trial_type}})
    r.progress_dir = tmp_path
    r._attempt_counter_by_video = {}
    original_emit = Mock()
    r.manager = SimpleNamespace(emit=original_emit)
    recorder = Mock()
    recorder.events = {}
    factory = Mock(return_value=recorder)
    monkeypatch.setattr('video_eeg.experiment.facial_recording.FacialRecorder', factory)
    def trial(self, idx, asset):
        recorder.events['stimulus_flip'] = dict(monotonic_sec=.8)
        self._event_times = dict(video_on=dict(monotonic_sec=1., sample_index=4))
        self.manager.emit('video_on')
        raise RuntimeError('playback failed')
    monkeypatch.setattr(EmotionV2Runner, '_run_trial', trial)
    with pytest.raises(RuntimeError, match='playback failed'):
        r._run_trial(1, SimpleNamespace(asset_id='v', rel_path='emotion/E01.mp4'))
    assert factory.call_count == expected
    assert recorder.finish.call_count == expected
    assert recorder.boundary.call_count == expected
    if expected:
        assert factory.call_args.kwargs['device_type'] == 'neuracle'
        assert original_emit.call_args.kwargs['stimulus_flip_monotonic_sec'] == .8
        assert recorder.boundary.call_args.args[1]['monotonic_sec'] == .8
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
    row = json.loads((tmp_path/'facial_recording_log.jsonl').read_text(encoding='utf-8').splitlines()[-1])
    assert row['status'] == 'failed'


def test_onset_alignment_brackets_and_preserves_media_pts():
    result = onset_frame_alignment([(0, 10., 0.), (1, 10.04, .04)], 10.03, [0., .04])
    assert result['before']['frame'] == 0
    assert result['after']['frame'] == result['nearest']['frame'] == 1
    assert result['nearest']['encoded_pts_sec'] == .04
    assert result['nearest']['relative_video_onset_sec'] == pytest.approx(.01)
    assert result['bracket_interval_sec'] == pytest.approx(.04)
    assert result['exposure_alignment_verified'] is False


@pytest.mark.parametrize('onset', [None, 9., 11., float('nan')])
def test_onset_alignment_requires_observed_coverage(onset):
    assert onset_frame_alignment([(0, 10., 0.)], onset, [])['status'] == 'unavailable'


@pytest.mark.parametrize('mode,size,codec,pixel', [
    ('vcodec=mjpeg min s=1920x1080 fps=30 max s=1920x1080 fps=60.0002', '1920x1080', 'mjpeg', None),
    ('pixel_format=nv12 min s=2560x1440 fps=30 max s=2560x1440 fps=30', '2560x1440', None, 'nv12'),
])
def test_advertised_camera_mode_shared_by_probe_and_capture(tmp_path, mode, size, codec, pixel):
    r = FacialRecorder(tmp_path, 'v', 1)
    r._command = Mock(side_effect=[
        SimpleNamespace(stderr='"UGREEN Camera 4K" (video)'),
        SimpleNamespace(returncode=1, stderr=mode + '\nImmediate exit requested'),
        SimpleNamespace(returncode=0, stderr='Video: h264, yuv420p, 1920x1080, 30 fps')])
    r.preflight()
    args = r._input_args()
    assert args[args.index('-video_size')+1] == size
    assert r.input_codec == codec and r.input_pixel_format == pixel
    probe = r._command.call_args.args[0]
    assert probe[1:1+len(args)] == args
    assert probe[probe.index('-vf')+1] == r._video_filter()
    assert ('scale=' in r._video_filter()) == (size == '2560x1440')
    assert 'fps=' not in r._video_filter()
    r.path, r.number = reserve_path(tmp_path, 'v')
    r._log('reserved')
    row = json.loads((tmp_path/'facial_recording_log.jsonl').read_text(encoding='utf-8'))
    assert row['input_codec'] == codec
    assert row['input_width'] == int(size.split('x')[0])
    assert row['width'] == 1920


def test_prefers_native_1080_mjpeg_and_rejects_five_fps_raw(tmp_path):
    r = FacialRecorder(tmp_path, 'v', 1)
    raw = 'pixel_format=yuyv422 min s=1920x1080 fps=5 max s=1920x1080 fps=5'
    modes = raw + '\nvcodec=mjpeg min s=1920x1080 fps=30 max s=1920x1080 fps=60.0002'
    r._command = Mock(side_effect=[SimpleNamespace(stderr='"UGREEN Camera 4K" (video)'),
        SimpleNamespace(stderr=modes), SimpleNamespace(returncode=0, stderr='1920x1080, 30 fps')])
    r.preflight()
    assert r.input_codec == 'mjpeg'
    assert '-pixel_format' not in r._input_args()
    r._command = Mock(side_effect=[SimpleNamespace(stderr='"UGREEN Camera 4K" (video)'),
        SimpleNamespace(stderr=raw)])
    with pytest.raises(FacialRecordingError, match='未报告'):
        r.preflight()


@pytest.mark.parametrize('names', [
    '"UGREEN Camera 4K" (video)',
    '"facialcamera" (video)\n"facialcamera" (video)',
    '"facialcamera extra" (video)',
    '"facialcamera" (audio)',
])
def test_neuracle_requires_unique_exact_friendlyname(tmp_path, names):
    recorder = FacialRecorder(tmp_path, 'v', 1, device_type='neuracle')
    recorder._command = Mock(return_value=SimpleNamespace(stderr=names))
    with pytest.raises(FacialRecordingError, match='facialcamera'):
        recorder.preflight()
    assert recorder._command.call_count == 1


def test_neuracle_friendlyname_used_for_probe_and_capture(tmp_path):
    recorder = FacialRecorder(tmp_path, 'v', 1, device_type='neuracle')
    recorder._command = Mock(side_effect=[
        SimpleNamespace(stderr='"UGREEN Camera 4K" (video)\n"facialcamera" (video)'),
        SimpleNamespace(stderr='vcodec=mjpeg min s=1920x1080 fps=30 max s=1920x1080 fps=30'),
        SimpleNamespace(returncode=0, stderr='1920x1080 30 fps'),
    ])
    recorder.preflight()
    for call in recorder._command.call_args_list[1:]:
        assert 'video=facialcamera' in call.args[0]
    assert 'video=facialcamera' in recorder._input_args()
    assert FacialRecorder(tmp_path, 'v', 1, device_type='brainco').device == 'UGREEN Camera 4K'


def test_neuracle_initial_preflight_routes_device(monkeypatch, tmp_path):
    from video_eeg.experiment.emotion_v3_runner import EmotionV3Runner, EmotionV2Runner
    runner = object.__new__(EmotionV3Runner)
    runner.config = dict(device_type='neuracle', facial_recording_enabled=True)
    runner.state = SimpleNamespace(queue_video_ids=['v'])
    runner.library = SimpleNamespace(rows={'v': {'trial_type': 'emotion'}})
    runner.progress_dir = tmp_path
    factory = Mock()
    monkeypatch.setattr('video_eeg.experiment.facial_recording.FacialRecorder', factory)
    monkeypatch.setattr(EmotionV2Runner, '_start_eeg', Mock())
    runner._start_eeg({})
    factory.assert_called_once_with(tmp_path, 'preflight', 0, device_type='neuracle')
    factory.return_value.preflight.assert_called_once()
