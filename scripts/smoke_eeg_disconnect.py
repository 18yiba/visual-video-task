"""Real-window fault injection and resume, synthetic videos and simulated EEG only."""
import copy,json,sys,time
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from video_eeg.experiment.emotion_v2_runner import EmotionV2Runner,base
from video_eeg.utils.emotion_protocol import prepare


def main():
    base._load_psychopy()
    config=base.load_config(base.CONFIG_DIR/'video_emotion_demo_config.yaml')
    config['_project_dir']=str(base.PROJECT_ROOT)
    config['protocol'].update(fixation_sec=.1,post_video_rest_seconds=.1)
    config['device'].update(eeg_no_sample_timeout_sec=.4,eeg_startup_timeout_sec=3.)
    config['storage']['records_dir']='data/video_emotion_eeg_runs/disconnect_smoke'
    config['explicit_run_seed']=20260912
    library,playlist=prepare(config,True)
    win=base.visual.Window(size=(1100,800),fullscr=False,units='height',color='black')
    results=[];subject='AUTO_FAULT_'+str(time.time_ns())
    class Keyboard:
        def __init__(self,target):self.target=target;self.runner=None
        def clearEvents(self):pass
        def getKeys(self,keys,**kwargs):
            if keys==['space']:return ['space']
            events=getattr(self.runner,'_event_times',{})
            if self.target and self.target in events:return []
            if '7' in keys:return ['7']
            if 'a' in keys:return ['1']
            if keys==['escape','f','j']:return ['f']
            return []
    class Runner(EmotionV2Runner):
        fault_target=None
        def _start_eeg(self,connection):
            super()._start_eeg(connection)
            original=self.manager._acquirer.get_new_samples
            def read():
                if self.fault_target and self.fault_target in self._event_times:
                    return np.empty((32,0),np.float32),np.empty(0)
                return original()
            self.manager._acquirer.get_new_samples=read
        def _show_text(self,text,**kwargs):
            if text.startswith('EEG采集异常'):
                super()._show_text(text,wait_for_key=False,duration=0,allow_abort=False)
                win.getMovieFrame(buffer='front');win.saveMovieFrames(str(self.progress_dir/'eeg_error_screen.png'))
                self.warning_seen=True
            else:super()._show_text(text,**kwargs)
    try:
        for target in ['video_on','FATIGUE_ONSET','AROUSAL_RATING_ONSET','rest_start']:
            cfg=copy.deepcopy(config);cfg['subject_id']=subject+'_'+target
            resume_config=copy.deepcopy(cfg)
            kb=Keyboard(target)
            r=Runner(win=win,keyboard=kb,config=cfg,protocol=base.VideoExperimentConfig.from_config(cfg),
                project_dir=base.PROJECT_ROOT,playlist=playlist,library=library)
            r.fault_target=target;kb.runner=r
            if target=='rest_start':r.state.next_rest_threshold_min=0.
            r.run()
            assert r.termination_reason=='eeg_background_error',r._run_traceback
            assert r.warning_seen and not r.state.session_completed and r.state.queue_video_ids
            path=r.manager.session_dir
            assert (path/'eeg_error_part_001.json').is_file()
            assert np.load(path/r.manager.eeg_filename).shape[1]>0 or target=='rest_start'
            before=copy.deepcopy(r.state.attention_schedule)
            if target=='video_on':
                assert not r.state.completed_video_ids
                assert r.state.video_attempts[-1]['abort_reason']=='eeg_background_error'
                cfg=resume_config
                cfg['device']['eeg_no_sample_timeout_sec']=5.
                kb2=Keyboard(None)
                resumed=Runner(win=win,keyboard=kb2,config=cfg,protocol=base.VideoExperimentConfig.from_config(cfg),
                    project_dir=base.PROJECT_ROOT,playlist=playlist,library=library)
                kb2.runner=resumed;resumed.run()
                assert resumed.state.session_completed and before==resumed.state.attention_schedule
            results.append(dict(phase=target,result='PASS',path=str(path)))
            print(json.dumps(results[-1]),flush=True)
    finally:win.close()
    (base.PROJECT_ROOT/'logs/eeg_disconnect_smoke.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print('EEG DISCONNECT SMOKE PASS',flush=True)
    base.core.quit()

if __name__=='__main__':main()
