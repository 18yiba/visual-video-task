"""Formal-only Qt UI checks; no EEG device started."""
import sys
from pathlib import Path
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import launch_emotion_v3 as front

def main():
    from video_eeg.utils import material_settings
    material_settings.check=lambda config:None  # Argument/UI check, no formal media required.
    from psychopy.gui import qtgui
    w = front.make_window()
    w.subject.setText('00000002'); w.check_progress()
    w.show(); qtgui.QtWidgets.QApplication.instance().processEvents()
    assert not hasattr(w, 'mode') and w.table.rowCount() == 45
    assert sum(r['videos_total'] for r in w.progress) == 11084
    w.grab().save(str(ROOT / 'logs/v3_frontend.png'))
    launched = []
    w.process = SimpleNamespace(setWorkingDirectory=lambda _: None, start=lambda exe, args: launched.append(args))
    w.connection = {'argument_check_only': True}
    w.subject.setText('00000002')
    w.paradigm.setText('TEST-ARGUMENT-CHECK')
    w.start.click()
    assert len(launched) == 1 and '--real-eeg' in launched[0]
    assert '--demo' not in launched[0] and '--dummy-eeg' not in launched[0]
    w.run_finished(0, None)
    w.scope.setCurrentIndex(1)
    assert sum(r['videos_total'] for r in w.progress) == 3138
    assert all(r['videos_total'] == r['emotion_total'] for r in w.progress)
    w.connection = {'argument_check_only': True}
    w.start.click()
    assert '--emotion-only' in launched[-1]
    w.run_finished(0, None)
    w.stage.setCurrentIndex(1)
    assert not w.detect.isEnabled()
    w.close()
    print('Formal-only frontend PASS; no hardware tested')

if __name__ == '__main__':
    main()
