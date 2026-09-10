"""Realtime-friendly EEG preprocessing helpers."""

from __future__ import annotations

import logging

import numpy as np
from scipy.signal import butter, filtfilt

LOGGER = logging.getLogger(__name__)


def common_average_reference(data: np.ndarray) -> np.ndarray:
    """Apply common average reference across channels."""

    channel_mean = np.mean(data, axis=0, keepdims=True)
    return data - channel_mean


def bandpass_filter(
    data: np.ndarray,
    sfreq: float,
    low_hz: float = 8.0,
    high_hz: float = 30.0,
    order: int = 4,
) -> np.ndarray:
    """Apply an IIR band-pass filter."""

    nyquist = sfreq / 2.0
    b, a = butter(order, [low_hz / nyquist, high_hz / nyquist], btype="bandpass")
    return filtfilt(b, a, data, axis=1).astype(np.float32)


def reject_artifacts(data: np.ndarray, clip_uv: float = 150.0) -> np.ndarray:
    """Simple amplitude clipping as a lightweight artifact safeguard."""

    return np.clip(data, -clip_uv, clip_uv)


def filter_and_transform(data: np.ndarray, sfreq: float) -> np.ndarray:
    """Run the default realtime preprocessing stack."""
    
    # Strip trigger channel if present (assuming channel count is e.g. 65 where last is trigger)
    # Most standard models expect exactly 64 channels.
    if data.shape[0] == 65:
        data = data[:64, :]

    referenced = common_average_reference(data)
    filtered = bandpass_filter(referenced, sfreq=sfreq)
    cleaned = reject_artifacts(filtered)
    return cleaned.astype(np.float32)
