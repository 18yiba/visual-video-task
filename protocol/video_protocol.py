"""Video-EEG experiment protocol configuration and session management."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from acquisition.base import AbstractAcquirer
from protocol.session_recorder import SessionRecorder
from utils.markers import PROTOCOL_EVENT_CODES, MarkerBackend

Heartbeat = Callable[[], None] | None


@dataclass(slots=True)
class VideoProtocolConfig:
    """Timing and playlist parameters for one video-EEG session."""

    fixation_sec: float
    blank_sec: float
    iti_sec: float
    trials_per_session: int
    baseline_sec: float
    video_dir: str
    random_seed: int
    default_video_sec: float

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> VideoProtocolConfig:
        protocol = dict(config.get("protocol", {}))
        return cls(
            fixation_sec=float(protocol.get("fixation_sec", 1.5)),
            blank_sec=float(protocol.get("blank_sec", 1.0)),
            iti_sec=float(protocol.get("iti_sec", 2.0)),
            trials_per_session=int(protocol.get("trials_per_session", 90)),
            baseline_sec=float(protocol.get("baseline_sec", 60.0)),
            video_dir=str(protocol.get("video_dir", "videos")),
            random_seed=int(protocol.get("random_seed", 17)),
            default_video_sec=float(protocol.get("default_video_sec", 8.0)),
        )


def build_playlist(protocol: VideoProtocolConfig, *, video_files: list[str] | None = None) -> list[str]:
    """Return a shuffled trial playlist."""

    if video_files:
        pool = list(video_files)
    else:
        pool = [f"video_{index:03d}.mp4" for index in range(protocol.trials_per_session)]
    rng = random.Random(protocol.random_seed)
    rng.shuffle(pool)
    return pool[: protocol.trials_per_session]


class EegSessionManager:
    """Background EEG pull loop with hardware trigger + event alignment."""

    def __init__(
        self,
        acquirer: AbstractAcquirer,
        marker_backend: MarkerBackend,
        *,
        sfreq: float,
        records_dir: Path,
        subject_id: str,
        session_id: int,
    ) -> None:
        self._acquirer = acquirer
        self._marker_backend = marker_backend
        self._sfreq = float(sfreq)
        self._records_dir = records_dir
        self._subject_id = subject_id
        self._session_id = int(session_id)
        self._recorder = SessionRecorder(
            acquirer,
            sfreq=self._sfreq,
            n_channels=int(acquirer.metadata.n_channels),
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._session_stamp = ""
        self._session_dir: Path | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def session_dir(self) -> Path | None:
        return self._session_dir

    @property
    def recorder(self) -> SessionRecorder:
        return self._recorder

    def start(self, *, metadata: dict[str, Any] | None = None) -> Path:
        if self._running:
            raise RuntimeError("EEG session is already running.")

        self._session_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_dir = (
            self._records_dir
            / self._subject_id
            / f"session_{self._session_id:02d}"
            / self._session_stamp
        )
        self._acquirer.start_stream()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._pull_loop, name="video-eeg-pull", daemon=True)
        self._thread.start()
        self._running = True
        self.emit("session_start", subject_id=self._subject_id, session_id=self._session_id)
        return self._session_dir

    def run_baseline(self, duration_sec: float, *, heartbeat: Heartbeat = None) -> None:
        if duration_sec <= 0:
            return
        self.emit("baseline_start", duration_sec=duration_sec)
        self._sleep(duration_sec, heartbeat=heartbeat)
        self.emit("baseline_end", duration_sec=duration_sec)

    def begin_trial(self, *, trial_idx: int, video_name: str) -> None:
        self.emit("trial_start", trial_idx=trial_idx, video_name=video_name)

    def fixation_on(self, *, trial_idx: int, video_name: str) -> None:
        self.emit("fixation_on", trial_idx=trial_idx, video_name=video_name)

    def fixation_off(self, *, trial_idx: int) -> None:
        self.emit("fixation_off", trial_idx=trial_idx)

    def video_on(self, *, trial_idx: int, video_name: str) -> None:
        self.emit("video_on", trial_idx=trial_idx, video_name=video_name)

    def video_off(self, *, trial_idx: int, video_name: str) -> None:
        self.emit("video_off", trial_idx=trial_idx, video_name=video_name)

    def blank_on(self, *, trial_idx: int) -> None:
        self.emit("blank_on", trial_idx=trial_idx)

    def blank_off(self, *, trial_idx: int) -> None:
        self.emit("blank_off", trial_idx=trial_idx)

    def rating_on(self, *, trial_idx: int, video_name: str) -> None:
        self.emit("rating_on", trial_idx=trial_idx, video_name=video_name)

    def rating_off(self, *, trial_idx: int) -> None:
        self.emit("rating_off", trial_idx=trial_idx)

    def iti_on(self, *, trial_idx: int) -> None:
        self.emit("iti_on", trial_idx=trial_idx)

    def iti_off(self, *, trial_idx: int) -> None:
        self.emit("iti_off", trial_idx=trial_idx)

    def end_trial(self, *, trial_idx: int, video_name: str) -> None:
        self.emit("trial_end", trial_idx=trial_idx, video_name=video_name)

    def stop_and_export(self, *, metadata: dict[str, Any] | None = None) -> Path | None:
        if not self._running:
            return self._session_dir

        self.emit("session_end", subject_id=self._subject_id, session_id=self._session_id)
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        try:
            self._recorder.pull()
        except RuntimeError:
            pass
        self._acquirer.stop_stream()
        self._running = False

        if self._session_dir is None:
            return None

        export_metadata = {
            "subject_id": self._subject_id,
            "session_id": self._session_id,
            "session_stamp": self._session_stamp,
            "sfreq": self._sfreq,
            "n_channels": int(self._acquirer.metadata.n_channels),
            "device_type": self._acquirer.metadata.name,
            "trigger_codes": dict(PROTOCOL_EVENT_CODES),
        }
        if metadata:
            export_metadata.update(metadata)
        self._recorder.export(self._session_dir, metadata=export_metadata)
        return self._session_dir

    def emit(self, event_name: str, **payload: Any) -> None:
        code = PROTOCOL_EVENT_CODES.get(event_name)
        if code is None:
            raise ValueError(f"Unknown protocol event: {event_name}")
        self._marker_backend.send_event(event_name)
        self._recorder.add_event(event_name, marker_code=code, **payload)

    def _pull_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._recorder.pull()
            except RuntimeError:
                if self._stop_event.is_set():
                    break
                raise
            time.sleep(0.01)

    @staticmethod
    def _sleep(duration_sec: float, *, heartbeat: Heartbeat = None) -> None:
        end = time.monotonic() + max(duration_sec, 0.0)
        while time.monotonic() < end:
            if heartbeat is not None:
                heartbeat()
            time.sleep(min(0.05, end - time.monotonic()))
