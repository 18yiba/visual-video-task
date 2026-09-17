import importlib.util,json
from pathlib import Path
import pytest
from video_eeg.utils.recording_paths import recording_root

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('launcher',ROOT/'scripts/launch_experiment.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)

@pytest.mark.parametrize('key,old',[('v1','video_question_complete_runs'),('v2','video_emotion_eeg_runs/protocol_emotion_v2')])
def test_new_subject_unified_old_subject_stays_put(tmp_path,key,old):
    config=dict(_unified_protocol=key,subject_id='S1',storage={'records_dir':'data/'+old})
    assert recording_root(config,tmp_path)==tmp_path/'data/sourcedata'/key
    state=tmp_path/'data'/old/'S1/session_08/session_state.json';state.parent.mkdir(parents=True);state.write_text('original state')
    before=state.read_bytes()
    assert recording_root(config,tmp_path)==state.parents[2]
    assert recording_root(config,tmp_path,'S2')==tmp_path/'data/sourcedata'/key
    assert state.read_bytes()==before
    conflict=tmp_path/'data/sourcedata'/key/'S1/session_01/session_state.json'
    conflict.parent.mkdir(parents=True);conflict.write_text('other progress')
    with pytest.raises(RuntimeError,match='多个保存位置'):recording_root(config,tmp_path)

def test_demo_separate_and_custom_legacy_root(tmp_path):
    cfg=dict(_unified_protocol='v1',subject_id='S',demo_mode=True)
    assert recording_root(cfg,tmp_path)==tmp_path/'data/sourcedata/demo/v1'
    cfg.update(demo_mode=False,storage={'records_dir':str(tmp_path/'external')})
    p=tmp_path/'external/S/session_01/session_state.json';p.parent.mkdir(parents=True);p.touch()
    assert recording_root(cfg,tmp_path)==tmp_path/'external'
    with pytest.raises(ValueError):recording_root(cfg,tmp_path,'../escape')

def test_new_output_disk_does_not_orphan_default_sourcedata_subject(tmp_path):
    cfg=dict(_unified_protocol='v2',subject_id='S',storage={'source_data_root':str(tmp_path/'new-disk')})
    old=tmp_path/'data/sourcedata/emotion-v2/S/session_01/session_state.json'
    old.parent.mkdir(parents=True);old.touch()
    assert recording_root(cfg,tmp_path)==old.parents[2]
    assert recording_root(cfg,tmp_path,'NEW')==tmp_path/'new-disk/v2'

@pytest.mark.parametrize('key,previous',[('v1','legacy17'),('v2','emotion-v2')])
def test_renamed_versions_resume_existing_subjects_on_custom_disk(tmp_path,key,previous):
    root=tmp_path/'custom-disk'
    state=root/previous/'P/session_03/session_state.json'
    state.parent.mkdir(parents=True);state.write_text('saved-progress')
    cfg=dict(_unified_protocol=key,subject_id='P',storage={'source_data_root':str(root)})
    assert recording_root(cfg,tmp_path)==root/previous
    assert state.read_text()=='saved-progress'

def test_only_two_public_versions():
    assert set(launcher.PROTOCOLS)=={'v1','v2'}
    for retired in ['legacy34','emotion-v1','legacy2779']:
        with pytest.raises(ValueError):launcher.launch(retired,'demo')


def test_offline_legacy_arithmetic_demo_keeps_original_attention(monkeypatch):
    from video_eeg.experiment import video_runner as base
    original = base.load_config
    def configured(path):
        cfg = original(path)
        cfg['_legacy_attention'] = True
        return cfg
    monkeypatch.setattr(base, 'load_config', configured)
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    def run(args):
        cfg = base.load_config(base.CONFIG_DIR/base.DEMO_CONFIG_FILENAME)
        assert 'question_bank_path' not in cfg['protocol']
        assert cfg['_unified_protocol'] == 'v1'
        assert cfg['protocol']['attention_tasks_per_session'] == 3
        return 0
    monkeypatch.setattr(base, 'main', run)
    assert launcher.launch('v1', 'demo') == 0

@pytest.mark.parametrize('protocol',['v1','v2'])
@pytest.mark.parametrize('mode',['demo','formal'])
def test_launcher_selects_expected_config_without_editing_yaml(monkeypatch,protocol,mode):
    from video_eeg.experiment import video_runner as base
    before={p:p.read_bytes() for p in (ROOT/'video_eeg/config').glob('*.yaml')}
    def run(args):
        filename=base.DEMO_CONFIG_FILENAME if mode=='demo' else base.DEFAULT_CONFIG_FILENAME
        cfg=base.load_config(base.CONFIG_DIR/filename)
        assert cfg['_unified_protocol']==protocol
        assert ('--demo' in args)==(mode=='demo')
        if mode=='formal':
            assert '--real-eeg' in args
            if protocol=='v1':assert cfg['protocol']['num_sessions']==17
            if protocol=='v2':assert cfg['protocol']['kind']=='emotion-v2' and cfg['protocol']['rating_scale_max']==7
        return 0
    monkeypatch.setattr(base,'main',run)
    import sys
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    assert launcher.launch(protocol,mode)==0
    assert all(p.read_bytes()==data for p,data in before.items())
