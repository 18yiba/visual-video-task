from pathlib import Path
import hashlib
import json
import os
import pytest
from video_eeg.utils import material_settings as media
from video_eeg.utils import desktop_local


@pytest.fixture
def roots(tmp_path,monkeypatch):
    monkeypatch.delenv('VIDEO_EEG_MATERIAL_SETTINGS',raising=False)
    root=tmp_path/'share/formal_v1'
    (root/'videos').mkdir(parents=True)
    (root/'emotion_video/selected').mkdir(parents=True)
    return tmp_path,root


def test_save_apply_only_media_and_preserve_storage(roots):
    project,root=roots
    storage={'records_dir':'local/subject','source_data_root':'local'}
    cfg={'protocol':{},'storage':storage.copy()}
    media.save(root,project)
    media.apply(cfg,project)
    assert cfg['protocol']['video_library_dir']==str(root/'videos')
    assert cfg['protocol']['emotion_library_dir']==str(root/'emotion_video')
    assert cfg['storage']==storage
    assert cfg['_material_roots_explicit']
    assert set(json.loads((project/'materials.local.json').read_text()))=={'ordinary_root','emotion_root'}
    media.check(cfg)


@pytest.mark.parametrize('leaf',['videos','emotion_video','emotion_video/selected'])
def test_leaf_selection_normalizes_to_root(roots,leaf):
    project,root=roots
    saved=media.save(root/leaf,project)
    assert saved['ordinary_root']==str(root/'videos')


def test_invalid_share_preserves_saved_settings(roots):
    project,root=roots
    media.save(root,project)
    before=(project/'materials.local.json').read_bytes()
    with pytest.raises(ValueError):media.save(project/'unavailable',project)
    assert (project/'materials.local.json').read_bytes()==before


def test_demo_does_not_use_nas(roots):
    project,root=roots
    media.save(root,project)
    cfg=dict(protocol={},hardware_dummy_mode=True)
    media.apply(cfg,project)
    assert cfg['protocol']=={}


def test_explicit_unavailable_media_never_falls_back(roots):
    from video_eeg.utils.video_library import load_video_library
    project,root=roots
    media.save(root,project)
    cfg=dict(protocol={},_project_dir=str(project))
    media.apply(cfg,project)
    (project/'video_library').mkdir()
    (project/'video_library/wrong.mp4').write_bytes(b'wrong video')
    # Empty explicitly selected location must not switch to old local materials.
    assert load_video_library(cfg).root==root/'videos'


def test_checksum_and_disconnection_fail_before_playback(tmp_path):
    path=tmp_path/'clip.mp4';path.write_bytes(b'verified material')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    media.verify_asset(path,digest)
    with pytest.raises(RuntimeError,match='SHA256'):media.verify_asset(path,'0'*64)
    with pytest.raises(RuntimeError,match='读取失败'):media.verify_asset(tmp_path/'offline.mp4',digest)


def test_ordinary_hash_comes_from_unchanged_base_catalog(tmp_path):
    source=tmp_path/'video_eeg/config';source.mkdir(parents=True)
    clip=tmp_path/'0019.mp4';clip.write_bytes(b'original bytes')
    catalog=source/'materials_manifest.json'
    catalog.write_text(json.dumps({'files':[{'path':'videos/0019.mp4',
        'sha256':hashlib.sha256(clip.read_bytes()).hexdigest()}]}),encoding='utf-8')
    before=catalog.read_bytes()
    media.verify_trial({'_project_dir':str(tmp_path)},{'trial_type':'ordinary','sha256':''},clip)
    assert catalog.read_bytes()==before


@pytest.mark.parametrize('device',['emotivpro','neuracle','brainco'])
def test_both_frontends_use_shared_local_settings(roots,monkeypatch,device):
    import sys
    project,root=roots
    media.save(root,project)
    monkeypatch.setenv('VIDEO_EEG_MATERIAL_SETTINGS',str(project/'materials.local.json'))
    monkeypatch.setenv('VIDEO_EEG_BACKEND',device)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    import launch_emotion_v3
    cfg=launch_emotion_v3.configuration()
    assert cfg['protocol']['video_library_dir']==str(root/'videos')
    assert cfg['device_type']==device
    if device=='brainco':
        assert cfg['device']['brainco_transport']=='sdk'
        assert cfg['storage']['records_dir'].endswith('_brainco')
    assert str(root) not in cfg['storage']['records_dir']


def test_v3_direct_brainco_route_keeps_sdk_backend(monkeypatch,tmp_path):
    import sys
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    import launch_emotion_v3 as front
    from video_eeg.experiment import emotion_v3_runner
    monkeypatch.setattr(front,'ROOT',tmp_path)
    seen={}
    monkeypatch.setattr(front,'configuration',lambda **kwargs:seen.update(backend=os.environ.get('VIDEO_EEG_BACKEND')) or {'device_type':'brainco'})
    monkeypatch.setattr(emotion_v3_runner,'main',lambda argv:seen.update(argv=argv) or 0)
    monkeypatch.setenv('VIDEO_EEG_BACKEND','emotivpro')
    assert front.launch_direct('acquisition','brainco',['--subject-id','12345678'])==0
    assert seen['backend']=='brainco'
    assert '--device-type' in seen['argv'] and 'brainco' in seen['argv']
    assert os.environ['VIDEO_EEG_BACKEND']=='emotivpro'


@pytest.mark.skipif(os.name!='nt',reason='Windows drive policy')
def test_network_drive_is_media_only(monkeypatch):
    path=Path(r'\\example.invalid\share\videos')
    monkeypatch.setattr(desktop_local,'no_links',lambda p:Path(p))
    monkeypatch.setattr(desktop_local.ctypes.windll.kernel32,'GetDriveTypeW',lambda p:4)
    assert desktop_local.require_material_path(path)==path
    with pytest.raises(ValueError):desktop_local.require_local(path)
