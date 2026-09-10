"""One automatic real-window video/MCQ trial with dummy EEG, no physical devices."""
import json
from pathlib import Path
import sys
import time
import argparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_eeg.experiment import ready_question_runner as ready
base = ready.base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--practice', action='store_true', help='Use generated clips in a fresh source checkout')
    args = parser.parse_args()
    base._load_psychopy()
    config = base.load_config(base.CONFIG_DIR / 'video_demo_config.yaml')
    config['_project_dir'] = str(base.PROJECT_ROOT)
    config['subject_id'] = f'AUTO_CHECK_SMOKE_{time.time_ns()}'
    config['storage']['records_dir'] = 'data/video_question_smoke'
    config['protocol'].update(trials_per_session=1, attention_tasks_per_session=1, fixation_sec=0.1, post_video_rest_seconds=0,
                              random_seed=int(time.time()))
    if args.practice:
        config['protocol']['video_library_dir'] = str(base.PROJECT_ROOT / 'stimuli/demo')
        config['protocol']['question_bank_path'] = 'stimuli/demo/question_bank.json'
    bank = ready.load_questions(ready.question_path(config))
    library = ready.ReadyLibrary(base.load_video_library(config), bank)
    asset = next(a for a in library.list_assets() if a.rel_path == ('demo_01.mp4' if args.practice else '0001.mp4'))
    output = base.PROJECT_ROOT / 'data/video_question_smoke' / config['subject_id']
    output.mkdir(parents=True, exist_ok=True)
    win = base.visual.Window(size=(1100, 800), fullscr=False, units='height', color='black')
    class Keyboard:
        captured = False
        def clearEvents(self):
            pass
        def getKeys(self, keys, **kwargs):
            if keys == ['space']:
                win.getMovieFrame(buffer='front')
                win.saveMovieFrames(str(output / 'instruction_screen.png'))
                return ['space']
            if '1' in keys:
                if not self.captured:
                    win.getMovieFrame(buffer='front')
                    win.saveMovieFrames(str(output / 'question_screen.png'))
                    self.captured = True
                return ['1']
            return []
    runner = None
    try:
        runner = ready.QuestionVideoRunner(win=win, keyboard=Keyboard(), config=config,
                    protocol=base.VideoExperimentConfig.from_config(config),
                    project_dir=base.PROJECT_ROOT, playlist=[asset], library=library)
        runner._show_instructions()
        runner._start_eeg({'device': 'dummy', 'smoke_test': True})
        completed = runner._run_trial(1, asset)
        runner.completed = completed
        runner.state.session_completed = completed and runner.state.completed_attention_count == 1
        runner._checkpoint('automated_smoke_complete')
        runner.termination_reason = 'automated_smoke_complete'
        assert completed and len(runner.question_rows) == 1
        assert runner.question_rows[0]['response'] == 'A'
        assert 'question_review_status' in runner.question_rows[0]
        assert asset.asset_id in runner.state.completed_video_ids
        print(json.dumps({'completed': completed, 'video': asset.rel_path,
                          'question_log': str(runner.progress_dir / 'video_question_log.csv'),
                          'screenshot': str(output / 'question_screen.png')}, ensure_ascii=False), flush=True)
    finally:
        if runner and runner.manager:
            runner._stop_and_export()
        win.close()
    base.core.quit()


if __name__ == '__main__':
    main()
