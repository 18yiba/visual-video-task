"""Real PsychoPy window + dummy EEG: hold Escape during video and shutdown."""
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from video_eeg.experiment import ready_question_runner as ready
base = ready.base


def main():
    base._load_psychopy()
    config = base.load_config(base.CONFIG_DIR / 'video_demo_config.yaml')
    subject = f'AUTO_HELD_ESCAPE_{time.time_ns()}'
    config.update(_project_dir=str(ROOT), subject_id=subject, hardware_dummy_mode=True)
    config['storage']['records_dir'] = 'data/safe_exit_smoke'
    config['protocol'].update(video_library_dir=str(ROOT / 'stimuli/demo'),
        question_bank_path='stimuli/demo/question_bank.json', attention_tasks_per_session=1,
        trials_per_session=1, fixation_sec=0.1, random_seed=int(time.time()))
    bank = ready.load_questions(ready.question_path(config))
    library = ready.ReadyLibrary(base.load_video_library(config), bank)
    asset = next(a for a in library.list_assets() if a.rel_path == 'demo_01.mp4')
    class Keyboard:
        armed = False
        def clearEvents(self): pass
        def getKeys(self, keys, **kwargs):
            if self.armed and 'escape' in keys: return ['escape']
            return ['space'] if 'space' in keys else []
    keyboard = Keyboard()
    win = base.visual.Window(size=(900, 650), fullscr=False, units='height', color='black')
    runner = ready.QuestionVideoRunner(win=win, keyboard=keyboard, config=config,
        protocol=base.VideoExperimentConfig.from_config(config), project_dir=ROOT,
        playlist=[asset], library=library)
    original_checkpoint = runner._checkpoint
    def checkpoint(status):
        original_checkpoint(status)
        if status == 'video_attempt_started':
            base.core.wait(0.5)
            keyboard.armed = True
    runner._checkpoint = checkpoint
    try:
        runner.run()
        assert runner.termination_reason == 'esc_emergency'
        assert not runner.state.session_completed
        assert not runner.state.completed_video_ids
        assert not runner._run_traceback
        state = json.loads((runner.progress_dir / 'session_state.json').read_text(encoding='utf-8'))
        assert state['queue_video_ids'] == [asset.asset_id]
        outputs = list((ROOT / 'data/safe_exit_smoke' / subject).rglob('continuous_eeg.npy'))
        assert outputs and outputs[0].stat().st_size > 128
        report = dict(subject=subject, termination_reason=runner.termination_reason,
            export_verified=True, resumable_video=asset.asset_id, physical_eeg=False)
        (ROOT / 'logs').mkdir(exist_ok=True)
        (ROOT / 'logs/safe_exit_validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
    finally:
        win.close()


if __name__ == '__main__': main()
