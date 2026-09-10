from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from ..models import EEGProfile, RecordingRecord


MANIFEST_COLUMNS = [
    "source_record_id",
    "source_path",
    "duplicate_source_paths",
    "subject",
    "session",
    "task",
    "acq_time",
    "device_type",
    "source_eeg_files",
    "source_eeg_sha256",
    "bids_primary_path",
    "behavior_source",
    "stimulus_library",
    "stimuli_count",
    "stimuli_set_sha256",
    "completed",
    "termination_reason",
    "warnings",
    "profile_provenance",
    "conversion_status",
    "validation_status",
]


def _aggregate_hash(paths: tuple[Path, ...]) -> str:
    if not paths:
        return ""
    entries: list[str] = []
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        entries.append(f"{path.name}:{digest.hexdigest()}")
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


class Manifest:
    def __init__(self, bids_root: Path):
        self.path = bids_root / "code" / "conversion_manifest.tsv"
        if self.path.exists():
            self.frame = pd.read_csv(self.path, sep="\t", dtype=str).fillna("")
        else:
            self.frame = pd.DataFrame(columns=MANIFEST_COLUMNS)

    def successful_ids(self) -> set[str]:
        if self.frame.empty:
            return set()
        return set(
            self.frame.loc[
                self.frame["conversion_status"].isin(["SUCCESS", "INCOMPLETE_SUCCESS"]),
                "source_record_id",
            ]
        )

    def upsert(
        self,
        record: RecordingRecord,
        bids_primary_path: Path | None,
        profile: EEGProfile | None,
        stimuli_count: int,
        stimuli_hash: str,
        conversion_status: str,
        validation_status: str = "PENDING",
    ) -> None:
        row: dict[str, Any] = {
            "source_record_id": record.source_record_id,
            "source_path": str(record.source_path),
            "duplicate_source_paths": "|".join(str(path) for path in record.duplicate_paths),
            "subject": f"sub-{record.subject}",
            "session": f"ses-{record.session}",
            "task": f"task-{record.task}",
            "acq_time": record.acq_time.isoformat() if record.acq_time else "n/a",
            "device_type": record.device_type,
            "source_eeg_files": "|".join(str(path) for path in record.eeg_files),
            "source_eeg_sha256": _aggregate_hash(record.eeg_files),
            "bids_primary_path": str(bids_primary_path) if bids_primary_path else "",
            "behavior_source": str(record.trial_log) if record.trial_log else "",
            "stimulus_library": record.stimulus.library if record.stimulus else "",
            "stimuli_count": stimuli_count,
            "stimuli_set_sha256": stimuli_hash,
            "completed": record.completed,
            "termination_reason": record.termination_reason or "",
            "warnings": "|".join(record.warnings),
            "profile_provenance": repr(profile.provenance) if profile else "",
            "conversion_status": conversion_status,
            "validation_status": validation_status,
        }
        if not self.frame.empty:
            self.frame = self.frame[self.frame["source_record_id"] != record.source_record_id]
        self.frame = pd.concat([self.frame, pd.DataFrame([row])], ignore_index=True)
        self.flush()

    def set_validation_status(self, status: str) -> None:
        if not self.frame.empty:
            self.frame["validation_status"] = status
            self.flush()

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.frame = self.frame.reindex(columns=MANIFEST_COLUMNS).sort_values("source_record_id")
        self.frame.to_csv(self.path, sep="\t", index=False, na_rep="n/a", lineterminator="\n")

