from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from ..models import EEGProfile, RecordingRecord


class EEGSourceAdapter(ABC):
    @abstractmethod
    def profile(self, record: RecordingRecord) -> EEGProfile:
        raise NotImplementedError

    @abstractmethod
    def load_part(self, record: RecordingRecord, index: int) -> np.ndarray:
        """Return one part as channels x times in its declared source unit."""
        raise NotImplementedError

