import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import yaml


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


def test_exe_default_dispatches_v3_without_old_selector(tmp_path, monkeypatch):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'scripts'))
    spec=importlib.util.spec_from_file_location('desktop_default_test',root/'scripts/desktop_entry.py')
    desktop=importlib.util.module_from_spec(spec);spec.loader.exec_module(desktop)
    monkeypatch.setattr(desktop,'USER',tmp_path)
    monkeypatch.setattr(sys,'argv',['desktop_entry.py'])
    from video_eeg.utils import desktop_local
    monkeypatch.setattr(desktop_local,'require_local',lambda p:Path(p).resolve())
    monkeypatch.setattr(desktop_local,'validate_runtime',lambda *a,**k:None)
    settings={'schema':desktop_local.SCHEMA}
    monkeypatch.setattr(desktop,'load_settings',lambda:settings)
    calls=[]
    monkeypatch.setattr(desktop,'launch_v3',lambda s:calls.append(s) or 0)
    import launch_experiment
    monkeypatch.setattr(launch_experiment,'choose',lambda **k:(_ for _ in ()).throw(AssertionError('old UI selected')))
    assert desktop.main()==0
    assert calls==[settings]
