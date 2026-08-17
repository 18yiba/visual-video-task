"""EEG session protocol helpers shared by independent experiments."""

from protocol.session_recorder import SessionEvent, SessionRecorder
from protocol.video_protocol import EegSessionManager

__all__ = [
    "EegSessionManager",
    "SessionEvent",
    "SessionRecorder",
]
