from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import unittest
from uuid import uuid4

import numpy as np

from protocol.session_recorder import SessionRecorder


class _FakeAcquirer:
    def __init__(self, value: float) -> None:
        self._value = value

    def get_new_samples(self):
        eeg = np.full((2, 4), self._value, dtype=np.float32)
        return eeg, np.arange(eeg.shape[1], dtype=np.float64)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SessionRecorderSegmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / ".codex_tmp" / f"segment_test_{uuid4().hex}"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _export(self, root: Path, *, completed: bool, value: float) -> SessionRecorder:
        recorder = SessionRecorder(_FakeAcquirer(value), sfreq=10, n_channels=2)
        recorder.start_spooling(root)
        recorder.pull()
        recorder.export(
            root,
            metadata={
                "subject_id": "S001",
                "session_id": 1,
                "task_mode": "image_b",
                "image_set_label": "set_A",
                "image_trials": 10,
                "completed": completed,
                "segment_start_trial": 1 if recorder.part_index == 1 else 6,
                "segment_end_trial": 5 if recorder.part_index == 1 else 10,
            },
        )
        return recorder

    def test_resume_creates_part_two_without_changing_part_one(self) -> None:
        root = self.root
        first = self._export(root, completed=False, value=1.0)
        original_digest = _digest(root / first.eeg_filename)

        second = self._export(root, completed=True, value=2.0)

        self.assertEqual(second.part_index, 2)
        self.assertEqual(_digest(root / "continuous_eeg.npy"), original_digest)
        self.assertTrue((root / "continuous_eeg_part_002.npy").exists())
        self.assertTrue((root / "events_part_002.json").exists())
        self.assertTrue((root / "metadata_part_002.json").exists())
        manifest = json.loads((root / "eeg_segments.json").read_text(encoding="utf-8"))
        self.assertEqual([item["part"] for item in manifest["segments"]], [1, 2])
        self.assertTrue(manifest["completed"])

    def test_stale_spool_is_preserved_and_its_part_is_skipped(self) -> None:
        root = self.root
        self._export(root, completed=False, value=1.0)
        stale = root / ".continuous_eeg_part_002.f32.tmp"
        stale.write_bytes(b"do-not-overwrite")

        recorder = SessionRecorder(_FakeAcquirer(3.0), sfreq=10, n_channels=2)
        recorder.start_spooling(root)

        self.assertEqual(recorder.part_index, 3)
        self.assertEqual(stale.read_bytes(), b"do-not-overwrite")
        recorder.pull()
        recorder.export(
            root,
            metadata={
                "subject_id": "S001",
                "session_id": 1,
                "task_mode": "image_b",
                "image_trials": 10,
                "completed": False,
            },
        )
        manifest = json.loads((root / "eeg_segments.json").read_text(encoding="utf-8"))
        part_two = next(item for item in manifest["segments"] if item["part"] == 2)
        self.assertEqual(part_two["status"], "incomplete_raw")
        self.assertEqual(stale.read_bytes(), b"do-not-overwrite")

    def test_existing_target_causes_safe_failure(self) -> None:
        root = self.root
        recorder = SessionRecorder(_FakeAcquirer(1.0), sfreq=10, n_channels=2)
        recorder.start_spooling(root)
        recorder.pull()
        target = root / recorder.eeg_filename
        target.write_bytes(b"existing-data")

        with self.assertRaises(FileExistsError):
            recorder.export(root, metadata={"subject_id": "S001", "session_id": 1})
        self.assertEqual(target.read_bytes(), b"existing-data")


if __name__ == "__main__":
    unittest.main()
