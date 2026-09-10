from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from video_eeg.experiment import video_runner as module
from video_eeg.utils.video_library import VideoAsset


@pytest.mark.parametrize("keys,skipped", [(["space"], True), ([], False)])
def test_short_rest_space_or_timeout_preserves_completion(keys, skipped):
    runner = object.__new__(module.VideoRunner)
    runner.protocol = SimpleNamespace(iti_sec=2.0)
    runner.manager = Mock()
    callbacks = []
    runner.win = Mock()
    runner.win.callOnFlip.side_effect = lambda fn, **kw: callbacks.append((fn, kw))

    def flip():
        for fn, kw in callbacks:
            fn(**kw)
        callbacks.clear()

    runner.win.flip.side_effect = flip
    runner.keyboard = Mock()
    runner.keyboard.getKeys.return_value = keys
    runner.message = Mock()
    runner.state = SimpleNamespace(
        video_attempts=[{"completed": True}], completed_net_video_duration_sec=60.0,
    )
    runner._write_trial_log = Mock()
    runner._checkpoint = Mock()
    record = SimpleNamespace(break_skipped=False)
    ticks = iter([0.0, 0.1, 0.2] if skipped else [0.0, 0.1, 0.2, 2.1, 2.2])
    with patch.object(module.time, "perf_counter", side_effect=lambda: next(ticks)), patch.object(module, "core", Mock()):
        runner._run_post_video_rest(trial_idx=1, asset=VideoAsset("v1", "v1.mp4"), record=record)
    assert record.break_skipped is skipped
    assert runner.state.video_attempts[-1]["break_skipped"] is skipped
    assert runner.state.video_attempts[-1]["completed"] is True
    assert runner.state.completed_net_video_duration_sec == 60.0
    runner.manager.break_start.assert_called_once()
    runner.manager.break_end.assert_called_once()
    runner._write_trial_log.assert_called_once()
    runner._checkpoint.assert_called_once_with("post_video_rest_skipped" if skipped else "post_video_rest_completed")


def test_short_rest_escape_takes_priority_over_space():
    runner = object.__new__(module.VideoRunner)
    runner.protocol = SimpleNamespace(iti_sec=2.0)
    runner.manager = Mock()
    runner.win = Mock()
    runner.message = Mock()
    runner.keyboard = Mock()
    runner.keyboard.getKeys.return_value = ["space", "escape"]
    with patch.object(module.time, "perf_counter", side_effect=[0.0, 0.1]):
        with pytest.raises(module.ExperimentAbort):
            runner._run_post_video_rest(trial_idx=1, asset=VideoAsset("v1", "v1.mp4"), record=SimpleNamespace())
