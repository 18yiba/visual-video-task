import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from video_eeg.experiment.emotion_v2_runner import EmotionV2Runner, alarm_schedule, base
from video_eeg.utils.emotion_protocol import presentation_order,parse_rating
from video_eeg.experiment.ready_question_runner import load_questions
from video_eeg.utils.session_protocol import SessionState

ROOT=Path(__file__).resolve().parents[1]

def test_all_sessions_have_nine_ordinary_bound_checks_near_ten_minute_targets():
    rows=list(csv.DictReader((ROOT/'video_eeg/config/session_manifest_emotion_v1.csv').open(encoding='utf-8-sig')))
    bank=load_questions(ROOT/'video_eeg/config/complete_questions_20260908/question_bank.json')
    gaps=[]
    for sid in range(1,46):
        group=[r for r in rows if int(r['session_id'])==sid];lookup={r['video_id']:r for r in group}
        questions={r['video_path']:bank[Path(r['video_path']).name] for r in group if r['trial_type']=='ordinary' and Path(r['video_path']).name in bank}
        for seed in (20260912,123,9876):
            order=presentation_order(group,seed,'AUDIT',sid)
            schedule=alarm_schedule(lookup,order,questions,9,600,seed)
            assert schedule==alarm_schedule(lookup,order,questions,9,600,seed)
            assert len({r['video_id'] for r in schedule})==9
            assert all(lookup[r['video_id']]['trial_type']=='ordinary' for r in schedule)
            assert max(abs(r['target_net_sec']-r['planned_trigger_net_sec']) for r in schedule)<120
            times=[0]+[r['planned_trigger_net_sec'] for r in schedule]
            gaps.extend(b-a for a,b in zip(times,times[1:]))
    assert min(gaps)>420 and max(gaps)<780

@pytest.mark.parametrize('key,answer',[('7',7),('num_7',7),('8',None),('9',None),('num_9',None),('f',None)])
def test_seven_point_boundaries(key,answer):assert parse_rating(key,7)==answer

@pytest.mark.parametrize('interrupted',[None,'liking','alarm','fatigue'])
def test_ordinary_transaction_and_immediate_fatigue(monkeypatch,interrupted):
    r=object.__new__(EmotionV2Runner)
    r.library=SimpleNamespace(rows={'v':{'trial_type':'ordinary'}})
    r.state=SessionState(subject_id='TEST',session_id=1,manifest_version='test',manifest_hash='test',video_ids=['v'],queue_video_ids=['v'])
    r.state.video_attempts=[{'video_id':'v','completed':False}]
    r.state.attention_schedule=[dict(video_id='v',attention_id=1,target_net_sec=600,planned_trigger_net_sec=599)]
    r.questions={'original/a.mp4':dict(question='Q',answer='A',options=dict(A='A',B='B',C='C',D='D'))}
    r.question_bank_sha256='sha';r.manager=Mock(session_dir=Path('record'))
    r._checkpoint=Mock();r._write_attention_log=Mock();r._write_trial_log=Mock()
    phases=[]
    def page(row,prefix,*args):
        phases.append(prefix)
        if interrupted==prefix:raise base.ExperimentAbort()
        return '1' if prefix=='alarm' else '5' if prefix=='fatigue' else 'j'
    r._choice_page=page
    monkeypatch.setattr(base.VideoRunner,'_run_post_video_rest',lambda *a,**k:phases.append('rest'))
    invoke=lambda:r._run_post_video_rest(trial_idx=1,asset=SimpleNamespace(asset_id='v',rel_path='original/a.mp4'),record=SimpleNamespace(attempt_id=1,eeg_part=1))
    if interrupted:
        with pytest.raises(base.ExperimentAbort):invoke()
        assert r.state.queue_video_ids==['v'] and not r.state.completed_video_ids and not r.state.completed_attention_ids
        assert not r.state.video_attempts[-1]['completed']
        assert r.state.video_attempts[-1]['ordinary_behavior']['interrupted']
    else:
        invoke();assert phases==['liking','alarm','fatigue','rest']
        assert r.state.completed_video_ids==['v'] and r.state.completed_attention_ids==[1]
        assert not r.state.queue_video_ids
        row=r.state.video_attempts[-1]['ordinary_behavior']
        assert row['liked']==1 and row['fatigue_rating']==5 and row['correct']
        assert row['fatigue_scale_min']==1 and row['fatigue_scale_max']==5
        assert 'fatigued' not in row

def test_binary_page_requires_release_before_accepting_next_key(monkeypatch):
    r=object.__new__(EmotionV2Runner);r._clear_keyboard=Mock();r._checkpoint=Mock()
    r.message=Mock();r._event_times={};r._require_manager=Mock()
    def emit(name,**kw):r._event_times[name]=dict(monotonic_sec=1.,timestamp_unix_sec=2.,sample_index=3,relative_time_sec=0.)
    r.manager=SimpleNamespace(emit=emit)
    r.win=SimpleNamespace(callOnFlip=lambda f,*a,**kw:f(*a,**kw),flip=lambda:None)
    r.keyboard=Mock()
    r.keyboard.getState.side_effect=[[True,False],[False,False]]
    r.keyboard.getKeys.side_effect=[['f'],['j']]
    monkeypatch.setattr(base,'core',SimpleNamespace(wait=lambda _:None))
    row={}
    assert r._choice_page(row,'liking','state',['F no','J yes'],['f','j'],'LIKING')=='j'
    assert r.keyboard.getKeys.call_count==2 and row['liking_key']=='j'

@pytest.mark.parametrize('answer',['1','5','num_5'])
def test_fatigue_rejects_binary_and_out_of_range_keys_and_waits_for_release(monkeypatch,answer):
    r=object.__new__(EmotionV2Runner);r._clear_keyboard=Mock();r._checkpoint=Mock()
    r.message=Mock();r._event_times={};r._require_manager=Mock();events=[]
    def emit(name,**kw):
        events.append((name,kw));r._event_times[name]=dict(monotonic_sec=1.,timestamp_unix_sec=2.,sample_index=3)
    r.manager=SimpleNamespace(emit=emit)
    r.win=SimpleNamespace(callOnFlip=lambda f,*a,**kw:f(*a,**kw),flip=lambda:None)
    r.keyboard=Mock();r.keyboard.getState.side_effect=[[True],[False]]
    r.keyboard.getKeys.side_effect=[['1'],['f','j','0','6','7','8','9','num_6','num_7'],[answer]]
    monkeypatch.setattr(base,'core',SimpleNamespace(wait=lambda _:None))
    row={};keys=list('12345')+[f'num_{i}' for i in range(1,6)]
    assert r._choice_page(row,'fatigue','Q',['anchors'],keys,'FATIGUE')==answer
    assert r.keyboard.getKeys.call_count==3
    assert row['fatigue_rating']==parse_rating(answer,5)
    assert events[-1][1]['fatigue_rating']==parse_rating(answer,5)
    assert events[0][1]['fatigue_scale_max']==5

def test_saved_binary_session_keeps_original_contract_but_new_session_uses_five(tmp_path):
    import hashlib,json
    from video_eeg.experiment.emotion_v2_runner import fatigue_contract_hash,session_fatigue_scale
    from video_eeg.utils.session_protocol import save_state_atomic
    old=dict(version='emotion-v2',scale=7,interval=600.0,
        liking={'f':'不喜欢','j':'喜欢'},fatigue={'f':'未感到明显的精神疲劳','j':'已感到明显的精神疲劳'},fatigue_wording='请判断您此刻的精神状态。')
    digest='materials:'+hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()
    assert fatigue_contract_hash('materials',600,2)==digest
    assert fatigue_contract_hash('materials',600,7)=='materials:81a80cbd8d2ded7f39db148c0c3e9ff5208f942ac68e1cbcf6d94177bee4fc46'
    cfg=dict(storage={'records_dir':str(tmp_path)},subject_id='S',session_id=1,session_manifest_hash='materials')
    proto=SimpleNamespace(random_seed=17)
    assert session_fatigue_scale(cfg,proto,600)==5
    state=SessionState(subject_id='S',session_id=1,manifest_version='test',manifest_hash=digest,video_ids=['v'],queue_video_ids=['v'])
    path=tmp_path/'S/session_01/session_state.json';path.parent.mkdir(parents=True)
    save_state_atomic(path,state);before=path.read_bytes()
    assert session_fatigue_scale(cfg,proto,600)==2 and path.read_bytes()==before
    assert session_fatigue_scale({**cfg,'session_id':2},proto,600)==5
    state.manifest_hash=fatigue_contract_hash('materials',600,7);save_state_atomic(path,state)
    assert session_fatigue_scale(cfg,proto,600)==7
    state.manifest_hash=fatigue_contract_hash('materials',600,5);save_state_atomic(path,state)
    assert session_fatigue_scale(cfg,proto,600)==5

@pytest.mark.parametrize('old_scale',[2,7])
def test_binary_session_constructor_resume_preserves_answers_and_snapshot(tmp_path,monkeypatch,old_scale):
    import copy
    from video_eeg.experiment.emotion_v2_runner import fatigue_contract_hash
    from video_eeg.utils.session_protocol import save_state_atomic
    from video_eeg.utils.video_library import VideoAsset
    monkeypatch.setattr(base,'visual',SimpleNamespace(TextStim=Mock()))
    monkeypatch.setattr(base,'event',None)
    cfg=base.load_config(ROOT/'video_eeg/config/video_emotion_demo_config.yaml')
    cfg.update(_project_dir=str(tmp_path),practice_materials=True,session_manifest_hash='materials',subject_id='OLD')
    cfg['storage']['records_dir']=str(tmp_path)
    proto=base.VideoExperimentConfig.from_config(cfg)
    asset=VideoAsset('p','practice/practice_0.mp4',5.)
    library=SimpleNamespace(rows={'p':dict(video_id='p',video_path=asset.rel_path,trial_type='ordinary',video_duration_sec=5.,three_class_label='')})
    def make():return EmotionV2Runner(win=Mock(),keyboard=Mock(),config=copy.deepcopy(cfg),protocol=proto,project_dir=tmp_path,playlist=[asset],library=library)
    original=make()
    original.state.manifest_hash=fatigue_contract_hash('materials',original.interval_sec,old_scale)
    original.state.video_attempts=[dict(video_id='p',completed=False,ordinary_behavior=(dict(fatigued=1,fatigue_key='j',completed=False) if old_scale==2 else dict(fatigue_rating=7,fatigue_key='7',fatigue_scale_max=7,completed=False)))]
    save_state_atomic(original.state_path,original.state)
    answers=copy.deepcopy(original.state.video_attempts);schedule=copy.deepcopy(original.state.attention_schedule)
    snapshot=(original.progress_dir/'question_bank_snapshot.json').read_bytes()
    resumed=make()
    assert resumed.fatigue_scale_max==old_scale
    assert resumed.state.video_attempts==answers and resumed.state.attention_schedule==schedule
    assert resumed.state.manifest_hash==original.state.manifest_hash
    assert (resumed.progress_dir/'question_bank_snapshot.json').read_bytes()==snapshot
    cfg['subject_id']='NEW'
    new=make()
    assert new.fatigue_scale_max==5
    new.state.manifest_hash='unrecognized-protocol';save_state_atomic(new.state_path,new.state)
    with pytest.raises(RuntimeError,match='different session manifest'):make()
