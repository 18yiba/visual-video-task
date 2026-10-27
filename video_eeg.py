"""Compatibility import for existing source scripts; runtime code lives in src/."""
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent / 'src' / 'video_eeg')]
