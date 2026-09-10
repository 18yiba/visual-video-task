"""Exercise the canonical formal Session 34 entry, then save with dummy EEG only."""
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video_eeg.experiment import video_runner as base
from video_eeg.experiment.ready_question_runner import QuestionVideoRunner


def main():
    subject = f'AUTO_FORMAL34_{time.time_ns()}'
    original_loader = base._load_psychopy
    original_checkpoint = QuestionVideoRunner._checkpoint
    original_init = QuestionVideoRunner.__init__
    class Keyboard:
        armed = False
        def clearEvents(self): pass
        def getKeys(self, keys, **kwargs):
            if self.armed and 'escape' in keys: return ['escape']
            return ['space'] if 'space' in keys else []
    keyboard = Keyboard()
    def load():
        original_loader()
        base.Keyboard = lambda: keyboard
    def checkpoint(self, status):
        original_checkpoint(self, status)
        if status == 'video_attempt_started':
            base.core.wait(0.5)
            keyboard.armed = True
    def init(self, *args, **kwargs):
        # Only this test harness substitutes acquisition after formal configuration
        # and material validation. The production CLI still rejects --dummy-eeg.
        kwargs['config']['hardware_dummy_mode'] = True
        original_init(self, *args, **kwargs)
    base._load_psychopy = load
    QuestionVideoRunner._checkpoint = checkpoint
    QuestionVideoRunner.__init__ = init
    try:
        try:
            result = base.main(['--real-eeg', '--no-dialog', '--windowed', '--session', '34', '--subject-id', subject])
        except SystemExit as exc:
            result = exc.code or 0
    finally:
        base._load_psychopy = original_loader
        QuestionVideoRunner._checkpoint = original_checkpoint
        QuestionVideoRunner.__init__ = original_init
    assert result == 0
    folder = ROOT/'data/video_question_complete_runs/protocol_34sessions'/subject/'session_34'
    state = json.loads((folder/'session_state.json').read_text(encoding='utf-8'))
    assert state['session_id'] == 34
    assert len(state['queue_video_ids']) == 234
    assert len(state['attention_schedule']) == 18
    assert len({q['video_id'] for q in state['attention_schedule']}) == 18
    assert not state['session_completed'] and not state['completed_video_ids']
    assert list(folder.rglob('continuous_eeg.npy'))
    assert not list(folder.rglob('crash_report.txt'))
    report = dict(subject=subject, session=34, videos=234, checks=18,
                  safe_exit_and_export_verified=True, physical_eeg=False)
    (ROOT/'logs').mkdir(exist_ok=True)
    (ROOT/'logs/formal34_validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__': main()
