from __future__ import annotations

import unittest
from unittest.mock import patch

import psychopy_image_b_experiment as experiment
from utils.markers import NoOpMarkerBackend


class DeviceMarkerIsolationTests(unittest.TestCase):
    def test_neuracle_does_not_create_brainco_lsl_marker(self) -> None:
        config = {
            "device_type": "neuracle",
            "device": {
                "lsl_marker_enabled": True,
                "brainco_transport": "bcigo",
                "trigger_serial_port": "",
            },
        }

        with patch("utils.markers.LSLMarkerBackend") as lsl_backend:
            backend = experiment.build_marker_backend(config)

        self.assertIsInstance(backend, NoOpMarkerBackend)
        lsl_backend.assert_not_called()

    def test_brainco_bcigo_still_creates_lsl_marker(self) -> None:
        config = {
            "device_type": "brainco",
            "device": {
                "lsl_marker_enabled": True,
                "brainco_transport": "bcigo",
                "trigger_serial_port": "",
            },
        }

        marker = object()
        with (
            patch.dict(experiment._LSL_MARKER_BACKENDS, {}, clear=True),
            patch("utils.markers.LSLMarkerBackend", return_value=marker) as lsl_backend,
        ):
            backend = experiment.build_marker_backend(config)

        self.assertIs(backend, marker)
        lsl_backend.assert_called_once()


if __name__ == "__main__":
    unittest.main()
