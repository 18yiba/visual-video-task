"""Neuracle/JellyFish acquisition backend based on the legacy collect code."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

from acquisition.base import AbstractAcquirer, AcquirerMetadata, EEGChunk

LOGGER = logging.getLogger(__name__)


class NeuracleAcquirer(AbstractAcquirer):
    """Wrap `collect.neuracle_api.DataServerThread` behind the unified acquirer API."""

    def __init__(
        self,
        sfreq: float = 250.0,
        n_channels: int = 64,
        buffer_sec: float = 60.0,
        neuracle_host: str = "127.0.0.1",
        neuracle_port: int = 8712,
        ready_timeout_sec: float = 15.0,
    ) -> None:
        from collect.neuracle_api import DataServerThread

        self.metadata = AcquirerMetadata(name="neuracle", sfreq=sfreq, n_channels=n_channels)
        self._host = neuracle_host
        self._port = neuracle_port
        self._ready_timeout_sec = ready_timeout_sec
        self._sample_rate = int(sfreq)
        self._buffer_sec = buffer_sec
        self._server: DataServerThread | None = None

    def start_stream(self) -> None:
        from collect.neuracle_api import DataServerThread

        if self._server is not None:
            # Defensive cleanup to avoid leaking a previous connection state.
            self.stop_stream()

        self._server = DataServerThread(sample_rate=self._sample_rate, t_buffer=self._buffer_sec)
        not_connected = self._server.connect(hostname=self._host, port=self._port)
        if not_connected:
            self._server = None
            raise RuntimeError("Could not connect to JellyFish/Neuracle forwarder")
        started = time.monotonic()
        while not self._server.isReady():
            if time.monotonic() - started > self._ready_timeout_sec:
                self.stop_stream()
                raise RuntimeError(
                    "Timed out waiting for Neuracle stream metadata. "
                    "Check JellyFish forwarding status and sample-rate settings."
                )
            time.sleep(0.1)
        self._server.start()
        detected_channels = int(getattr(self._server, "n_chan", 0))
        module_name = str(getattr(self._server, "moduleName", "unknown"))
        detected_sfreq = float(getattr(self._server, "sample_rate", self.metadata.sfreq))
        LOGGER.info(
            "Neuracle metadata ready: module=%s channels=%s sfreq=%.1fHz",
            module_name,
            detected_channels if detected_channels else self.metadata.n_channels,
            detected_sfreq,
        )
        if detected_channels and self.metadata.n_channels > detected_channels:
            raise RuntimeError(
                f"Configured channels={self.metadata.n_channels} exceeds forwarded channels={detected_channels}"
            )
        LOGGER.info("Neuracle acquisition started at %s:%s", self._host, self._port)

    def stop_stream(self) -> None:
        if self._server is None:
            return

        server = self._server
        self._server = None
        try:
            server.stop()
        finally:
            # Give the underlying socket thread a short window to exit fully
            # before the next reconnect attempt.
            time.sleep(0.1)
        LOGGER.info("Neuracle acquisition stopped")

    def get_chunk(self, window_sec: float) -> EEGChunk:
        if self._server is None:
            raise RuntimeError("Neuracle stream is not started")
        data = self._server.GetBufferData()
        if data.ndim != 2:
            raise RuntimeError(f"Unexpected Neuracle buffer shape: {data.shape}")
        if data.shape[0] < self.metadata.n_channels:
            raise RuntimeError(
                f"Forwarded channel count {data.shape[0]} is lower than configured {self.metadata.n_channels}"
            )
        required = int(window_sec * self.metadata.sfreq)
        if data.shape[1] < required:
            raise RuntimeError(f"Not enough data in ring buffer: {data.shape[1]} < {required}")
        eeg = np.asarray(data[: self.metadata.n_channels, -required:], dtype=np.float32)
        timestamps = np.arange(required, dtype=np.float64) / self.metadata.sfreq
        return eeg, timestamps

    def get_new_samples(self) -> EEGChunk:
        if self._server is None:
            raise RuntimeError("Neuracle stream is not started")
        data = self._server.buffer.getUpdate()
        if data.ndim != 2:
            raise RuntimeError(f"Unexpected Neuracle update shape: {data.shape}")
        if data.size == 0:
            return (
                np.empty((self.metadata.n_channels, 0), dtype=np.float32),
                np.empty((0,), dtype=np.float64),
            )
        eeg = np.asarray(data[: self.metadata.n_channels], dtype=np.float32)
        timestamps = np.arange(eeg.shape[1], dtype=np.float64) / self.metadata.sfreq
        return eeg, timestamps

    def save_full_buffer_npy(self, path: Path) -> Path:
        """Persist the current full forwarded buffer for diagnostics."""

        if self._server is None:
            raise RuntimeError("Neuracle stream is not started")

        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, self._server.GetBufferData().astype(np.float32))
        return path
