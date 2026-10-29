import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import yaml
import pytest


def test_v3_desktop_uses_local_materials_and_independent_records(tmp_path, monkeypatch):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'scripts'))
    spec=importlib.util.spec_from_file_location('desktop_v3_test',root/'scripts/desktop_entry.py')
    desktop=importlib.util.module_from_spec(spec);spec.loader.exec_module(desktop)
    monkeypatch.setattr(desktop,'USER',tmp_path)
    import launch_emotion_v3 as front
    from video_eeg.utils import desktop_local
    monkeypatch.setattr(desktop_local,'require_local',lambda p:Path(p).resolve())
    monkeypatch.setattr(front,'make_window',lambda:SimpleNamespace(exec=lambda:0))
    settings=dict(schema=2,data_root=str(tmp_path/'records'),ordinary_root=str(tmp_path/'ordinary'),
        emotion_root=str(tmp_path/'emotion'),legacy_snapshot=str(tmp_path/'old'))
    monkeypatch.setenv('VIDEO_EEG_V3_CONFIG','')
    assert desktop.launch_v3(settings)==0
    cfg=yaml.safe_load((tmp_path/'v3-desktop.yaml').read_text(encoding='utf-8'))
    assert cfg['storage']['records_dir']==str(tmp_path/'records/v3')
    assert cfg['protocol']['separate_emotion_ratings']
    assert cfg['protocol']['emotion_library_dir']==settings['emotion_root']
    assert not cfg['hardware_dummy_mode']
    loaded=front.configuration(True)
    assert loaded['storage']['records_dir']==str(tmp_path/'records/v3_emotion_only')
    assert not list((tmp_path/'records').glob('**/session_state.json'))


def test_behavior_rating_has_direct_console_entry(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'scripts'))
    import launch_emotion_v3 as front
    calls=[]
    window=SimpleNamespace(stage=SimpleNamespace(setCurrentIndex=lambda value:calls.append(('stage',value))),
                           launch=lambda:calls.append(('launch',)))
    front.launch_behavior_rating(window)
    assert calls==[('stage',1),('launch',)]
    source=(root/'scripts/launch_emotion_v3.py').read_text(encoding='utf-8')
    assert "self.rate = W.QPushButton('开始行为评分')" in source
    assert 'self.rate.clicked.connect(lambda: launch_behavior_rating(self))' in source


def test_behavior_rating_graphical_entry_builds_rating_only_route():
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('rating_emotion_v3_test',root/'scripts/rating_emotion_v3.py')
    rating=importlib.util.module_from_spec(spec);spec.loader.exec_module(rating)
    assert rating.rating_arguments('neuracle','12345678',7)==[
        'main.py','--paradigm','v3','--phase','behavior-rating','--device','neuracle',
        '--subject-id','12345678','--session-id','7','--no-dialog','--integrated-startup']
    assert '--emotion-only' in rating.rating_arguments('brainco','12345678',1,emotion_only=True)
    assert '--windowed' in rating.rating_arguments('emotivpro','12345678',1,fullscreen=False)
    batch=(root/'rating_emotion_v3.bat').read_text(encoding='utf-8')
    assert 'scripts\\rating_emotion_v3.py' in batch


def test_installed_launcher_routes_rating_shortcut_to_graphical_entry(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('desktop_rating_route_test',root/'scripts/desktop_entry.py')
    desktop=importlib.util.module_from_spec(spec);spec.loader.exec_module(desktop)
    monkeypatch.syspath_prepend(str(root/'scripts'))
    import types
    rating=types.ModuleType('rating_emotion_v3');rating.main=lambda:23
    with __import__('unittest.mock',fromlist=['patch']).patch.dict(sys.modules, {'rating_emotion_v3':rating}):
        assert desktop.launch_v3(rating_only=True)==23


@pytest.mark.parametrize(('device','ratings'), [('emotivpro',False),('neuracle',False),
                                                ('emotivpro',True),('neuracle',True)])
def test_exe_default_dispatches_v3_without_old_selector(tmp_path, monkeypatch, device, ratings):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'scripts'))
    spec=importlib.util.spec_from_file_location('desktop_default_test',root/'scripts/desktop_entry.py')
    desktop=importlib.util.module_from_spec(spec);spec.loader.exec_module(desktop)
    monkeypatch.setattr(desktop,'USER',tmp_path)
    monkeypatch.setenv('VIDEO_EEG_BACKEND','untrusted-inherited-value')
    monkeypatch.setattr(sys,'argv',['desktop_entry.py','--device',device,*(['--ratings'] if ratings else [])])
    from video_eeg.utils import desktop_local
    monkeypatch.setattr(desktop_local,'require_local',lambda p:Path(p).resolve())
    monkeypatch.setattr(desktop_local,'validate_runtime',lambda *a,**k:None)
    settings={'schema':desktop_local.SCHEMA}
    monkeypatch.setattr(desktop,'load_settings',lambda:settings)
    calls=[]
    monkeypatch.setattr(desktop,'launch_v3',lambda s,**kwargs:calls.append((s,kwargs)) or 0)
    import launch_experiment
    monkeypatch.setattr(launch_experiment,'choose',lambda **k:(_ for _ in ()).throw(AssertionError('old UI selected')))
    assert desktop.main()==0
    assert calls==[(settings,{'rating_only':ratings})]
    import os
    assert os.environ['VIDEO_EEG_BACKEND']==device


def test_installer_has_both_explicit_device_shortcuts():
    root=Path(__file__).resolve().parents[1]
    assert not (root/'packaging').exists()
    installer_source=root.parent/'visual-video-package'/'video-task.iss'
    if not installer_source.is_file():
        pytest.skip('Windows installer source is maintained outside the paradigm repository')
    text=installer_source.read_text(encoding='utf-8')
    assert 'Parameters: --device emotivpro' in text
    assert 'Parameters: --device neuracle' in text
    assert 'Parameters: --ratings --device emotivpro' in text
    assert 'Parameters: --ratings --device neuracle' in text
    assert 'EMOTIV设备入口' in text and '博睿康设备入口' in text
