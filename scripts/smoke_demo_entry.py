"""Exercise the real Demo entry/timeline automatically with dummy EEG only."""
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video_eeg.experiment import video_runner as base


def main():
    original_loader = base._load_psychopy
    subject = f'AUTO_DEMO_ENTRY_{time.time_ns()}'

    class Keyboard:
        def clearEvents(self):
            pass

        def getKeys(self, keys, **kwargs):
            if '1' in keys:
                return ['1']
            if 'space' in keys:
                return ['space']
            return []

    def load():
        original_loader()
        base.Keyboard = Keyboard

    base._load_psychopy = load
    try:
        try:
            result = base.main(['--demo', '--dummy-eeg', '--no-dialog', '--windowed', '--subject-id', subject])
        except SystemExit as exc:
            # PsychoPy core.quit terminates the normal CLI after export.
            result = exc.code or 0
    finally:
        base._load_psychopy = original_loader
    state_path = next((ROOT / 'data/demo_runs' / subject).rglob('session_state.json'))
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert result == 0
    assert state['session_completed']
    assert len(state['completed_video_ids']) == 10
    assert len(state['completed_attention_ids']) == 3
    assert len(state['attention_attempts']) == 3
    report = dict(subject=subject, videos=10, questions=3, session_completed=True,
                  state_path=str(state_path), real_hardware_used=False)
    (ROOT / 'logs').mkdir(exist_ok=True)
    (ROOT / 'logs/demo_entry_validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
