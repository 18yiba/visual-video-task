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
        return '1' if prefix=='alarm' else 'j'
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
        assert row['liked']==row['fatigued']==1 and row['correct']

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
    assert r._choice_page(row,'fatigue','state',['F no','J yes'],['f','j'],'FATIGUE')=='j'
    assert r.keyboard.getKeys.call_count==2 and row['fatigue_key']=='j'
