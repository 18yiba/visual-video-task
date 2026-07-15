"""Continuous session recording helpers for video-EEG experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from acquisition.base import AbstractAcquirer


@dataclass(slots=True)
class SessionEvent:
    name: str
    sample_index: int
    relative_time_sec: float
    payload: dict[str, Any]


class SessionRecorder:
    """Collect continuous EEG and aligned events during one protocol session."""

    def __init__(self, acquirer: AbstractAcquirer, *, sfreq: float, n_channels: int) -> None:
        self._acquirer = acquirer
        self._sfreq = float(sfreq)
        self._n_channels = int(n_channels)
        self._chunks: list[np.ndarray] = []
        self._spool_path: Path | None = None
        self._spool_handle: Any | None = None
        self._part_index = 0
        self._eeg_filename = ""
        self._events_filename = ""
        self._metadata_filename = ""
        self._events: list[SessionEvent] = []
        self._sample_count = 0
        self._started_at = time.monotonic()

    @property
    def sample_count(self) -> int:
        return self._sample_count

    @property
    def events(self) -> list[SessionEvent]:
        return list(self._events)

    @property
    def part_index(self) -> int:
        return self._part_index

    @property
    def eeg_filename(self) -> str:
        return self._eeg_filename

    @property
    def events_filename(self) -> str:
        return self._events_filename

    @property
    def metadata_filename(self) -> str:
        return self._metadata_filename

    def pull(self) -> np.ndarray:
        samples, _timestamps = self._acquirer.get_new_samples()
        if samples.size == 0:
            return np.empty((self._n_channels, 0), dtype=np.float32)
        if samples.ndim != 2 or samples.shape[0] < self._n_channels:
            raise RuntimeError(f"Unexpected incremental EEG shape: {samples.shape}")
        eeg = np.asarray(samples[: self._n_channels], dtype=np.float32)
        if self._spool_handle is not None:
            np.ascontiguousarray(eeg.T).tofile(self._spool_handle)
            self._spool_handle.flush()
        else:
            self._chunks.append(eeg.copy())
        self._sample_count += int(eeg.shape[1])
        return eeg

    def start_spooling(self, output_dir: Path) -> None:
        """Stream samples to a bounded-memory temporary file for this session."""
        output_dir.mkdir(parents=True, exist_ok=True)
        self._part_index = self._next_part_index(output_dir)
        self._eeg_filename, self._events_filename, self._metadata_filename = self._part_filenames(
            self._part_index
        )
        if self._part_index == 1:
            spool_name = ".continuous_eeg.f32.tmp"
        else:
            spool_name = f".continuous_eeg_part_{self._part_index:03d}.f32.tmp"
        self._spool_path = output_dir / spool_name
        self._spool_handle = self._spool_path.open("xb")

    def add_event(self, name: str, **payload: Any) -> None:
        self._events.append(
            SessionEvent(
                name=name,
                sample_index=self._sample_count,
                relative_time_sec=time.monotonic() - self._started_at,
                payload=dict(payload),
            )
        )

    def export(self, output_dir: Path, *, metadata: dict[str, Any]) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.pull()
        except BaseException:
            # Preserve everything already spooled when acquisition has failed.
            if self._sample_count <= 0:
                raise
        if self._spool_handle is not None:
            self._spool_handle.close()
            self._spool_handle = None
        eeg_path = output_dir / self._eeg_filename
        if self._spool_path is not None and self._spool_path.exists() and self._sample_count > 0:
            raw = np.memmap(self._spool_path, dtype=np.float32, mode="r", shape=(self._sample_count, self._n_channels))
            writing_path = output_dir / f".{self._eeg_filename}.{uuid4().hex}.writing"
            target = np.lib.format.open_memmap(
                writing_path, mode="w+", dtype=np.float32,
                shape=(self._n_channels, self._sample_count),
            )
            block = max(1, int(self._sfreq * 10))
            for start in range(0, self._sample_count, block):
                end = min(start + block, self._sample_count)
                target[:, start:end] = raw[start:end].T
            target.flush()
            del target, raw
            try:
                os.link(writing_path, eeg_path)
            finally:
                writing_path.unlink(missing_ok=True)
            self._spool_path.unlink()
        elif self._spool_path is not None and self._spool_path.exists():
            with eeg_path.open("xb") as handle:
                np.save(handle, np.empty((self._n_channels, 0), dtype=np.float32))
            self._spool_path.unlink()
        else:
            with eeg_path.open("xb") as handle:
                np.save(handle, self.to_array())
        with (output_dir / self._events_filename).open("x", encoding="utf-8") as handle:
            json.dump([asdict(event) for event in self._events], handle, ensure_ascii=False, indent=2)
        segment_metadata = dict(metadata)
        segment_metadata.update(
            {
                "eeg_part": self._part_index,
                "eeg_file": self._eeg_filename,
                "events_file": self._events_filename,
                "metadata_file": self._metadata_filename,
                "sample_count": self._sample_count,
                "sample_index_origin": "segment_local",
            }
        )
        with (output_dir / self._metadata_filename).open("x", encoding="utf-8") as handle:
            json.dump(segment_metadata, handle, ensure_ascii=False, indent=2)
        self._update_segments_manifest(output_dir, segment_metadata)
        return output_dir

    @staticmethod
    def _part_filenames(part_index: int) -> tuple[str, str, str]:
        if part_index == 1:
            return "continuous_eeg.npy", "events.json", "metadata.json"
        suffix = f"part_{part_index:03d}"
        return f"continuous_eeg_{suffix}.npy", f"events_{suffix}.json", f"metadata_{suffix}.json"

    @classmethod
    def _next_part_index(cls, output_dir: Path) -> int:
        occupied: set[int] = set()
        legacy_names = {
            "continuous_eeg.npy",
            "events.json",
            "metadata.json",
            ".continuous_eeg.f32.tmp",
        }
        pattern = re.compile(
            r"^(?:\.?continuous_eeg|events|metadata)_part_(\d{3})(?:\.f32\.tmp|\.npy|\.json)$"
        )
        for path in output_dir.iterdir():
            if path.name in legacy_names:
                occupied.add(1)
                continue
            match = pattern.fullmatch(path.name)
            if match:
                occupied.add(int(match.group(1)))
        return max(occupied, default=0) + 1

    def _update_segments_manifest(self, output_dir: Path, metadata: dict[str, Any]) -> None:
        manifest_path = output_dir / "eeg_segments.json"
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                manifest = {}
        segments = [dict(item) for item in manifest.get("segments", []) if isinstance(item, dict)]
        known_parts = {int(item.get("part", 0)) for item in segments}
        if self._part_index > 1 and 1 not in known_parts and (output_dir / "continuous_eeg.npy").exists():
            segments.append(self._legacy_segment_record(output_dir))
            known_parts.add(1)
        for stale_part, stale_path in self._stale_spools(output_dir):
            if stale_part not in known_parts and stale_part != self._part_index:
                segments.append(
                    {
                        "part": stale_part,
                        "status": "incomplete_raw",
                        "raw_file": stale_path.name,
                        "raw_bytes": stale_path.stat().st_size,
                        "sample_index_origin": "segment_local",
                    }
                )
                known_parts.add(stale_part)
        segments = [item for item in segments if int(item.get("part", 0)) != self._part_index]
        segments.append(
            {
                "part": self._part_index,
                "status": "finalized",
                "eeg_file": self._eeg_filename,
                "events_file": self._events_filename,
                "metadata_file": self._metadata_filename,
                "sample_count": self._sample_count,
                "sfreq": self._sfreq,
                "n_channels": self._n_channels,
                "start_trial": metadata.get("segment_start_trial"),
                "end_trial": metadata.get("segment_end_trial"),
                "termination_reason": metadata.get("termination_reason"),
                "sample_index_origin": "segment_local",
            }
        )
        segments.sort(key=lambda item: int(item.get("part", 0)))
        manifest.update(
            {
                "schema_version": 1,
                "subject_id": metadata.get("subject_id"),
                "session_id": metadata.get("session_id"),
                "task_mode": metadata.get("task_mode"),
                "image_set_label": metadata.get("image_set_label", "default"),
                "image_trials": metadata.get("image_trials"),
                "timestamp_label": metadata.get("timestamp_label"),
                "completed": bool(metadata.get("completed", False)),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "segments": segments,
            }
        )
        temp_path = output_dir / f".eeg_segments.{uuid4().hex}.tmp"
        try:
            with temp_path.open("x", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, manifest_path)
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def _legacy_segment_record(output_dir: Path) -> dict[str, Any]:
        sample_count: int | None = None
        try:
            eeg = np.load(output_dir / "continuous_eeg.npy", mmap_mode="r")
            sample_count = int(eeg.shape[1]) if eeg.ndim == 2 else None
            del eeg
        except Exception:
            pass
        return {
            "part": 1,
            "status": "finalized",
            "eeg_file": "continuous_eeg.npy",
            "events_file": "events.json",
            "metadata_file": "metadata.json",
            "sample_count": sample_count,
            "sample_index_origin": "segment_local",
            "legacy": True,
        }

    @staticmethod
    def _stale_spools(output_dir: Path) -> list[tuple[int, Path]]:
        stale: list[tuple[int, Path]] = []
        legacy = output_dir / ".continuous_eeg.f32.tmp"
        if legacy.exists():
            stale.append((1, legacy))
        pattern = re.compile(r"^\.continuous_eeg_part_(\d{3})\.f32\.tmp$")
        for path in output_dir.iterdir():
            match = pattern.fullmatch(path.name)
            if match:
                stale.append((int(match.group(1)), path))
        return stale

    def to_array(self) -> np.ndarray:
        try:
            self.pull()
        except RuntimeError as exc:
            if not self._is_stream_not_started_error(exc):
                raise
        if not self._chunks:
            return np.empty((self._n_channels, 0), dtype=np.float32)
        return np.concatenate(self._chunks, axis=1).astype(np.float32)

    @staticmethod
    def _is_stream_not_started_error(exc: RuntimeError) -> bool:
        message = str(exc).lower()
        return "not started" in message and "stream" in message
