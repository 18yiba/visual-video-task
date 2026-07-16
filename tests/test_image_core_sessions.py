from pathlib import Path
import shutil
import unittest
from uuid import uuid4

from tasks.image_core import (
    FORMAL_500_PROTOCOL,
    PILOT_105_PROTOCOL,
    build_session_playlist,
    image_root,
    session_type_for_id,
    subject_image_set_path,
)


def _image_config(image_library: Path, protocol_name: str, label: str) -> dict:
    return {
        "task_mode": "image_b",
        "experiment_protocol": protocol_name,
        "image_set_label": label,
        "protocol": {
            "image_library_dir": str(image_library),
            "images_per_subject": 500,
            "pilot_images_per_subject": 105,
            "block_size": 100,
            "pilot_block_size": 105,
            "attention_probability": 0.05,
            "random_seed": 17,
        },
    }


def _make_image_library(root: Path, count: int = 500) -> None:
    root.mkdir(parents=True)
    for index in range(count):
        (root / f"img_{index:04d}.jpg").touch()


class ImageCoreSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / ".codex_tmp" / f"image_core_test_{uuid4().hex}"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_formal_session_one_is_the_only_labeling_session(self) -> None:
        self.assertEqual(session_type_for_id(1), "labeling")
        for session_id in range(2, 6):
            self.assertEqual(session_type_for_id(session_id), "denoise")

    def test_protocol_session_ranges_are_enforced(self) -> None:
        self.assertEqual(session_type_for_id(1, PILOT_105_PROTOCOL), "labeling")
        with self.assertRaises(ValueError):
            session_type_for_id(2, PILOT_105_PROTOCOL)
        with self.assertRaises(ValueError):
            session_type_for_id(6, FORMAL_500_PROTOCOL)

    def test_protocols_resolve_to_separate_source_libraries(self) -> None:
        config = {
            "experiment_protocol": PILOT_105_PROTOCOL,
            "protocol": {
                "pilot_image_library_dir": "image_library/pilot",
                "formal_image_library_dir": "image_library/formal",
            },
        }
        self.assertEqual(
            image_root(config, base_dir=self.root),
            self.root / "image_library" / "pilot",
        )
        config["experiment_protocol"] = FORMAL_500_PROTOCOL
        self.assertEqual(
            image_root(config, base_dir=self.root),
            self.root / "image_library" / "formal",
        )

    def test_formal_playlist_has_five_balanced_blocks_and_rotates_positions(self) -> None:
        image_library = self.root / "images"
        records_dir = self.root / "records"
        _make_image_library(image_library)
        config = _image_config(image_library, FORMAL_500_PROTOCOL, "image_b_500_v2")

        block_positions: dict[str, set[int]] = {}
        for session_id in range(1, 6):
            trials, assets, metadata = build_session_playlist(
                config,
                subject_id="S001",
                session_id=session_id,
                records_dir=records_dir,
            )
            self.assertEqual(len(assets), 500)
            self.assertEqual(len(trials), 500)
            self.assertEqual(metadata["block_count"], 5)
            self.assertEqual(
                [sum(trial.block_idx == block for trial in trials) for block in range(1, 6)],
                [100] * 5,
            )
            self.assertEqual(len({trial.asset.image_id for trial in trials}), 500)
            expected_type = "rating" if session_id == 1 else "eeg_denoise"
            self.assertEqual({trial.trial_type for trial in trials}, {expected_type})
            for trial in trials:
                block_positions.setdefault(trial.asset.image_id, set()).add(trial.block_idx)

        self.assertTrue(
            all(positions == {1, 2, 3, 4, 5} for positions in block_positions.values())
        )

    def test_pilot_and_formal_subject_sets_are_separate(self) -> None:
        image_library = self.root / "images"
        records_dir = self.root / "records"
        _make_image_library(image_library)

        pilot_config = _image_config(image_library, PILOT_105_PROTOCOL, "image_b_pilot105_v1")
        pilot_trials, _, _ = build_session_playlist(
            pilot_config,
            subject_id="S001",
            session_id=1,
            records_dir=records_dir,
        )
        formal_config = _image_config(image_library, FORMAL_500_PROTOCOL, "image_b_500_v2")
        formal_trials, _, _ = build_session_playlist(
            formal_config,
            subject_id="S001",
            session_id=1,
            records_dir=records_dir,
        )

        self.assertEqual(len(pilot_trials), 105)
        self.assertEqual(len(formal_trials), 500)
        pilot_path = subject_image_set_path(records_dir, "S001", "image_b_pilot105_v1")
        formal_path = subject_image_set_path(records_dir, "S001", "image_b_500_v2")
        self.assertNotEqual(pilot_path, formal_path)
        self.assertTrue(pilot_path.exists())
        self.assertTrue(formal_path.exists())

    def test_formal_protocol_rejects_a_reused_105_image_set(self) -> None:
        image_library = self.root / "images"
        records_dir = self.root / "records"
        _make_image_library(image_library)
        shared_label = "old_default"
        pilot_config = _image_config(image_library, PILOT_105_PROTOCOL, shared_label)
        build_session_playlist(
            pilot_config,
            subject_id="S001",
            session_id=1,
            records_dir=records_dir,
        )

        formal_config = _image_config(image_library, FORMAL_500_PROTOCOL, shared_label)
        with self.assertRaisesRegex(ValueError, "contains 105 images"):
            build_session_playlist(
                formal_config,
                subject_id="S001",
                session_id=1,
                records_dir=records_dir,
            )


if __name__ == "__main__":
    unittest.main()
