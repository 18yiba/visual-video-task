"""Continuous session recording helpers for video-EEG experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import time
from pathlib import Path
from typing import Any

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
        self._events: list[SessionEvent] = []
        self._sample_count = 0
        self._started_at = time.monotonic()

    @property
    def sample_count(self) -> int:
        return self._sample_count

    @property
    def events(self) -> list[SessionEvent]:
        return list(self._events)

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
        self._spool_path = output_dir / ".continuous_eeg.f32.tmp"
        self._spool_handle = self._spool_path.open("wb")

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
        if self._spool_path is not None and self._spool_path.exists() and self._sample_count > 0:
            raw = np.memmap(self._spool_path, dtype=np.float32, mode="r", shape=(self._sample_count, self._n_channels))
            target = np.lib.format.open_memmap(
                output_dir / "continuous_eeg.npy", mode="w+", dtype=np.float32,
                shape=(self._n_channels, self._sample_count),
            )
            block = max(1, int(self._sfreq * 10))
            for start in range(0, self._sample_count, block):
                end = min(start + block, self._sample_count)
                target[:, start:end] = raw[start:end].T
            target.flush()
            del target, raw
            self._spool_path.unlink()
        elif self._spool_path is not None and self._spool_path.exists():
            np.save(output_dir / "continuous_eeg.npy", np.empty((self._n_channels, 0), dtype=np.float32))
            self._spool_path.unlink()
        else:
            np.save(output_dir / "continuous_eeg.npy", self.to_array())
        with (output_dir / "events.json").open("w", encoding="utf-8") as handle:
            json.dump([asdict(event) for event in self._events], handle, ensure_ascii=False, indent=2)
        with (output_dir / "metadata.json").open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
        return output_dir

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
