from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

import psychopy_video_experiment as video_module
from acquisition.base import AcquirerMetadata
from protocol.session_recorder import SessionRecorder
from psychopy_video_experiment import (
    VideoExperimentConfig,
    VideoRunner,
    _natural_asset_key,
    load_config,
)
from utils.markers import PROTOCOL_EVENT_CODES
from utils.video_library import VideoAsset


class VideoExperimentConfigTests(unittest.TestCase):
    def test_required_video_defaults(self) -> None:
        parsed = VideoExperimentConfig.from_config({})

        self.assertEqual(parsed.video_sec, 60.0)
        self.assertEqual(parsed.eyes_open_baseline_sec, 60.0)
        self.assertEqual(parsed.eyes_closed_baseline_sec, 60.0)
        self.assertEqual(parsed.playlist_mode, "balanced")
        self.assertFalse(hasattr(parsed, "rating_sec"))

    def test_video_config_is_independent_from_image_fields(self) -> None:
        parsed = VideoExperimentConfig.from_config(
            {
                "task_mode": "image_b",
                "protocol": {
                    "image_present_min_sec": 1.0,
                    "rating_sec": 3.0,
                },
            }
        )

        self.assertEqual(parsed.video_sec, 60.0)
        self.assertEqual(parsed.trials_per_session, 500)

    def test_demo_config_uses_ten_numbered_videos_in_sequence(self) -> None:
        config = load_config(Path("video_demo_config.yaml"))
        parsed = VideoExperimentConfig.from_config(config)
        assets = [
            VideoAsset(str(index), f"{index}.mp4")
            for index in (1, 10, 2, 9, 3, 8, 4, 7, 5, 6)
        ]

        self.assertTrue(config["demo_mode"])
        self.assertTrue(config["hardware_dummy_mode"])
        self.assertEqual(parsed.trials_per_session, 10)
        self.assertEqual(parsed.playlist_mode, "sequential")
        self.assertEqual(
            [asset.rel_path for asset in sorted(assets, key=_natural_asset_key)],
            [f"{index}.mp4" for index in range(1, 11)],
        )


class VideoMarkerTests(unittest.TestCase):
    def test_dual_baseline_markers_are_distinct_external_events(self) -> None:
        expected = {
            "eyes_open_baseline_start": 112,
            "eyes_open_baseline_end": 113,
            "eyes_closed_baseline_start": 114,
            "eyes_closed_baseline_end": 115,
        }

        self.assertEqual(
            {name: PROTOCOL_EVENT_CODES[name] for name in expected},
            expected,
        )
        self.assertEqual(len(set(expected.values())), 4)

    def test_video_markers_keep_existing_codes(self) -> None:
        self.assertEqual(PROTOCOL_EVENT_CODES["video_on"], 132)
        self.assertEqual(PROTOCOL_EVENT_CODES["video_off"], 133)

    def test_baseline_markers_are_dispatched_from_flip_callbacks(self) -> None:
        class Stim:
            text = ""
            height = 0.0
            pos = (0, 0)

            def draw(self) -> None:
                return None

        class Window:
            def __init__(self) -> None:
                self.callbacks: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
                self.in_flip = False

            def callOnFlip(self, fn, *args, **kwargs) -> None:
                self.callbacks.append((fn, args, kwargs))

            def flip(self) -> None:
                pending, self.callbacks = self.callbacks, []
                self.in_flip = True
                try:
                    for fn, args, kwargs in pending:
                        fn(*args, **kwargs)
                finally:
                    self.in_flip = False

        class Manager:
            def __init__(self, window: Window) -> None:
                self.window = window
                self.events: list[str] = []

            def raise_if_background_failed(self) -> None:
                return None

            def emit(self, name: str, **_payload) -> None:
                if not self.window.in_flip:
                    raise AssertionError(f"{name} was not emitted from callOnFlip")
                self.events.append(name)

        window = Window()
        manager = Manager(window)
        runner = object.__new__(VideoRunner)
        runner.win = window
        runner.manager = manager
        runner.protocol = VideoExperimentConfig.from_config(
            {
                "protocol": {
                    "eyes_open_baseline_sec": 0.0,
                    "eyes_closed_baseline_sec": 0.0,
                }
            }
        )
        runner.message = Stim()
        runner.subtitle = Stim()
        runner._phase_started_at = 0.0

        runner._run_baseline_phase(
            symbol="+",
            subtitle="open",
            duration_sec=0.0,
            start_event="eyes_open_baseline_start",
            end_event="eyes_open_baseline_end",
        )
        runner._run_baseline_phase(
            symbol="",
            subtitle="",
            duration_sec=0.0,
            start_event="eyes_closed_baseline_start",
            end_event="eyes_closed_baseline_end",
        )

        self.assertEqual(
            manager.events,
            [
                "baseline_start",
                "eyes_open_baseline_start",
                "eyes_open_baseline_end",
                "eyes_closed_baseline_start",
                "eyes_closed_baseline_end",
                "baseline_end",
            ],
        )

    def test_trial_contains_no_rating_stage_and_video_markers_run_on_flip(self) -> None:
        class Keyboard:
            def getKeys(self, *_args, **_kwargs):
                return []

        class Window:
            def __init__(self) -> None:
                self.callbacks = []
                self.in_flip = False

            def callOnFlip(self, fn, *args, **kwargs) -> None:
                self.callbacks.append((fn, args, kwargs))

            def flip(self) -> None:
                pending, self.callbacks = self.callbacks, []
                self.in_flip = True
                try:
                    for fn, args, kwargs in pending:
                        fn(*args, **kwargs)
                finally:
                    self.in_flip = False

        class Manager:
            session_dir = None

            def __init__(self, window: Window) -> None:
                self.window = window
                self.events: list[str] = []

            def raise_if_background_failed(self) -> None:
                return None

            def _add(self, name: str) -> None:
                if not self.window.in_flip:
                    raise AssertionError(f"{name} was not emitted from callOnFlip")
                self.events.append(name)

            def emit(self, name: str, **_payload) -> None:
                self._add(name)

            def begin_trial(self, **_payload) -> None:
                self._add("trial_start")

            def fixation_on(self, **_payload) -> None:
                self._add("fixation_on")

            def fixation_off(self, **_payload) -> None:
                self._add("fixation_off")

            def blank_on(self, **_payload) -> None:
                self._add("blank_on")

            def blank_off(self, **_payload) -> None:
                self._add("blank_off")

            def iti_on(self, **_payload) -> None:
                self._add("iti_on")

            def iti_off(self, **_payload) -> None:
                self._add("iti_off")

            def end_trial(self, **_payload) -> None:
                self._add("trial_end")

        class Movie:
            isFinished = True

            def __init__(self) -> None:
                self.stop_calls = 0
                self.unload_calls = 0

            def draw(self) -> None:
                return None

            def play(self) -> None:
                return None

            def pause(self) -> None:
                return None

            def stop(self) -> None:
                self.stop_calls += 1

            def unload(self) -> None:
                self.unload_calls += 1

        class Fixation:
            def draw(self) -> None:
                return None

        class Message(Fixation):
            text = ""
            height = 0.0
            pos = (0, 0)

        class Library:
            @staticmethod
            def resolve(_asset: VideoAsset) -> Path:
                return Path("fake.mp4")

        class Core:
            @staticmethod
            def wait(_duration: float) -> None:
                return None

        window = Window()
        manager = Manager(window)
        runner = object.__new__(VideoRunner)
        runner.win = window
        runner.keyboard = Keyboard()
        runner.manager = manager
        runner.config = {"subject_id": "S001", "session_id": 1}
        runner.protocol = VideoExperimentConfig(
            fixation_sec=0.0,
            video_sec=0.001,
            blank_sec=0.0,
            iti_sec=0.0,
            eyes_open_baseline_sec=60.0,
            eyes_closed_baseline_sec=60.0,
            trials_per_session=1,
            random_seed=17,
            playlist_mode="sequential",
        )
        runner.library = Library()
        runner.playlist = [VideoAsset("001", "001_test.mp4")]
        runner.fixation = Fixation()
        runner.message = Message()
        runner.trial_records = []
        runner._phase_started_at = 0.0
        movie = Movie()
        runner._create_movie = lambda _path: movie
        original_core = video_module.core
        video_module.core = Core()
        try:
            runner._run_trial(
                1,
                VideoAsset("001", "001_test.mp4", duration_sec=0.001, category="test"),
            )
        finally:
            video_module.core = original_core

        self.assertIn("video_on", manager.events)
        self.assertIn("video_off", manager.events)
        self.assertFalse(any("rating" in name for name in manager.events))
        self.assertEqual(len(runner.trial_records), 1)
        self.assertEqual(movie.stop_calls, 0)
        self.assertEqual(movie.unload_calls, 1)


class SessionRecorderWindowsExportTests(unittest.TestCase):
    def test_spooled_eeg_is_published_without_hard_links(self) -> None:
        class Acquirer:
            metadata = AcquirerMetadata(name="test", sfreq=100.0, n_channels=2)

            def __init__(self) -> None:
                self.returned = False

            def get_new_samples(self):
                if self.returned:
                    return np.empty((2, 0), dtype=np.float32), np.empty((0,))
                self.returned = True
                samples = np.asarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
                return samples, np.arange(3, dtype=np.float64) / 100.0

        with TemporaryDirectory(dir=Path.cwd() / "tests") as temporary_dir:
            output_dir = Path(temporary_dir)
            recorder = SessionRecorder(
                Acquirer(),
                sfreq=100.0,
                n_channels=2,
            )
            recorder.start_spooling(output_dir)
            recorder.pull()
            recorder.export(output_dir, metadata={"task_mode": "video"})

            exported = np.load(output_dir / "continuous_eeg.npy")
            np.testing.assert_array_equal(
                exported,
                np.asarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32),
            )
            self.assertFalse((output_dir / ".continuous_eeg.f32.tmp").exists())
            self.assertFalse(any(output_dir.glob("*.writing")))


if __name__ == "__main__":
    unittest.main()
