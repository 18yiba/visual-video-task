import csv
from pathlib import Path
import random
from tempfile import TemporaryDirectory
import unittest

from video_eeg.utils.session_protocol import (
    SessionManifest,
    SessionManifestEntry,
    SessionState,
    build_attention_schedule,
    build_duration_bucket_assignments,
    build_duration_balanced_manifest,
    choose_rest_threshold_minutes,
    duration_progress,
    load_state,
    make_arithmetic_question,
    save_state_atomic,
    session_state_path,
)
from video_eeg.utils.video_library import VideoAsset


def assets(count: int = 120) -> list[VideoAsset]:
    return [
        VideoAsset(f"vid_{index:04d}", f"{index:04d}.mp4", float(5 + (index * 7) % 56))
        for index in range(1, count + 1)
    ]


class SessionPlanningTests(unittest.TestCase):
    def test_partition_is_fixed_complete_and_balanced(self) -> None:
        catalog = assets()
        manifest = build_duration_balanced_manifest(catalog, session_count=17, random_seed=17)
        manifest_again = build_duration_balanced_manifest(catalog, session_count=17, random_seed=17)
        self.assertEqual(manifest.entries, manifest_again.entries)
        self.assertEqual(len(manifest.entries), len(catalog))
        self.assertEqual(set(manifest.video_ids), {item.asset_id for item in catalog})
        totals = [manifest.session_duration_sec(index) for index in range(1, 18)]
        self.assertLess(max(totals) - min(totals), 60.0)

    def test_partition_balances_duration_buckets_and_excludes_long_videos(self) -> None:
        catalog = assets()
        manifest = build_duration_balanced_manifest(catalog, session_count=17, random_seed=17, excluded_video_count=2, source_video_count=122)
        definitions = [item["name"] for item in manifest.duration_bucket_definition]
        self.assertEqual(definitions, ["very_short", "short", "medium", "long", "very_long"])
        self.assertEqual(manifest.source_video_count, 122)
        self.assertEqual(manifest.excluded_video_count, 2)
        for session_id in range(1, 18):
            labels = {item.duration_bucket for item in manifest.session_entries(session_id)}
            self.assertEqual(labels, set(definitions))
        assignments, _ = build_duration_bucket_assignments(catalog)
        self.assertEqual(set(assignments), {item.asset_id for item in catalog})
        self.assertTrue(all(item.video_duration_sec <= 60.0 for item in manifest.entries))

    def test_current_formal_manifest_has_no_legacy_long_videos(self) -> None:
        path = Path("video_eeg/config/session_manifest.csv")
        manifest = SessionManifest.load(path)
        self.assertEqual(manifest.source_video_count, 7996)
        self.assertEqual(manifest.excluded_video_count, 47)
        self.assertEqual(len(manifest.entries), 7949)
        self.assertTrue(all(item.video_duration_sec <= 60.0 + 1e-6 for item in manifest.entries))
        self.assertEqual(len({item.video_id for item in manifest.entries}), 7949)
        for session_id in range(1, 18):
            labels = {item.duration_bucket for item in manifest.session_entries(session_id)}
            self.assertEqual(labels, {"very_short", "short", "medium", "long", "very_long"})

    def test_current_manifest_generates_18_boundary_attention_tasks_per_session(self) -> None:
        manifest = SessionManifest.load(Path("video_eeg/config/session_manifest.csv"))
        for session_id in range(1, 18):
            schedule = build_attention_schedule(manifest.session_assets(session_id), task_count=18, random_seed=17 + session_id)
            self.assertEqual(len(schedule), 18)
            self.assertEqual(len({item.after_video_number for item in schedule}), 18)

    def test_manifest_atomic_write_and_reload(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "session_manifest.csv"
            manifest = build_duration_balanced_manifest(assets(), session_count=17)
            manifest.write_atomic(path)
            loaded = SessionManifest.load(path)
            self.assertEqual(loaded.entries, manifest.entries)
            self.assertFalse(path.with_name(path.name + ".tmp").exists())

    def test_attention_is_18_even_boundary_checkpoints(self) -> None:
        schedule = build_attention_schedule(assets(), task_count=18, random_seed=19)
        self.assertEqual(len(schedule), 18)
        self.assertEqual([item.after_video_number for item in schedule], sorted({item.after_video_number for item in schedule}))
        self.assertGreater(schedule[0].scheduled_net_time_sec, 0.0)
        self.assertGreater(schedule[0].after_video_number, 1)
        other_seed = build_attention_schedule(assets(), task_count=18, random_seed=20)
        self.assertNotEqual(
            [item.scheduled_net_time_sec for item in schedule],
            [item.scheduled_net_time_sec for item in other_seed],
        )

    def test_arithmetic_generator_constraints_and_balance(self) -> None:
        truths = []
        for index in range(1, 1001):
            item = make_arithmetic_question(index, random_seed=42)
            truths.append(item["statement_truth"])
            self.assertIn(item["operator"], {"+", "-"})
            self.assertGreaterEqual(item["operand_a"], 0)
            self.assertLessEqual(item["operand_a"], 100)
            self.assertGreaterEqual(item["operand_b"], 0)
            self.assertLessEqual(item["operand_b"], 100)
            expected = item["operand_a"] + item["operand_b"] if item["operator"] == "+" else item["operand_a"] - item["operand_b"]
            self.assertEqual(item["true_result"], expected)
            self.assertGreaterEqual(item["true_result"], 0)
            self.assertLessEqual(item["true_result"], 100)
            self.assertGreaterEqual(item["displayed_result"], 0)
            self.assertLessEqual(item["displayed_result"], 100)
            self.assertEqual(item["statement_truth"], item["displayed_result"] == item["true_result"])
        self.assertAlmostEqual(sum(truths) / len(truths), 0.5, delta=0.01)

    def test_state_save_reload_and_skip_resume_semantics(self) -> None:
        catalog = assets()
        manifest = build_duration_balanced_manifest(catalog, session_count=17)
        state = SessionState.new(
            subject_id="S001", session_id=1, manifest=manifest, assets=manifest.session_assets(1),
            random_seed=17, attention_task_count=3, rest_min_minutes=30, rest_max_minutes=45,
        )
        first = state.queue_video_ids.pop(0)
        state.queue_video_ids.append(first)
        path = session_state_path(Path("records"), "S001", 1)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "S001" / "session_01" / "session_state.json"
            save_state_atomic(path, state, last_exit_reason="video_skipped")
            restored = load_state(path)
            assert restored is not None
            self.assertIn(first, restored.remaining_video_ids)
            self.assertNotIn(first, restored.completed_video_ids)
            self.assertEqual(restored.last_exit_reason, "video_skipped")

    def test_completed_video_is_removed_and_duration_progress_is_duration_based(self) -> None:
        state = SessionState(
            subject_id="S", session_id=1, manifest_version="video-eeg-session-manifest-v1", manifest_hash="x",
            video_ids=["short", "long"], queue_video_ids=["short", "long"],
            completed_net_video_duration_sec=60.0,
        )
        state.queue_video_ids.pop(0)
        state.completed_video_ids.append("short")
        state.completed_net_video_duration_sec += 60.0
        self.assertNotIn("short", state.remaining_video_ids)
        self.assertAlmostEqual(duration_progress(120.0, 660.0), 18.1818, places=3)
        self.assertNotEqual(duration_progress(600.0, 660.0), 50.0)

    def test_rest_threshold_is_integer_formal_minutes(self) -> None:
        rng = random.Random(17)
        values = [choose_rest_threshold_minutes(rng, 30, 45) for _ in range(1000)]
        self.assertTrue(all(30 <= value <= 45 and isinstance(value, int) for value in values))

    def test_demo_config_is_short_and_separate(self) -> None:
        from video_eeg.experiment.video_runner import load_config, VideoExperimentConfig
        formal_config = load_config(Path("video_eeg/config/video_legacy_17_config.yaml"))
        demo_config = load_config(Path("video_eeg/config/video_demo_config.yaml"))
        formal = VideoExperimentConfig.from_config(formal_config)
        demo = VideoExperimentConfig.from_config(demo_config)
        self.assertEqual(formal_config["sfreq"], 1000.0)
        self.assertEqual(formal_config["eeg_sampling_rate_hz"], 1000.0)
        self.assertEqual(demo_config["eeg_sampling_rate_hz"], 1000.0)
        self.assertEqual(formal.num_sessions, 17)
        self.assertEqual(formal.attention_tasks_per_session, 18)
        self.assertEqual(formal.rest_min_net_minutes, 30.0)
        self.assertEqual(demo.num_sessions, 1)
        self.assertEqual(demo.attention_tasks_per_session, 3)
        self.assertEqual(demo.rest_min_net_minutes, 30.0)
        self.assertEqual(demo.rest_max_net_minutes, 45.0)
        self.assertEqual(demo.iti_sec, 2.0)

    def test_participant_instructions_hide_debug_counts_and_explain_breaks(self) -> None:
        from video_eeg.experiment.video_runner import build_participant_instruction_text

        text = build_participant_instruction_text(
            subject_id="S001", session_id=3, rest_min_minutes=30, rest_max_minutes=45,
        )
        self.assertIn("一系列视频", text)
        self.assertIn("随机抽查刚才的视频内容", text)
        self.assertIn("每个视频结束后会有短暂休息", text)
        self.assertIn("F 继续", text)
        self.assertIn("J 退出", text)
        self.assertNotIn("10 个视频", text)
        self.assertNotIn("道注意力", text)

    def test_keyboard_contract_is_explicit_and_mouse_free(self) -> None:
        from video_eeg.experiment.video_runner import (
            ATTENTION_BUTTON_LAYOUT,
            attention_response_for_key,
            attention_response_is_correct,
            rest_action_for_key,
        )

        self.assertEqual(attention_response_for_key("f"), "incorrect")
        self.assertEqual(attention_response_for_key("J"), "correct")
        self.assertTrue(attention_response_is_correct("f", False))
        self.assertFalse(attention_response_is_correct("j", False))
        self.assertTrue(attention_response_is_correct("j", True))
        self.assertEqual(ATTENTION_BUTTON_LAYOUT["left"]["key"], "F")
        self.assertEqual(ATTENTION_BUTTON_LAYOUT["left"]["response"], "incorrect")
        self.assertEqual(ATTENTION_BUTTON_LAYOUT["left"]["label"], "错误")
        self.assertEqual(ATTENTION_BUTTON_LAYOUT["left"]["fill_color"], "#7f1d1d")
        self.assertEqual(ATTENTION_BUTTON_LAYOUT["right"]["key"], "J")
        self.assertEqual(ATTENTION_BUTTON_LAYOUT["right"]["response"], "correct")
        self.assertEqual(ATTENTION_BUTTON_LAYOUT["right"]["label"], "正确")
        self.assertEqual(ATTENTION_BUTTON_LAYOUT["right"]["fill_color"], "#166534")
        self.assertEqual(rest_action_for_key("F"), "continue")
        self.assertEqual(rest_action_for_key("j"), "exit")
        self.assertEqual(rest_action_for_key("escape"), "emergency")

    def test_attention_record_constructor_and_response_path_include_index(self) -> None:
        from video_eeg.experiment.video_runner import VideoRunner

        runner = object.__new__(VideoRunner)
        runner.config = {"subject_id": "P0", "session_id": 3}
        runner.state = None
        runner.attention_records = []
        runner._state_completed_duration = lambda: 123.0
        runner._write_attention_log = lambda: None
        item = {
            "attention_id": 2,
            "scheduled_net_time_sec": 120.0,
            "after_video_number": 4,
            "question_text": "判断：46 - 23 = 26 是否正确？",
            "operator": "-",
            "operand_a": 46,
            "operand_b": 23,
            "true_result": 23,
            "displayed_result": 26,
            "statement_truth": False,
        }
        runner._append_attention_record(
            item,
            response="incorrect",
            response_key="F",
            response_correct=True,
            reaction_time_sec=0.8,
            timeout=False,
            page_onset_timestamp="2026-01-01T00:00:00+0800",
            response_timestamp="2026-01-01T00:00:01+0800",
            dwell_time_sec=0.8,
            completed=True,
            aborted=False,
            abort_reason="",
        )
        self.assertEqual(len(runner.attention_records), 1)
        record = runner.attention_records[0]
        self.assertEqual(record.attention_idx, 2)
        self.assertEqual(record.attention_id, 2)
        self.assertTrue(record.response_correct)

    def test_demo_seed_changes_schedule_and_question_but_resume_keeps_it(self) -> None:
        catalog = assets(40)
        manifest = SessionManifest(
            version="video-eeg-session-manifest-v1",
            entries=[SessionManifestEntry(1, item.asset_id, item.rel_path, float(item.duration_sec)) for item in catalog],
        )
        first = SessionState.new(
            subject_id="DEMO", session_id=1, manifest=manifest, assets=catalog,
            random_seed=1001, attention_task_count=3, rest_min_minutes=30, rest_max_minutes=45,
            demo_mode=True,
        )
        second = SessionState.new(
            subject_id="DEMO", session_id=1, manifest=manifest, assets=catalog,
            random_seed=2002, attention_task_count=3, rest_min_minutes=30, rest_max_minutes=45,
            demo_mode=True,
        )
        self.assertNotEqual(first.attention_schedule, second.attention_schedule)
        with TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            save_state_atomic(state_path, first)
            restored = load_state(state_path)
            assert restored is not None
            self.assertEqual(restored.attention_schedule, first.attention_schedule)

    def test_attention_due_uses_completed_net_time_not_first_video_index(self) -> None:
        from video_eeg.experiment.video_runner import VideoRunner

        class State:
            completed_video_ids = ["video_1"]
            completed_attention_ids: list[int] = []
            completed_net_video_duration_sec = 29.0
            attention_schedule = [{"attention_id": 1, "scheduled_net_time_sec": 30.0, "after_video_number": 1}]

        runner = object.__new__(VideoRunner)
        runner.state = State()
        calls: list[int] = []
        runner._run_attention_task = lambda schedule_item: calls.append(schedule_item["attention_id"]) or True
        runner._run_due_attention_tasks()
        self.assertEqual(calls, [])
        runner.state.completed_net_video_duration_sec = 30.0
        runner._run_due_attention_tasks()
        self.assertEqual(calls, [1])

    def test_fast_smoke_video_attention_rest_exit_resume_flow(self) -> None:
        catalog = [VideoAsset(f"v{index}", f"v{index}.mp4", 1.0) for index in range(1, 6)]
        manifest = SessionManifest(
            version="video-eeg-session-manifest-v1",
            entries=[
                # The state machine simulation only needs one small session.
                *(SessionManifestEntry(1, asset.asset_id, asset.rel_path, 1.0) for asset in catalog),
            ],
        )
        state = SessionState.new(
            subject_id="SMOKE", session_id=1, manifest=manifest, assets=catalog,
            random_seed=3, attention_task_count=1, rest_min_minutes=0.01, rest_max_minutes=0.02,
        )
        first, second = state.queue_video_ids[:2]
        state.commit_completed_video(first, 1.0)
        state.commit_completed_video(second, 1.0)
        state.completed_attention_ids.append(1)
        skipped = state.queue_video_ids[0]
        state.requeue_skipped_video(skipped)
        self.assertIn(skipped, state.remaining_video_ids)
        interrupted = state.queue_video_ids[0]
        state.preserve_aborted_video(interrupted)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_state_atomic(path, state, last_exit_reason="esc_emergency")
            resumed = load_state(path)
            assert resumed is not None
            self.assertEqual(resumed.current_video_id, interrupted)
            self.assertEqual(resumed.queue_video_ids[0], interrupted)
            while resumed.queue_video_ids:
                resumed.commit_completed_video(resumed.queue_video_ids[0], 1.0)
            self.assertEqual(set(resumed.completed_video_ids), set(resumed.video_ids))
            self.assertEqual(resumed.completed_attention_count, 1)


if __name__ == "__main__":
    unittest.main()
