"""Real PsychoPy window + dummy EEG: complete ratings and resume all three stages.

No researcher or participant files are reused. Output is an AUTO_EMOTION subject.
"""
import argparse
import csv
import json
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from video_eeg.experiment.emotion_runner import EmotionVideoRunner, base
from video_eeg.utils.emotion_protocol import prepare, EmotionLibrary
from video_eeg.utils.video_library import VideoAsset

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-materials',action='store_true',help='Exercise three existing eMotions clips with original sound')
    args=parser.parse_args()
    base._load_psychopy()
    config=base.load_config(base.CONFIG_DIR/'video_emotion_demo_config.yaml')
    config['_project_dir']=str(base.PROJECT_ROOT)
    config['protocol'].update(fixation_sec=.1,post_video_rest_seconds=.15,random_seed=20260912)
    config['storage']['records_dir']='data/video_emotion_eeg_runs/software_smoke'
    config['explicit_run_seed']=20260912
    library,playlist=prepare(config,True)
    if args.real_materials:
        formal=dict(config); formal['session_id']=1
        library,all_assets=prepare(formal,False)
        playlist=[]
        for label in ('positive','neutral','negative'):
            playlist.append(min((a for a in all_assets if library.rows[a.asset_id]['three_class_label']==label),key=lambda a:a.duration_sec))
        library.rows={a.asset_id:library.rows[a.asset_id] for a in playlist}
        config['session_manifest_hash']=formal['session_manifest_hash']+'-smoke-three'
    output=base.PROJECT_ROOT/config['storage']['records_dir']/f'AUTO_EMOTION_{time.time_ns()}'
    output.mkdir(parents=True)
    results=[]
    win=base.visual.Window(size=(1100,800),fullscr=False,units='height',color='black')
    class Keyboard:
        def __init__(self,interrupt=None):
            self.runner=None; self.interrupt=interrupt; self.fired=False; self.screens=set()
        def clearEvents(self):
            pass
        def getKeys(self,keys,**kwargs):
            if keys==['space']:
                return ['space']
            if self.interrupt in ('video','skip') and keys==['escape','s'] and not self.fired:
                self.fired=True; return ['s' if self.interrupt=='skip' else 'escape']
            if keys==['escape','f','j']:
                return ['f']
            if '9' in keys:
                times=self.runner._event_times
                page='arousal' if 'AROUSAL_RATING_ONSET' in times else 'valence'
                if page not in self.screens:
                    win.getMovieFrame(buffer='front')
                    win.saveMovieFrames(str(output/f'{self.interrupt or "complete"}_{page}.png'))
                    self.screens.add(page)
                if self.interrupt==page and not self.fired:
                    self.fired=True; return ['escape']
                return ['6' if page=='valence' else '4']
            return []
    def run_case(case,assets,lib,interrupt=None,resume=False):
        cfg=dict(config);cfg['subject_id']=output.name+'_'+case
        kb=Keyboard(interrupt)
        runner=EmotionVideoRunner(win=win,keyboard=kb,config=cfg,
            protocol=base.VideoExperimentConfig.from_config(cfg),project_dir=base.PROJECT_ROOT,playlist=assets,library=lib)
        kb.runner=runner
        if case=='complete':
            runner.state.next_rest_threshold_min=.01  # Exercise the normal rest page without waiting 30 minutes.
        runner.run()
        events=json.loads((runner.manager.session_dir/runner.manager.recorder.events_filename).read_text(encoding='utf-8'))
        if isinstance(events,dict):
            events=events['events']
        eeg=np.load(runner.manager.session_dir/runner.manager.eeg_filename,mmap_mode='r')
        assert eeg.shape[1]>0
        assert events[0]['name']=='session_start' and events[-1]['name']=='session_end'
        assert all(e['sample_index'] is not None for e in events)
        state=runner.state
        ratings=[a['emotion_rating'] for a in state.video_attempts if 'emotion_rating' in a]
        if interrupt and interrupt!='skip':
            assert kb.fired and not state.session_completed
            assert not state.completed_video_ids and state.queue_video_ids[0]==assets[0].asset_id
            assert ratings and not ratings[-1]['completed']
            if interrupt=='arousal':
                assert ratings[-1]['valence_rating']==6 and ratings[-1]['arousal_rating'] is None
        else:
            assert state.session_completed and len(state.completed_video_ids)==len(assets)
            completed=[r for r in ratings if r['completed']]
            assert len(completed)==sum(lib.rows[a.asset_id]['trial_type']=='emotion' for a in assets)
            assert all(r['valence_rating']==6 and r['arousal_rating']==4 for r in completed)
            expected=['EMOTION_VIDEO_ONSET','EMOTION_VIDEO_OFFSET','VALENCE_RATING_ONSET','VALENCE_RATING_RESPONSE','AROUSAL_RATING_ONSET','AROUSAL_RATING_RESPONSE','SHORT_REST_ONSET','SHORT_REST_OFFSET']
            for r in completed:
                trial=[e for e in events if e['payload'].get('video_id')==r['video_id'] and e['payload'].get('attempt_id')==r['attempt_id'] and e['name'] in expected]
                assert [e['name'] for e in trial]==expected,[e['name'] for e in trial]
                assert trial[4]['sample_index']>trial[2]['sample_index']
            if resume or interrupt=='skip':
                assert len(ratings)==len(completed)+1 and ratings[0]['interrupted']
            if case=='complete':
                assert len(state.rest_events)==1 and state.rest_events[0]['action']=='continue'
            assert abs(state.completed_net_video_duration_sec-sum(r['actual_video_sec'] for r in state.video_attempts))<1e-6
        assert not any('attention' in e['name'] for e in events)
        assert runner.termination_reason!='python_exception',runner._run_traceback
        result=dict(case=case,interrupt=interrupt,resume=resume,completed=state.session_completed,
                    eeg_samples=eeg.shape[1],events=len(events),rating_rows=len(ratings),output=str(runner.manager.session_dir))
        print(json.dumps(result),flush=True);results.append(result)
    try:
        run_case('complete',playlist,library)
        if not args.real_materials:
            asset=next(a for a in playlist if library.rows[a.asset_id]['trial_type']=='emotion')
            single=EmotionLibrary([library.rows[asset.asset_id]],library.roots)
            for stage in ('video','valence','arousal'):
                run_case(stage,[asset],single,stage)
                run_case(stage,[asset],single,resume=True)
            run_case('skip',[asset],single,'skip')
    finally:
        win.close()
    (output/'result.json').write_text(json.dumps(dict(status='PASS',real_materials=args.real_materials,cases=results),indent=2),encoding='utf-8')
    print('EMOTION EEG SMOKE PASS: '+str(output),flush=True)
    base.core.quit()

if __name__=='__main__':
    main()
