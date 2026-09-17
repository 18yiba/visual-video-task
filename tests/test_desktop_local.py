from pathlib import Path
import copy,json
import pytest,yaml
from video_eeg.utils import desktop_local as local
from video_eeg.utils.desktop import adapt_config,save_json

@pytest.fixture
def layout(tmp_path,monkeypatch):
    # Use isolated workspace folders to represent the lab's C: and removed USB.
    monkeypatch.setattr(local,'require_local',local.no_links)
    app=tmp_path/'app';cfgdir=app/'video_eeg/config';cfgdir.mkdir(parents=True)
    videos=tmp_path/'lab/video_materials/formal_v1/videos';videos.mkdir(parents=True)
    files=[]
    for name in ('0001.mp4','0002.mp4'):
        p=videos/name;p.write_bytes(name.encode());files.append({'path':'videos/'+name,'bytes':p.stat().st_size,'sha256':local.sha256(p)})
    save_json(cfgdir/'materials_manifest.json',{'files':files})
    (tmp_path/'lab/video_materials/formal_v1/emotion_video/selected').mkdir(parents=True)
    old=tmp_path/'usb/old';config=old/'video_eeg/config';config.mkdir(parents=True)
    (config/'manifest.csv').write_text('original fixed membership',encoding='utf-8')
    (config/'bank.json').write_text('{"review_status":"original"}',encoding='utf-8')
    cfg={'hardware_dummy_mode':False,'device_type':'brainco','protocol':{'num_sessions':17,'attention_tasks_per_session':18,'session_manifest_path':'video_eeg/config/manifest.csv','question_bank_path':'video_eeg/config/bank.json'},'storage':{'records_dir':'data/sourcedata'}}
    (config/'video_config.yaml').write_text(yaml.safe_dump(cfg),encoding='utf-8')
    demo=copy.deepcopy(cfg);demo['hardware_dummy_mode']=True;demo['protocol'].update(num_sessions=1,trials_per_session=10,attention_tasks_per_session=3)
    (config/'video_demo_config.yaml').write_text(yaml.safe_dump(demo),encoding='utf-8')
    state=old/'data/sourcedata/S001/session_01/session_state.json'
    save_json(state,{'queue_video_ids':['0002'],'completed_video_ids':['0001'],'attention_schedule':{'0002':True}})
    (state.parent/'continuous_eeg.npy').write_bytes(b'original test bytes')
    return tmp_path,app,old,cfg

def test_find_actual_leaf_from_parent(layout):
    root,app,old,cfg=layout
    found=local.discover_materials(root/'lab',app,root/'lab')
    assert Path(found['ordinary_root'])==root/'lab/video_materials/formal_v1/videos'
    assert Path(found['emotion_root'])==root/'lab/video_materials/formal_v1/emotion_video'

def test_detached_source_preserves_state_config_and_local_output(layout):
    root,app,old,cfg=layout;user=root/'user'
    before={p:local.sha256(p) for p in local.files_under(old)}
    settings=local.migrate({},user,root/'lab',app,old)
    assert all(local.sha256(p)==h for p,h in before.items())
    data=local.local_recording_root({'_unified_protocol':'v1','subject_id':'S001'},settings)
    original=(old/'data/sourcedata/S001/session_01/session_state.json').read_bytes()
    assert (data/'S001/session_01/session_state.json').read_bytes()==original
    # Removing the source is simulated by a checked rename within pytest tmp.
    hidden=root/'usb_detached';assert old.parent.resolve().is_relative_to(root.resolve())
    old.parent.rename(hidden)
    local.validate_runtime(settings,user,app,formal=True)
    inherited=adapt_config({'protocol':{},'storage':{}},'video_legacy_17_config.yaml',settings,user,app)
    assert Path(inherited['storage']['source_data_root'])==root/'lab/data/sourcedata'
    assert inherited['protocol']['attention_tasks_per_session']==18
    assert Path(inherited['protocol']['question_bank_path']).read_text()=='{"review_status":"original"}'
    assert local.local_recording_root({'_unified_protocol':'v1'},settings,'NEW')==root/'lab/data/sourcedata/v1'
    assert local.local_recording_root({'_unified_protocol':'v2'},settings,'NEW')==root/'lab/data/sourcedata/v2'

def test_existing_local_state_not_moved_or_overwritten(layout):
    root,app,old,cfg=layout
    cfg['storage']['records_dir']=str(root/'lab/data/sourcedata')
    (old/'video_eeg/config/video_config.yaml').write_text(yaml.safe_dump(cfg),encoding='utf-8')
    state=root/'lab/data/sourcedata/S002/session_02/session_state.json'
    save_json(state,{'untouched':True});before=state.read_bytes()
    settings=local.migrate({},root/'user',root/'lab',app,old)
    assert state.read_bytes()==before
    assert local.local_recording_root({'_unified_protocol':'v1'},settings,'S002')==root/'lab/data/sourcedata'

def test_duplicate_subject_stops_instead_of_merging(layout):
    root,app,old,cfg=layout
    settings=local.migrate({},root/'user',root/'lab',app,old)
    save_json(root/'lab/data/sourcedata/v1/S001/session_01/session_state.json',{'different':True})
    with pytest.raises(RuntimeError,match='多份进度'):
        local.local_recording_root({'_unified_protocol':'v1'},settings,'S001')

def test_copy_failure_does_not_switch_settings(layout,monkeypatch):
    root,app,old,cfg=layout;user=root/'user';previous={'configured':True,'legacy_project':str(old)}
    save_json(user/'settings.json',previous)
    original=local.copy_checked
    def broken(source,dest):
        if Path(source).name=='continuous_eeg.npy':raise OSError('copy failed')
        return original(source,dest)
    monkeypatch.setattr(local,'copy_checked',broken)
    with pytest.raises(OSError,match='copy failed'):local.migrate(previous,user,root/'lab',app,old)
    assert json.loads((user/'settings.json').read_text())==previous
    assert (old/'data/sourcedata/S001/session_01/continuous_eeg.npy').exists()

def test_snapshot_tampering_stops(layout):
    root,app,old,cfg=layout;user=root/'user'
    settings=local.migrate({},user,root/'lab',app,old)
    next((Path(settings['legacy_snapshot'])/'references').glob('*bank.json')).write_text('{}')
    with pytest.raises(ValueError,match='快照被改动'):local.validate_runtime(settings,user,app)

def test_archive_only_known_caches_and_keep_records_environment(layout):
    root,app,old,cfg=layout;user=root/'user'
    for name in ('__pycache__/module.pyc','.venv/__pycache__/env.pyc','data/__pycache__/record.pyc','__pycache__/session_state.json','notes.txt'):
        p=old/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'keep or archive by category')
    settings=local.migrate({},user,root/'lab',app,old)
    assert local.archive_caches(settings,user,app)==1
    assert not (old/'__pycache__/module.pyc').exists()
    for name in ('.venv/__pycache__/env.pyc','data/__pycache__/record.pyc','__pycache__/session_state.json','notes.txt'):
        assert (old/name).is_file()
    assert list((root/'lab/_archive').rglob('module.pyc'))
    assert list((root/'lab/_archive').rglob('恢复清单.json'))

def test_symlink_rejected(layout):
    root,app,old,cfg=layout
    link=root/'linked'
    try:link.symlink_to(old,target_is_directory=True)
    except OSError:pytest.skip('Symlink creation unavailable')
    with pytest.raises(ValueError,match='junction'):local.no_links(link)

def test_nonlocal_volume_rejected_without_test_override(tmp_path,monkeypatch):
    import importlib
    # Exercise actual Windows volume guard independently of the fixture.
    if __import__('os').name!='nt':pytest.skip('Windows volume check')
    if tmp_path.anchor.lower()==Path.home().anchor.lower():pytest.skip('Need a non-profile drive')
    with pytest.raises(ValueError,match='本机用户所在磁盘'):local.require_local(tmp_path)


def test_current_desktop_rejects_arithmetic_only_without_modifying_source(layout):
    root,app,old,cfg=layout
    cfg['protocol'].pop('question_bank_path')
    path=old/'video_eeg/config/video_config.yaml';path.write_text(yaml.safe_dump(cfg),encoding='utf-8')
    before=path.read_bytes()
    with pytest.raises(ValueError,match='内容题'):
        local.migrate({},root/'user',root/'lab',app,old)
    assert path.read_bytes()==before and not (root/'user/settings.json').exists()

def test_current_content_config_wins_over_retired_arithmetic_and_demo(layout):
    root,app,old,cfg=layout
    (old/'video_eeg/config/video_legacy_17_config.yaml').write_text(yaml.safe_dump(cfg),encoding='utf-8')
    arithmetic=copy.deepcopy(cfg);arithmetic['protocol'].pop('question_bank_path')
    for name in ('video_config.yaml','video_demo_config.yaml'):
        (old/'video_eeg/config'/name).write_text(yaml.safe_dump(arithmetic),encoding='utf-8')
    settings=local.migrate({},root/'user',root/'lab',app,old)
    inherited=adapt_config({'protocol':{}},'video_demo_config.yaml',settings,root/'user',app)
    assert inherited['_legacy_attention'] is False
    assert Path(inherited['protocol']['question_bank_path']).is_file()
