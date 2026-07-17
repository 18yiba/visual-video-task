from __future__ import annotations

import unittest
from unittest.mock import patch

from acquisition.neuracle_acquirer import NeuracleAcquirer
from collect.neuracle_api import DataServerThread


class NeuracleMemoryBoundsTests(unittest.TestCase):
    def test_timestamp_history_can_be_disabled(self) -> None:
        server = DataServerThread(record_timestamps=False)
        try:
            for value in range(10_000):
                server._record_timestamp("data", value)
                server._record_timestamp("trigger", value)

            self.assertEqual(server.timeStamp, {"data": [], "trigger": []})
        finally:
            server.stop()

    def test_legacy_defaults_remain_compatible(self) -> None:
        server = DataServerThread()
        try:
            server._record_timestamp("data", 123)
            self.assertEqual(server.timeStamp["data"], [123])
            self.assertTrue(server.enable_save_buffer)
        finally:
            server.stop()

    def test_neuracle_experiment_disables_duplicate_full_session_buffers(self) -> None:
        captured: dict[str, object] = {}

        class FakeDataServer:
            def __init__(self, **kwargs: object) -> None:
                captured.update(kwargs)

            def connect(self, **kwargs: object) -> bool:
                del kwargs
                return True

        acquirer = NeuracleAcquirer()
        with patch("collect.neuracle_api.DataServerThread", FakeDataServer):
            with self.assertRaisesRegex(RuntimeError, "Could not connect"):
                acquirer.start_stream()

        self.assertFalse(captured["enable_save_buffer"])
        self.assertFalse(captured["record_timestamps"])


if __name__ == "__main__":
    unittest.main()
