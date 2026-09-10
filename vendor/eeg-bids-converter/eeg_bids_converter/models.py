from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class StimulusResolution:
    library: str
    source_root: Path
    referenced_files: tuple[str, ...]


@dataclass(slots=True)
class RecordingRecord:
    source_record_id: str
    source_path: Path
    duplicate_paths: tuple[Path, ...]
    subject: str
    source_subject: str
    task: str
    task_name: str
    session: str
    source_session_id: int | str | None
    timestamp_label: str
    acq_time: datetime | None
    metadata: dict[str, Any]
    device_type: str
    eeg_files: tuple[Path, ...]
    events_files: tuple[Path, ...]
    trial_log: Path | None
    behavioral_ratings: Path | None
    stimulus: StimulusResolution | None
    completed: bool | None
    termination_reason: str | None
    warnings: list[str] = field(default_factory=list)

    @property
    def has_eeg(self) -> bool:
        return bool(self.eeg_files)

    @property
    def is_incomplete(self) -> bool:
        return self.completed is False


@dataclass(slots=True)
class EEGProfile:
    sampling_frequency: float
    channel_names: tuple[str, ...]
    channel_types: tuple[str, ...]
    unit: str
    eeg_reference: str
    power_line_frequency: float
    software_filters: str | dict[str, Any]
    manufacturer: str = "n/a"
    hardware_filters: str | dict[str, Any] | None = None
    dropped_channels: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScanSummary:
    records: list[RecordingRecord]
    ignored_root_items: list[Path]
    errors: list[ConverterError]
