from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from video_eeg.experiment import emotion_runner, video_runner as base
from video_eeg.experiment import emotion_v2_runner
from video_eeg.utils import emotion_protocol
from video_eeg.utils.video_library import VideoAsset

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('demo',[True,False])
def test_new_main_dispatches_to_v2_with_question_bank(monkeypatch,demo):
    seen={}
    class Runner:
        def __init__(self,**kw):
            seen.update(kw)
        def run(self):
            seen['ran']=True
    asset=VideoAsset('test','practice/test.mp4',5.)
    library=SimpleNamespace(is_available=lambda a:True)
    monkeypatch.setattr(emotion_v2_runner,'EmotionV2Runner',Runner)
    monkeypatch.setattr(emotion_protocol,'prepare',lambda cfg,demo:(library,[asset]))
    monkeypatch.setattr(base,'_load_psychopy',lambda:None)
    monkeypatch.setattr(base,'visual',SimpleNamespace(Window=lambda **kw:Mock()))
    monkeypatch.setattr(base,'Keyboard',Mock)
    monkeypatch.setattr(base,'core',Mock())
    args=['--no-dialog','--session-id','1','--windowed']+(['--demo'] if demo else [])
    assert emotion_runner.main(args)==0
    assert seen['ran'] and seen['config']['protocol']['kind']=='emotion-v2'
    assert seen['config']['protocol'].get('question_bank_path')
    assert seen['protocol'].attention_tasks_per_session==(1 if demo else 9)
    assert seen['config']['storage']['records_dir'].startswith('data/video_emotion_eeg_runs/')

def test_new_bats_use_new_config_and_legacy_entry_preserves_old_config():
    source=(ROOT/'scripts/run_video_emotion_formal.bat').read_text()
    assert 'video_emotion_config.yaml' in source
    assert 'VIDEO_EEG_EMOTION_CONFIG' in source
    assert '-m video_eeg.experiment.emotion_runner' in source
    assert 'video_config.yaml' in (ROOT/'scripts/run_video_formal.bat').read_text()

def test_prepare_uses_portable_ordinary_fallback_and_local_emotion_override(tmp_path):
    import json
    import csv
    (tmp_path/'stimuli/videos').mkdir(parents=True)
    (tmp_path/'stimuli/videos/example.mp4').touch()
    (tmp_path/'emotion_library.local.json').write_text(json.dumps({'emotion_root':'materials/emotion_video'}))
    row=dict(video_id='original:test',video_path='original/example.mp4',video_duration_sec=5,
             trial_type='ordinary',session_id=1,original_label='',three_class_label='')
    with (tmp_path/'manifest.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    config={'_project_dir':str(tmp_path),'session_id':1,'protocol':dict(video_library_dir='../video_materials/formal_v1/videos',session_manifest='manifest.csv')}
    library,playlist=emotion_protocol.prepare(config,False)
    assert library.resolve(playlist[0])==tmp_path/'stimuli/videos/example.mp4'
    assert library.roots['emotion']==tmp_path/'materials/emotion_video/selected'
