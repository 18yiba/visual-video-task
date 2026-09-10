"""Dependency health check for the portable video-EEG environment.

This file intentionally starts with only Python standard-library imports so it
can explain a broken environment instead of failing before the check starts.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
from typing import Iterable


REQUIRED_MODULES: tuple[tuple[str, str], ...] = (
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("pandas", "pandas"),
    ("pytz", "pytz"),
    ("python-dateutil", "dateutil"),
    ("tzdata", "tzdata"),
    ("PyYAML", "yaml"),
    ("pylsl", "pylsl"),
    ("opencv-python", "cv2"),
    ("imageio-ffmpeg", "imageio_ffmpeg"),
    ("psutil", "psutil"),
    ("pyserial", "serial"),
    ("zeroconf", "zeroconf"),
    ("PsychoPy", "psychopy"),
    ("BrainCo SDK", "bcigo_sdk"),
    ("PsychoPy.visual", "psychopy.visual"),
    ("PsychoPy.core", "psychopy.core"),
    ("PsychoPy.event", "psychopy.event"),
    ("PsychoPy.gui", "psychopy.gui"),
    ("PsychoPy.data", "psychopy.data"),
    ("PsychoPy.hardware.keyboard", "psychopy.hardware.keyboard"),
    ("pytest", "pytest"),
    ("eeg-bids-converter", "eeg_bids_converter"),
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def check_modules(
    modules: Iterable[tuple[str, str]] = REQUIRED_MODULES, *, quiet: bool = False
) -> int:
    if not quiet:
        print(f"Python: {sys.executable}")
        print(f"Version: {sys.version.split()[0]}")
    failures = 0
    for label, module_name in modules:
        try:
            module = importlib.import_module(module_name)
            version = getattr(module, "__version__", "installed")
            if not quiet:
                print(f"[OK] {label}: {version}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")
    try:
        importlib.import_module("video_eeg.experiment.video_runner")
    except Exception as exc:
        failures += 1
        print(f"[FAIL] video_eeg core: {type(exc).__name__}: {exc}")
    else:
        if not quiet:
            print("[OK] video_eeg core")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(check_modules(quiet="--quiet" in sys.argv[1:]))
