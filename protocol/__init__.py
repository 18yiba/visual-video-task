"""Video-EEG experiment protocol helpers."""

from protocol.session_recorder import SessionEvent, SessionRecorder
from protocol.video_protocol import EegSessionManager, VideoProtocolConfig

__all__ = [
    "EegSessionManager",
    "SessionEvent",
    "SessionRecorder",
    "VideoProtocolConfig",
]
