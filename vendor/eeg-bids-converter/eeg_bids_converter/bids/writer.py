from __future__ import annotations

import json
import logging
import warnings
from datetime import timezone
from pathlib import Path
from typing import Any

import mne
import pandas as pd
from mne_bids import BIDSPath, write_raw_bids

from .. import __version__
from ..adapters.eeg_numpy import NumpyEEGAdapter
from ..config import ConverterConfig
from ..conversion.events import build_behavior_table, build_events
from ..errors import ConverterError
from ..models import EEGProfile, RecordingRecord


LOG = logging.getLogger("eeg_bids_converter")
EXPECTED_MNE_BIDS_WARNINGS = (
    "No events found or provided",
    "Conflicting BIDSVersion found",
    "Converting data files to BrainVision format",
    'Encountered data in "double" format',
)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_tsv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, sep="\t", index=False, na_rep="n/a", lineterminator="\n")


class BIDSWriter:
    def __init__(self, bids_root: Path, cfg: ConverterConfig, adapter: NumpyEEGAdapter):
        self.root = bids_root.resolve()
        self.cfg = cfg
        self.adapter = adapter

    def initialize_dataset(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        description: dict[str, Any] = {
            "Name": self.cfg.dataset.name,
            "BIDSVersion": self.cfg.dataset.bids_version,
            "DatasetType": self.cfg.dataset.dataset_type,
            "GeneratedBy": [{"Name": "eeg-bids-converter", "Version": __version__}],
        }
        if self.cfg.dataset.authors:
            description["Authors"] = self.cfg.dataset.authors
        optional_dataset_fields = {
            "License": self.cfg.dataset.license,
            "Acknowledgements": self.cfg.dataset.acknowledgements,
            "HowToAcknowledge": self.cfg.dataset.how_to_acknowledge,
            "Funding": self.cfg.dataset.funding,
            "EthicsApprovals": self.cfg.dataset.ethics_approvals,
            "ReferencesAndLinks": self.cfg.dataset.references_and_links,
        }
        description.update({key: value for key, value in optional_dataset_fields.items() if value})
        _write_json(self.root / "dataset_description.json", description)
        readme = (
            f"# {self.cfg.dataset.name}\n\n"
            f"{self.cfg.dataset.description}\n\n"
            f"- Conversion tool: eeg-bids-converter {__version__}\n"
            "- EEG source format: NumPy arrays with device-specific metadata\n"
            "- EEG output format: BrainVision\n"
            f"- Task mapping: {', '.join(f'{source} to task-{target}' for source, target in self.cfg.task_mappings.items())}\n"
            "- Session strategy: acquisition date plus timestamp; source session fallback when time is absent\n"
            "- Source data are never modified.\n"
        )
        (self.root / "README").write_text(readme, encoding="utf-8")

    def update_participants(self, records: list[RecordingRecord]) -> None:
        path = self.root / "participants.tsv"
        existing: set[str] = set()
        if path.exists():
            try:
                existing = set(pd.read_csv(path, sep="\t")["participant_id"].astype(str))
            except Exception as exc:
                raise ConverterError("INVALID_PARTICIPANTS", f"Cannot read {path}: {exc}") from exc
        existing.update(f"sub-{record.subject}" for record in records)
        _write_tsv(path, pd.DataFrame({"participant_id": sorted(existing)}))

    def target_primary_path(self, record: RecordingRecord) -> Path:
        if record.has_eeg:
            return BIDSPath(
                subject=record.subject,
                session=record.session,
                task=record.task,
                datatype="eeg",
                suffix="eeg",
                extension=".vhdr",
                root=self.root,
                check=True,
            ).fpath
        return BIDSPath(
            subject=record.subject,
            session=record.session,
            task=record.task,
            datatype="beh",
            suffix="beh",
            extension=".tsv",
            root=self.root,
            check=True,
        ).fpath

    def write_record(self, record: RecordingRecord, overwrite: bool) -> tuple[Path, EEGProfile | None]:
        target = self.target_primary_path(record)
        if target.exists() and not overwrite:
            raise ConverterError("BIDS_TARGET_EXISTS", f"Target already exists: {target}", record.source_record_id)
        if record.has_eeg:
            profile = self.adapter.profile(record)
            target = self._write_eeg_record(record, profile, overwrite)
        else:
            profile = None
            target = self._write_behavior_record(record)
        self._update_scans(record, target)
        return target, profile

    def _write_eeg_record(self, record: RecordingRecord, profile: EEGProfile, overwrite: bool) -> Path:
        raw_parts: list[mne.io.RawArray] = []
        for index in range(len(record.eeg_files)):
            data_volts = self.adapter.load_part(record, index)
            info = mne.create_info(
                ch_names=list(profile.channel_names),
                sfreq=profile.sampling_frequency,
                ch_types=list(profile.channel_types),
            )
            info["line_freq"] = profile.power_line_frequency
            raw_parts.append(mne.io.RawArray(data_volts, info, verbose=False))
        raw = raw_parts[0] if len(raw_parts) == 1 else mne.concatenate_raws(raw_parts, verbose=False)
        if record.acq_time is not None:
            raw.set_meas_date(record.acq_time.astimezone(timezone.utc))
        bids_path = BIDSPath(
            subject=record.subject,
            session=record.session,
            task=record.task,
            datatype="eeg",
            suffix="eeg",
            root=self.root,
            check=True,
        )
        try:
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                write_raw_bids(
                    raw,
                    bids_path=bids_path,
                    # The primary target was checked above. MNE-BIDS also treats an
                    # existing participants.tsv row as an overwrite conflict, so its
                    # internal flag must be enabled for multi-session conversion.
                    overwrite=True,
                    format="BrainVision",
                    allow_preload=True,
                    verbose=False,
                )
            for item in caught_warnings:
                message = str(item.message)
                if not any(expected in message for expected in EXPECTED_MNE_BIDS_WARNINGS):
                    LOG.warning("MNE-BIDS source_record_id=%s: %s", record.source_record_id, message)
        except Exception as exc:
            raise ConverterError("EEG_CONVERSION_FAILURE", str(exc), record.source_record_id) from exc
        events, descriptions = build_events(record, profile, self.cfg)
        events_path = bids_path.copy().update(suffix="events", extension=".tsv").fpath
        _write_tsv(events_path, events)
        _write_json(events_path.with_suffix(".json"), descriptions)
        sidecar = bids_path.copy().update(extension=".json").fpath
        sidecar_data = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
        sidecar_data.update(
            {
                "TaskName": record.task,
                "SourceTaskName": record.task_name,
                "TaskDescription": self.cfg.task_descriptions.get(
                    record.task,
                    f"Visual stimulus task (source task: {record.task_name})",
                ),
                "Manufacturer": profile.manufacturer,
                "EEGReference": profile.eeg_reference,
                "SamplingFrequency": profile.sampling_frequency,
                "PowerLineFrequency": profile.power_line_frequency,
                "SoftwareFilters": profile.software_filters,
                "HardwareFilters": profile.hardware_filters if profile.hardware_filters is not None else "n/a",
            }
        )
        if record.task in self.cfg.task_instructions:
            sidecar_data["Instructions"] = self.cfg.task_instructions[record.task]
        if "MiscChannelCount" in sidecar_data:
            sidecar_data["MISCChannelCount"] = sidecar_data.pop("MiscChannelCount")
        sidecar_data["SourceDeviceType"] = record.device_type
        sidecar_data["SourceProfileProvenance"] = profile.provenance
        if profile.dropped_channels:
            sidecar_data["SourceNonEEGRowsDropped"] = list(profile.dropped_channels)
        _write_json(sidecar, sidecar_data)
        return bids_path.copy().update(extension=".vhdr").fpath

    def _write_behavior_record(self, record: RecordingRecord) -> Path:
        frame, descriptions = build_behavior_table(record)
        bids_path = BIDSPath(
            subject=record.subject,
            session=record.session,
            task=record.task,
            datatype="beh",
            suffix="beh",
            extension=".tsv",
            root=self.root,
            check=True,
        )
        _write_tsv(bids_path.fpath, frame)
        _write_json(bids_path.copy().update(extension=".json").fpath, descriptions)
        return bids_path.fpath

    def _update_scans(self, record: RecordingRecord, primary_path: Path) -> None:
        session_root = self.root / f"sub-{record.subject}" / f"ses-{record.session}"
        scans_path = session_root / f"sub-{record.subject}_ses-{record.session}_scans.tsv"
        filename = primary_path.relative_to(session_root).as_posix()
        acq_time = record.acq_time.isoformat() if record.acq_time else "n/a"
        rows = pd.DataFrame(columns=["filename", "acq_time"])
        if scans_path.exists():
            rows = pd.read_csv(scans_path, sep="\t", dtype=str).fillna("n/a")
        rows = rows[rows["filename"] != filename] if not rows.empty else rows
        rows = pd.concat([rows, pd.DataFrame([{"filename": filename, "acq_time": acq_time}])], ignore_index=True)
        rows = rows.sort_values("filename")
        _write_tsv(scans_path, rows)
