from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

import video_eeg.experiment.video_runner as video_module
import video_eeg.utils.video_library as video_library_module
from video_eeg.devices.base import AcquirerMetadata
from video_eeg.storage.session_recorder import SessionRecorder
from video_eeg.experiment.video_runner import (
    VideoExperimentConfig,
    VideoRunner,
    _natural_asset_key,
    attention_effective_reaction_time,
    load_config,
)
from video_eeg.utils.markers import PROTOCOL_EVENT_CODES
from video_eeg.utils.video_library import VideoAsset, VideoLibrary
from video_eeg.utils.video_library import build_fast_candidate_playlist, build_fast_valid_playlist, duration_status


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

    def test_demo_config_uses_ten_random_nonrepeating_videos(self) -> None:
        config = load_config(Path("video_eeg/config/video_demo_config.yaml"))
        parsed = VideoExperimentConfig.from_config(config)
        assets = [
            VideoAsset(str(index), f"{index}.mp4")
            for index in (1, 10, 2, 9, 3, 8, 4, 7, 5, 6)
        ]

        self.assertTrue(config["demo_mode"])
        self.assertTrue(config["hardware_dummy_mode"])
        self.assertEqual(parsed.trials_per_session, 10)
        self.assertEqual(parsed.playlist_mode, "shuffle")
        self.assertEqual(config["protocol"]["video_library_dir"], "../video_materials/formal_v1/videos")
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
        self.assertEqual(PROTOCOL_EVENT_CODES["break_start"], 136)
        self.assertEqual(PROTOCOL_EVENT_CODES["break_end"], 137)

    def test_duration_status_boundaries(self) -> None:
        self.assertEqual(duration_status(4.99), "invalid_short")
        self.assertEqual(duration_status(5.0), "valid")
        self.assertEqual(duration_status(60.0), "valid")
        self.assertEqual(duration_status(60.01), "invalid_long")

    def test_attention_f_response_records_index_and_returns_to_flow(self) -> None:
        class Stim:
            def __init__(self, _win=None, **kwargs):
                self.pos = kwargs.get("pos", (0, 0))
                self.text = kwargs.get("text", "")
                self.height = kwargs.get("height", 0.0)

            def draw(self) -> None:
                return None

        class Visual:
            Rect = Stim
            TextStim = Stim

        class Window:
            def callOnFlip(self, callback, *args, **kwargs) -> None:
                callback(*args, **kwargs)

            def flip(self) -> None:
                return None

        class Keyboard:
            def getKeys(self, *_args, **_kwargs):
                return ["f"]

        class Manager:
            def __init__(self) -> None:
                self.events: list[tuple[str, dict]] = []

            def raise_if_background_failed(self) -> None:
                return None

            def emit(self, name: str, **payload) -> None:
                self.events.append((name, payload))

        class State:
            completed_net_video_duration_sec = 123.0
            attention_attempts: list[dict] = []
            completed_attention_ids: list[int] = []

        runner = object.__new__(VideoRunner)
        runner.win = Window()
        runner.keyboard = Keyboard()
        runner.manager = Manager()
        runner.config = {"subject_id": "P0", "session_id": 1}
        runner.state = State()
        runner.attention_records = []
        runner.message = Stim()
        runner.subtitle = Stim()
        runner.mouse = None
        runner._clear_keyboard = lambda: None
        runner._checkpoint = lambda _reason: None
        runner._write_attention_log = lambda: None
        item = {
            "attention_id": 1,
            "scheduled_net_time_sec": 120.0,
            "after_video_number": 3,
            "question_text": "判断：46 - 23 = 26 是否正确？",
            "operator": "-",
            "operand_a": 46,
            "operand_b": 23,
            "true_result": 23,
            "displayed_result": 26,
            "statement_truth": False,
        }
        original_visual = video_module.visual
        video_module.visual = Visual()
        try:
            self.assertTrue(runner._run_attention_task(schedule_item=item))
        finally:
            video_module.visual = original_visual

        self.assertEqual(runner.attention_records[0].attention_idx, 1)
        self.assertEqual(runner.attention_records[0].response_key, "F")
        self.assertTrue(runner.attention_records[0].response_correct)
        self.assertEqual(runner.state.completed_attention_ids, [1])
        self.assertEqual([name for name, _ in runner.manager.events], ["attention_task_on", "attention_response"])

    def test_attention_space_rest_ignores_f_and_excludes_rest_from_rt(self) -> None:
        class Stim:
            def __init__(self, _win=None, **kwargs):
                self.pos = kwargs.get("pos", (0, 0))
                self.text = kwargs.get("text", "")
                self.height = kwargs.get("height", 0.0)

            def draw(self) -> None:
                return None

        class Visual:
            Rect = Stim
            TextStim = Stim

        class Window:
            def callOnFlip(self, callback, *args, **kwargs) -> None:
                callback(*args, **kwargs)

            def flip(self) -> None:
                return None

        class Keyboard:
            def __init__(self) -> None:
                self.events = [["space"], ["space", "f"], ["j"]]

            def getKeys(self, *_args, **_kwargs):
                return self.events.pop(0) if self.events else []

        class Manager:
            def raise_if_background_failed(self) -> None:
                return None

            def emit(self, *_args, **_kwargs) -> None:
                return None

        class State:
            completed_net_video_duration_sec = 123.0
            attention_attempts: list[dict] = []
            completed_attention_ids: list[int] = []

        runner = object.__new__(VideoRunner)
        runner.win = Window()
        runner.keyboard = Keyboard()
        runner.manager = Manager()
        runner.config = {"subject_id": "P0", "session_id": 1}
        runner.state = State()
        runner.attention_records = []
        runner.message = Stim()
        runner.subtitle = Stim()
        runner.mouse = None
        runner._clear_keyboard = lambda: None
        runner._checkpoint = lambda _reason: None
        runner._write_attention_log = lambda: None
        item = {
            "attention_id": 1,
            "scheduled_net_time_sec": 120.0,
            "question_text": "判断：46 - 23 = 23 是否正确？",
            "operator": "-", "operand_a": 46, "operand_b": 23,
            "true_result": 23, "displayed_result": 23, "statement_truth": True,
        }
        original_visual = video_module.visual
        video_module.visual = Visual()
        try:
            self.assertTrue(runner._run_attention_task(schedule_item=item))
        finally:
            video_module.visual = original_visual

        record = runner.attention_records[0]
        self.assertEqual(record.response_key, "J")
        self.assertTrue(record.response_correct)
        self.assertLessEqual(record.reaction_time_sec, record.dwell_time_sec)

    def test_attention_effective_rt_excludes_all_rest(self) -> None:
        self.assertEqual(attention_effective_reaction_time(129.0, 120.0), 9.0)

    def test_fast_candidate_playlist_randomizes_without_duration_probe(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(1, 21):
                (root / f"{index:03d}.mp4").write_bytes(b"placeholder")

            original_probe = video_library_module.probe_video_duration

            def fail_probe(_path: Path) -> tuple[float | None, str]:
                raise AssertionError("candidate playlist must not probe durations")

            video_library_module.probe_video_duration = fail_probe
            try:
                playlist = build_fast_candidate_playlist(
                    VideoLibrary(root=root, mode="local", default_duration_sec=60.0),
                    trials_per_session=10,
                    random_seed=42,
                )
            finally:
                video_library_module.probe_video_duration = original_probe

            self.assertEqual(len(playlist), 10)
            self.assertEqual(len({asset.rel_path for asset in playlist}), 10)
            self.assertTrue(all(asset.duration_status == "duration_unknown" for asset in playlist))
    def test_fast_demo_playlist_probes_until_enough_valid_videos(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(1, 21):
                (root / f"{index:03d}.mp4").write_bytes(b"placeholder")

            seen: list[str] = []
            original_probe = video_library_module.probe_video_duration

            def fake_probe(path: Path) -> tuple[float | None, str]:
                seen.append(path.name)
                number = int(path.stem)
                if number in {2, 5, 9}:
                    return 2.0, "invalid_short"
                return 12.0, "valid"

            video_library_module.probe_video_duration = fake_probe
            try:
                playlist, probed = build_fast_valid_playlist(
                    VideoLibrary(root=root, mode="local", default_duration_sec=60.0),
                    trials_per_session=10,
                    random_seed=42,
                )
            finally:
                video_library_module.probe_video_duration = original_probe

            self.assertEqual(len(playlist), 10)
            self.assertEqual(len({asset.rel_path for asset in playlist}), 10)
            self.assertEqual(probed, len(seen))
            self.assertLess(probed, 20)
            self.assertTrue(all(asset.duration_status == "valid" for asset in playlist))
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

            def break_start(self, **_payload) -> None:
                self._add("break_start")

            def break_end(self, **_payload) -> None:
                self._add("break_end")

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
            iti_sec=0.001,
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
        self.assertIn("break_start", manager.events)
        self.assertIn("break_end", manager.events)
        self.assertFalse(any("rating" in name for name in manager.events))
        self.assertEqual(len(runner.trial_records), 1)
        self.assertEqual(movie.stop_calls, 0)
        self.assertEqual(movie.unload_calls, 1)
        self.assertFalse(runner.trial_records[0].break_skipped)


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




