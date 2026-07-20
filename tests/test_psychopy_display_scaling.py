from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import psychopy_image_b_experiment as experiment


class WindowsDisplayScalingTests(unittest.TestCase):
    def test_uses_extended_display_and_its_native_size(self) -> None:
        primary = type("Screen", (), {"width": 2560, "height": 1600})()
        extended = type("Screen", (), {"width": 2560, "height": 1440})()
        canvas = SimpleNamespace(
            get_display=lambda: SimpleNamespace(get_screens=lambda: [primary, extended])
        )
        pyglet = SimpleNamespace(canvas=canvas)

        with patch.dict("sys.modules", {"pyglet": pyglet}):
            target = experiment._fullscreen_display()

        self.assertEqual(target, (1, (2560, 1440)))

    def test_single_display_falls_back_to_primary(self) -> None:
        primary = type("Screen", (), {"width": 1920, "height": 1080})()
        canvas = SimpleNamespace(
            get_display=lambda: SimpleNamespace(get_screens=lambda: [primary])
        )
        pyglet = SimpleNamespace(canvas=canvas)

        with patch.dict("sys.modules", {"pyglet": pyglet}):
            target = experiment._fullscreen_display()

        self.assertEqual(target, (0, (1920, 1080)))


if __name__ == "__main__":
    unittest.main()
