"""Stable interfaces shared by protocol runners and EEG session services."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class EegRecorder(Protocol):
    """Append-only recording contract; export seals the current part to disk."""
    part_index: int
    eeg_filename: str
    events_filename: str
    metadata_filename: str
    sample_count: int
    elapsed_sec: float

    def start_spooling(self, output_dir: Path) -> None: ...
    def pull(self) -> Any: ...
    def add_event(self, name: str, **payload: Any) -> None: ...
    def freeze(self) -> None: ...
    def export(self, output_dir: Path, *, metadata: dict[str, Any], pull_final: bool = True) -> Path: ...


class HealthMonitor(Protocol):
    timeout: float
    startup_timeout: float
    started: float
    last_sample_time: float

    def observe(self, count: int, now: float) -> dict[str, Any]: ...


class RecorderFactory(Protocol):
    def __call__(self, acquirer: Any, *, sfreq: float, n_channels: int,
                 event_only: bool) -> EegRecorder: ...
