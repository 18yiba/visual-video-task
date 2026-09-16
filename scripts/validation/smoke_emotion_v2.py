"""Real-window v2 behavioral and continuous EEG checks, using synthetic media."""
import copy
import json
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from video_eeg.experiment.emotion_v2_runner import EmotionV2Runner,base
from video_eeg.utils.emotion_protocol import prepare

def main():
    base._load_psychopy()
    config=base.load_config(base.CONFIG_DIR/'video_emotion_demo_config.yaml')
    config['_project_dir']=str(base.PROJECT_ROOT)
    config['protocol'].update(fixation_sec=.1,post_video_rest_seconds=.1,random_seed=20260912)
    config['storage']['records_dir']='data/video_emotion_eeg_runs/software_smoke_v2'
    config['explicit_run_seed']=20260912
    library,playlist=prepare(config,True)
    subject='AUTO_V2_'+str(time.time_ns());results=[]
    win=base.visual.Window(size=(1100,800),fullscr=False,units='height',color='black')
    class Keyboard:
        def __init__(self,interrupt):self.interrupt=interrupt;self.fired=False;self.runner=None;self.shots=set()
        def clearEvents(self):pass
        def getKeys(self,keys,**kw):
            if keys==['space']:return ['space']
            if keys==['escape','f','j']: # Also handles binary pages; distinguish event times.
                events=self.runner._event_times
                stage='fatigue' if 'FATIGUE_ONSET' in events else 'liking' if 'LIKING_ONSET' in events else 'rest'
            elif '5' in keys:stage='fatigue' if 'FATIGUE_ONSET' in self.runner._event_times else 'arousal' if 'AROUSAL_RATING_ONSET' in self.runner._event_times else 'valence'
            elif 'a' in keys:stage='alarm'
            elif keys==['escape','s'] and self.interrupt=='skip' and not self.fired:
                self.fired=True;return ['s']
            else:return []
            if self.interrupt==stage and not self.fired:
                self.fired=True;return ['escape']
            if stage not in self.shots:
                self.shots.add(stage)
                win.getMovieFrame(buffer='front');win.saveMovieFrames(str(self.runner.progress_dir/(stage+'.png')))
            return ['1' if stage=='alarm' else '5' if stage=='fatigue' else '7' if stage=='valence' else '4' if stage=='arousal' else 'f']
    try:
        for case in ('complete','liking','alarm','fatigue','valence','arousal','skip'):
            attempts=(False,True) if case not in ('complete','skip') else (False,)
            initial_schedule=None
            for resume in attempts:
                cfg=copy.deepcopy(config);cfg['subject_id']=subject+'_'+case
                kb=Keyboard(None if resume or case=='complete' else case)
                r=EmotionV2Runner(win=win,keyboard=kb,config=cfg,protocol=base.VideoExperimentConfig.from_config(cfg),
                    project_dir=base.PROJECT_ROOT,playlist=playlist,library=library)
                kb.runner=r
                if initial_schedule is None:initial_schedule=copy.deepcopy(r.state.attention_schedule)
                else:assert initial_schedule==r.state.attention_schedule
                r.run();assert r.termination_reason!='python_exception',r._run_traceback
                state=r.state
                path=r.manager.session_dir/r.manager.recorder.events_filename
                events=json.loads(path.read_text(encoding='utf-8'));events=events.get('events',[]) if isinstance(events,dict) else events
                assert np.load(r.manager.session_dir/r.manager.eeg_filename,mmap_mode='r').shape[1]>0
                if case in ('complete','skip') or resume:
                    assert state.session_completed and len(state.completed_video_ids)==4
                    assert state.completed_attention_count==1
                    rated=[a['emotion_rating'] for a in state.video_attempts if a.get('emotion_rating',{}).get('completed')]
                    assert len(rated)==3 and all(x['valence_rating']==7 and x['arousal_rating']==4 and x['rating_scale_max']==7 for x in rated)
                    ordinary=[a['ordinary_behavior'] for a in state.video_attempts if a.get('ordinary_behavior',{}).get('completed')]
                    assert len(ordinary)==1 and ordinary[0]['liked']==0 and ordinary[0]['fatigue_rating']==5 and ordinary[0]['correct']
                    assert ordinary[0]['fatigue_scale_max']==5 and 'fatigued' not in ordinary[0]
                    names=[e['name'] for e in events]
                    if 'ALARM_RESPONSE' in names:assert names[names.index('ALARM_RESPONSE')+1]=='FATIGUE_ONSET'
                    for log in ('fatigue_log.csv','video_question_log.csv','video_liking_log.csv','emotion_rating_log.csv'):
                        assert (r.progress_dir/log).is_file()
                else:
                    assert kb.fired and not state.session_completed
                    assert state.queue_video_ids
                results.append(dict(case=case,resume=resume,completed=state.session_completed,events=len(events),path=str(r.progress_dir)))
                print(json.dumps(results[-1]),flush=True)
    finally:win.close()
    out=base.PROJECT_ROOT/'logs';out.mkdir(exist_ok=True)
    (out/'emotion_v2_smoke.json').write_text(json.dumps({'status':'PASS','cases':results},indent=2),encoding='utf-8')
    print('EMOTION V2 SMOKE PASS',flush=True)
    base.core.quit()

if __name__=='__main__':main()
