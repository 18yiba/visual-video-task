from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest
from uuid import uuid4

from acquisition.external_recorder_acquirer import ExternalRecorderAcquirer
from protocol.video_protocol import EegSessionManager
from utils.markers import MarkerBackend


class _CaptureMarkers(MarkerBackend):
    def __init__(self) -> None:
        self.labels: list[int] = []

    def send(self, label: int, timestamp: float | None = None) -> None:
        del timestamp
        self.labels.append(int(label))


class BCIGoExternalRecordingTests(unittest.TestCase):
    def test_external_recording_exports_events_without_fake_eeg(self) -> None:
        root = Path.cwd() / ".codex_tmp" / f"bcigo_external_{uuid4().hex}"
        root.mkdir(parents=True)
        try:
            markers = _CaptureMarkers()
            manager = EegSessionManager(
                ExternalRecorderAcquirer(sfreq=250.0, n_channels=32),
                markers,
                sfreq=250.0,
                records_dir=root,
                subject_id="S001",
                session_id=1,
                record_local_eeg=False,
            )
            session_dir = manager.start(
                metadata={
                    "task_mode": "image_b",
                    "timestamp_label": "20260716_1234_default",
                    "eeg_recording_mode": "bcigo_external_edf",
                }
            )
            manager.begin_trial(trial_idx=1, video_name="image.jpg")
            manager.end_trial(trial_idx=1, video_name="image.jpg")
            manager.stop_and_export(metadata={"completed": True})

            self.assertFalse((session_dir / "continuous_eeg.npy").exists())
            self.assertTrue((session_dir / "events.json").exists())
            metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
            events = json.loads((session_dir / "events.json").read_text(encoding="utf-8"))
            self.assertFalse(metadata["local_eeg_recorded"])
            self.assertIsNone(metadata["eeg_file"])
            self.assertTrue(all(event["sample_index"] is None for event in events))
            self.assertEqual(markers.labels[0], 101)
            self.assertEqual(markers.labels[-1], 102)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
