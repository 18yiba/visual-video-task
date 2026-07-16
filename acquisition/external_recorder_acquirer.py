"""Acquirer placeholder for EEG recorded externally by the BCIGo desktop app."""

from __future__ import annotations

import numpy as np

from acquisition.base import AbstractAcquirer, AcquirerMetadata, EEGChunk


class ExternalRecorderAcquirer(AbstractAcquirer):
    """Expose device metadata without opening a second EEG connection.

    BCIGo owns the hardware connection and writes the EDF file. The experiment
    publishes LSL markers and keeps only its local behavioral/event timeline.
    """

    def __init__(
        self,
        sfreq: float = 250.0,
        n_channels: int = 32,
        buffer_sec: float = 60.0,
        backend_name: str = "brainco_bcigo",
    ) -> None:
        del buffer_sec
        self.metadata = AcquirerMetadata(
            name=str(backend_name).strip() or "brainco_bcigo",
            sfreq=float(sfreq),
            n_channels=int(n_channels),
        )
        self._started = False

    def start_stream(self) -> None:
        self._started = True

    def stop_stream(self) -> None:
        self._started = False

    def get_chunk(self, window_sec: float) -> EEGChunk:
        del window_sec
        raise RuntimeError("EEG is recorded externally by BCIGo; no local EEG stream is available.")

    def get_new_samples(self) -> EEGChunk:
        empty_data = np.empty((self.metadata.n_channels, 0), dtype=np.float32)
        empty_timestamps = np.empty((0,), dtype=np.float64)
        return empty_data, empty_timestamps
