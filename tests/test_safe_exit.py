from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from video_eeg.experiment import video_runner as module


@pytest.mark.parametrize('reason', ['running', 'rest_exit'])
def test_held_escape_during_shutdown_exports_once(tmp_path, reason):
    runner = object.__new__(module.VideoRunner)
    runner.keyboard = Mock()
    runner.keyboard.getKeys.side_effect = lambda keys, **kw: ['escape'] if 'escape' in keys else ['space']
    runner.message = Mock()
    runner.win = Mock()
    runner.termination_reason = reason
    runner._run_traceback = None
    runner._checkpoint = Mock()
    runner._session_exit_text = Mock(return_value='Exit')
    runner._show_instructions = runner._check_abort
    runner._stop_and_export = Mock(return_value=tmp_path)
    ticks = iter(range(100))
    with patch.object(module.time, 'perf_counter', side_effect=lambda: next(ticks)), patch.object(module, 'core', Mock()):
        runner.run()
    runner._stop_and_export.assert_called_once()
    runner._checkpoint.assert_called_once_with('esc_emergency' if reason == 'running' else reason)
    assert runner._run_traceback is None


def test_regular_text_still_accepts_escape():
    runner = object.__new__(module.VideoRunner)
    runner.message = Mock()
    runner.win = Mock()
    runner.keyboard = Mock()
    runner.keyboard.getKeys.return_value = ['escape']
    with pytest.raises(module.ExperimentAbort):
        runner._show_text('Normal instruction')
