from __future__ import annotations

import importlib.util
import threading
import time
import unittest
from uuid import uuid4

import numpy as np

from acquisition.lsl_acquirer import LSLAcquirer
from utils.markers import LSLMarkerBackend


PYLSL_AVAILABLE = importlib.util.find_spec("pylsl") is not None


@unittest.skipUnless(PYLSL_AVAILABLE, "pylsl is not installed")
class LSLBackendTests(unittest.TestCase):
    def test_eeg_stream_round_trip(self) -> None:
        from pylsl import StreamInfo, StreamOutlet

        suffix = uuid4().hex
        name = f"bcigo-test-{suffix}"
        source_id = f"bcigo-test-source-{suffix}"
        outlet = StreamOutlet(StreamInfo(name, "EEG", 4, 100.0, "float32", source_id))
        stop_event = threading.Event()

        def produce() -> None:
            sample_index = 0
            while not stop_event.is_set():
                value = float(sample_index)
                outlet.push_sample([value, value + 1, value + 2, value + 3])
                sample_index += 1
                time.sleep(0.005)

        producer = threading.Thread(target=produce, daemon=True)
        producer.start()
        acquirer = LSLAcquirer(
            sfreq=100.0,
            n_channels=4,
            buffer_sec=2.0,
            stream_name=name,
            stream_type="EEG",
            source_id=source_id,
            resolve_timeout_sec=3.0,
            ready_timeout_sec=2.0,
            backend_name="brainco_lsl",
        )
        try:
            acquirer.start_stream()
            eeg, timestamps = acquirer.get_chunk(0.2)
            self.assertEqual(eeg.shape, (4, 20))
            self.assertEqual(timestamps.shape, (20,))
            self.assertTrue(np.isfinite(eeg).all())
            incremental, incremental_timestamps = acquirer.get_new_samples()
            self.assertEqual(incremental.shape[0], 4)
            self.assertEqual(incremental.shape[1], incremental_timestamps.shape[0])
        finally:
            acquirer.stop_stream()
            stop_event.set()
            producer.join(timeout=1.0)

    def test_marker_stream_round_trip(self) -> None:
        from pylsl import StreamInlet, resolve_byprop

        suffix = uuid4().hex
        name = f"visual-video-task-Markers-{suffix}"
        source_id = f"visual-video-task-marker-{suffix}"
        backend = LSLMarkerBackend(stream_name=name, source_id=source_id)
        streams = resolve_byprop("source_id", source_id, minimum=1, timeout=3.0)
        self.assertEqual(len(streams), 1)
        inlet = StreamInlet(streams[0])
        inlet.open_stream(timeout=2.0)
        sample = None
        timestamp = 0.0
        deadline = time.monotonic() + 3.0
        # LSL discovery can finish slightly before the outlet sees the new
        # consumer. Retry the marker while that subscription settles.
        while sample is None and time.monotonic() < deadline:
            backend.send(132)
            sample, timestamp = inlet.pull_sample(timeout=0.25)
        self.assertEqual(sample, [132])
        self.assertGreater(timestamp, 0.0)
        inlet.close_stream()


if __name__ == "__main__":
    unittest.main()
