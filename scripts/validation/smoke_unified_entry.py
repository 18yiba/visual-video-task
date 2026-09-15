"""Exercise unified launcher + real PsychoPy Demo without official media/hardware."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(1,str(ROOT/'scripts'))
from video_eeg.experiment import video_runner as base
from launch_experiment import launch

def main():
    p=argparse.ArgumentParser();p.add_argument('--protocol',choices=['legacy17','emotion-v2'],required=True);args=p.parse_args()
    subject='AUTO_LAYOUT_'+str(time.time_ns());original=base._load_psychopy
    class Keyboard:
        def clearEvents(self):pass
        def getKeys(self,keys,**kw):
            if 'space' in keys:return ['space']
            if '7' in keys:return ['7']
            if '1' in keys:return ['1']
            if keys==['escape','f','j']:return ['f']
            return []
    def load():
        original();base.Keyboard=Keyboard;base.core.quit=lambda:None
    base._load_psychopy=load
    result=launch(args.protocol,'demo',['--no-dialog','--windowed','--subject-id',subject,'--seed','20260912'])
    assert result==0
    root=ROOT/'data/sourcedata/demo'/args.protocol/subject
    path=next(root.rglob('session_state.json'));state=json.loads(path.read_text(encoding='utf-8'))
    assert state['session_completed']
    assert len(state['completed_video_ids'])==(10 if args.protocol=='legacy17' else 4)
    assert len(state['completed_attention_ids'])==(3 if args.protocol=='legacy17' else 1)
    assert list((ROOT/'data/sourcedata/demo'/args.protocol/subject).rglob('continuous_eeg*.npy'))
    assert list((ROOT/'data/sourcedata/demo'/args.protocol/subject).rglob('eeg_health*.jsonl'))
    print(json.dumps(dict(protocol=args.protocol,result='PASS',videos=len(state['completed_video_ids']),questions=len(state['completed_attention_ids']),state=str(path)),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
