import json
from pathlib import Path

import pytest

from video_eeg.utils.emotiv_roots import v3_emotiv_root


def config(mode, emotion=False):
    return {'device_type': 'emotivpro', 'device': {'emotiv_transport': mode},
            'protocol': {'separate_emotion_ratings': True, 'emotion_only': emotion},
            'storage': {'records_dir': 'data/sourcedata/v3' + ('_emotion_only' if emotion else '')}}


@pytest.mark.parametrize('mode,emotion,name', [
    ('cortex', False, 'v3_cortex'), ('cortex', True, 'v3_cortex_emotion_only'),
    ('serial', False, 'v3_emotviePRO'), ('serial', True, 'v3_emotivePRO_emotion_only'),
])
def test_new_subject_roots(tmp_path, mode, emotion, name):
    assert v3_emotiv_root(config(mode, emotion), tmp_path, '00000001').name == name
    assert list(tmp_path.iterdir()) == []


def legacy_record(root, mode, *, session=1):
    folder = root/'00000001'/f'session_{session:02d}'
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'session_state.json').write_text('{}')
    part = folder/'20261108_184818'; part.mkdir()
    info = ({'device_type':'emotiv_cortex', 'eeg_recording_mode':'local_continuous_eeg'}
            if mode == 'cortex' else {'device_type':'emotivpro', 'eeg_recording_mode':'emotivpro_external'})
    (part/'metadata.json').write_text(json.dumps(info))


@pytest.mark.parametrize('mode', ['cortex','serial'])
@pytest.mark.parametrize('emotion', [False,True])
def test_legacy_resume_and_device_isolation(tmp_path, mode, emotion):
    old = tmp_path/'data'/'sourcedata'/('v3_emotion_only' if emotion else 'v3')
    legacy_record(old, mode)
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in old.rglob('*') if p.is_file()}
    assert v3_emotiv_root(config(mode, emotion), tmp_path, '00000001') == old
    other = 'serial' if mode == 'cortex' else 'cortex'
    assert v3_emotiv_root(config(other, emotion), tmp_path, '00000001') != old
    assert before == {str(p.relative_to(tmp_path)): p.read_bytes() for p in old.rglob('*') if p.is_file()}


def test_conflicting_roots_stop_and_show_paths(tmp_path):
    old = tmp_path/'data/sourcedata/v3'; legacy_record(old, 'cortex')
    new = tmp_path/'data/sourcedata/v3_cortex/00000001/session_02'
    new.mkdir(parents=True); (new/'session_state.json').write_text('{}')
    with pytest.raises(RuntimeError) as error:
        v3_emotiv_root(config('cortex'), tmp_path, '00000001')
    assert str(old/'00000001') in str(error.value)
    assert str(new.parent) in str(error.value)


def test_unknown_or_mixed_legacy_fails_closed(tmp_path):
    old = tmp_path/'data/sourcedata/v3'; legacy_record(old, 'cortex')
    legacy_record(old, 'serial', session=2)
    with pytest.raises(RuntimeError, match='混有'):
        v3_emotiv_root(config('cortex'), tmp_path, '00000001')
    other = tmp_path/'data/sourcedata/v3/00000002/session_01'
    other.mkdir(parents=True); (other/'session_state.json').write_text('{}')
    with pytest.raises(RuntimeError, match='缺少'):
        v3_emotiv_root(config('cortex'), tmp_path, '00000002')


def test_orphan_directory_is_not_silently_replaced(tmp_path):
    old = tmp_path/'data/sourcedata/v3/00000001'
    old.mkdir(parents=True); (old/'unidentified.log').write_text('preserve')
    with pytest.raises(RuntimeError, match='缺少可识别进度'):
        v3_emotiv_root(config('cortex'), tmp_path, '00000001')
    assert (old/'unidentified.log').read_text() == 'preserve'


def test_runner_and_progress_use_same_subject_root(tmp_path, monkeypatch):
    from video_eeg.experiment import video_runner
    from video_eeg.utils import v3_progress
    monkeypatch.setattr(video_runner, 'PROJECT_ROOT', tmp_path)
    cfg = config('cortex')
    cfg.update(subject_id='00000001', demo_mode=False)
    assert video_runner._records_dir(cfg) == tmp_path/'data/sourcedata/v3_cortex'
    legacy = tmp_path/'data/sourcedata/v3'
    legacy_record(legacy, 'cortex')
    assert video_runner._records_dir(cfg) == legacy
    # Same resolver is used by the console's progress inspection.
    assert v3_progress.inspect_progress.__globals__['Path'] is Path
    assert v3_emotiv_root(cfg, tmp_path, cfg['subject_id']) == legacy
