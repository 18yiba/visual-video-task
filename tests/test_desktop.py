from pathlib import Path
import copy,json
import pytest,yaml
from video_eeg.utils.desktop import adapt_config,legacy_config

def original_project(tmp_path,bank):
    p=tmp_path/'old';cfgdir=p/'video_eeg/config';cfgdir.mkdir(parents=True)
    (cfgdir/'manifest.csv').write_text('preserve fixed assignment',encoding='utf-8')
    config=dict(device_type='brainco',hardware_dummy_mode=False,sfreq=1000,
        protocol=dict(num_sessions=17,session_manifest_path='video_eeg/config/manifest.csv',attention_tasks_per_session=18),
        storage=dict(records_dir='data/original'))
    if bank:
        (cfgdir/'bank.json').write_text('{}',encoding='utf-8');config['protocol']['question_bank_path']='video_eeg/config/bank.json'
    (cfgdir/'video_config.yaml').write_text(yaml.safe_dump(config),encoding='utf-8')
    demo=copy.deepcopy(config);demo['protocol']['attention_tasks_per_session']=3
    (cfgdir/'video_demo_config.yaml').write_text(yaml.safe_dump(demo),encoding='utf-8')
    return p,config

@pytest.mark.parametrize('bank',[False,True])
def test_binding_preserves_protocol_files_and_roots(tmp_path,bank):
    old,cfg=original_project(tmp_path,bank)
    before={p:p.read_bytes() for p in old.rglob('*') if p.is_file()}
    inherited=adapt_config({'protocol':{},'storage':{}},'video_legacy_17_config.yaml',{'legacy_project':str(old)},tmp_path/'user',tmp_path/'app')
    assert inherited['protocol']['attention_tasks_per_session']==18
    assert inherited['_legacy_attention']==(not bank)
    assert inherited['storage']['records_dir']==str(old/'data/original')
    assert Path(inherited['protocol']['session_manifest_path']).read_text(encoding='utf-8')=='preserve fixed assignment'
    assert all(p.read_bytes()==data for p,data in before.items())
    assert not inherited['hardware_dummy_mode']

def test_new_desktop_data_lives_outside_installation(tmp_path):
    cfg=adapt_config({'protocol':{}},'video_emotion_demo_config.yaml',{},tmp_path/'user',tmp_path/'app')
    assert cfg['storage']['source_data_root']==str(tmp_path/'user/data/sourcedata')
    assert cfg['demo_mode'] and cfg['hardware_dummy_mode']

def test_wrong_legacy_protocol_rejected(tmp_path):
    old,cfg=original_project(tmp_path,False);cfg['protocol']['num_sessions']=34
    (old/'video_eeg/config/video_config.yaml').write_text(yaml.safe_dump(cfg),encoding='utf-8')
    with pytest.raises(ValueError,match='17组'):legacy_config(old)

def test_running_relative_legacy_entry_is_detected(tmp_path,monkeypatch):
    import psutil
    from video_eeg.utils.desktop import assert_legacy_idle
    class Process:
        pid=-1
        info={'cmdline':['python.exe','-m','video_eeg.experiment.video_runner']}
        def cwd(self):return str(tmp_path)
    monkeypatch.setattr(psutil,'process_iter',lambda attrs:[Process()])
    with pytest.raises(RuntimeError,match='仍在运行'):assert_legacy_idle(tmp_path)
