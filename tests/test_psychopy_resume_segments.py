from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest
from uuid import uuid4

from psychopy_image_b_experiment import find_resume_state
from tasks.image_core import ImageAsset, ImageTrial


def _trials(count: int) -> list[ImageTrial]:
    return [
        ImageTrial(
            block_idx=1,
            trial_idx=index,
            block_trial_idx=index,
            repeat_idx=1,
            trial_type="rating",
            asset=ImageAsset(
                image_id=f"img_{index:03d}",
                rel_path=f"img_{index:03d}.jpg",
                category="test",
                split="train",
            ),
        )
        for index in range(1, count + 1)
    ]


class PsychoPyResumeSegmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / ".codex_tmp" / f"resume_test_{uuid4().hex}"
        self.session_dir = self.root / "S001" / "20260715_180000_set_A" / "session_01"
        self.session_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_resume_before_first_completed_trial_uses_original_session(self) -> None:
        (self.session_dir / ".resume_manifest.json").write_text(
            json.dumps(
                {
                    "subject_id": "S001",
                    "session_id": 1,
                    "task_mode": "image_b",
                    "image_set_label": "set_A",
                    "image_trials": 3,
                    "completed": False,
                }
            ),
            encoding="utf-8",
        )

        state = find_resume_state(
            self.root,
            subject_id="S001",
            session_id=1,
            trials=_trials(3),
            image_set_label="set_A",
        )

        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state["source_dir"], self.session_dir)
        self.assertEqual(state["completed_trial"], 0)
        self.assertEqual(state["next_trial"], 1)

    def test_completed_segment_manifest_is_not_resumed(self) -> None:
        (self.session_dir / "eeg_segments.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "subject_id": "S001",
                    "session_id": 1,
                    "task_mode": "image_b",
                    "image_set_label": "set_A",
                    "image_trials": 3,
                    "completed": True,
                    "segments": [],
                }
            ),
            encoding="utf-8",
        )

        state = find_resume_state(
            self.root,
            subject_id="S001",
            session_id=1,
            trials=_trials(3),
            image_set_label="set_A",
        )

        self.assertIsNone(state)


if __name__ == "__main__":
    unittest.main()
