"""EEG session protocol helpers shared by independent experiments."""

from video_eeg.storage.session_recorder import SessionEvent, SessionRecorder
from video_eeg.experiment.video_protocol import EegSessionManager

__all__ = [
    "EegSessionManager",
    "SessionEvent",
    "SessionRecorder",
]

