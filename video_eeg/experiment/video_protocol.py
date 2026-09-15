"""Shared EEG session recording and marker alignment."""

from __future__ import annotations

import threading
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from video_eeg.devices.base import AbstractAcquirer
from video_eeg.experiment.eeg_health import EegAcquisitionError, SampleWatchdog
from video_eeg.storage.session_recorder import SessionRecorder
from video_eeg.utils.markers import LOCAL_ONLY_EVENT_NAMES, PROTOCOL_EVENT_CODES, MarkerBackend

Heartbeat = Callable[[], None] | None


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
        record_local_eeg: bool = True,
        no_sample_timeout_sec: float = 5.0,
        startup_timeout_sec: float = 10.0,
    ) -> None:
        self._acquirer = acquirer
        self._marker_backend = marker_backend
        self._sfreq = float(sfreq)
        detected_sfreq = float(acquirer.metadata.sfreq)
        if abs(detected_sfreq - self._sfreq) > 0.01:
            raise ValueError(
                f"EEG acquisition rate {detected_sfreq:g} Hz does not match "
                f"the video paradigm expected rate {self._sfreq:g} Hz"
            )
        self._records_dir = records_dir
        self._subject_id = subject_id
        self._session_id = int(session_id)
        self._record_local_eeg = bool(record_local_eeg)
        self._recorder = SessionRecorder(
            acquirer,
            sfreq=self._sfreq,
            n_channels=int(acquirer.metadata.n_channels),
            event_only=not self._record_local_eeg,
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._session_stamp = ""
        self._session_dir: Path | None = None
        self._running = False
        self._start_metadata: dict[str, Any] = {}
        self._background_error: BaseException | None = None
        self._watchdog = SampleWatchdog(time.monotonic(), timeout=no_sample_timeout_sec,
                                       startup_timeout=startup_timeout_sec)
        self._health_thread = None
        self._fault_lock = threading.Lock()
        self._health_file = None
        self._health_error = None
        self._shutdown_errors = []

    @property
    def running(self) -> bool:
        return self._running

    @property
    def session_dir(self) -> Path | None:
        return self._session_dir

    @property
    def recorder(self) -> SessionRecorder:
        return self._recorder

    @property
    def background_error(self) -> BaseException | None:
        return self._background_error

    @property
    def eeg_part(self) -> int:
        return self._recorder.part_index

    @property
    def eeg_filename(self) -> str:
        return self._recorder.eeg_filename

    @property
    def recording_elapsed_sec(self) -> float:
        """Elapsed monotonic time used for converter-compatible behavior timing."""

        return self._recorder.elapsed_sec

    def start(self, *, metadata: dict[str, Any] | None = None, output_dir: Path | None = None) -> Path:
        if self._running:
            raise RuntimeError("EEG session is already running.")

        self._session_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._start_metadata = dict(metadata or {})
        task_mode = str(self._start_metadata.get("task_mode", "")).strip().lower()
        session_layout = str(self._start_metadata.get("session_dir_layout", "")).strip().lower()
        timestamp_label = str(self._start_metadata.get("timestamp_label", "")).strip()
        if timestamp_label:
            self._session_stamp = timestamp_label
        session_folder = f"session_{self._session_id:02d}"
        if task_mode in {"image_a", "image_b"}:
            session_folder = f"{task_mode}_session_{self._session_id:02d}"
        if output_dir is not None:
            self._session_dir = Path(output_dir)
        elif session_layout == "subject_timestamp_session":
            self._session_dir = (
                self._records_dir
                / self._subject_id
                / self._session_stamp
                / f"session_{self._session_id:02d}"
            )
        else:
            self._session_dir = (
                self._records_dir
                / self._subject_id
                / session_folder
                / self._session_stamp
            )
        if self._record_local_eeg:
            self._acquirer.start_stream()
        self._recorder.start_spooling(self._session_dir)
        self._stop_event.clear()
        self._background_error = None
        if self._record_local_eeg:
            self._watchdog.started = self._watchdog.last_sample_time = time.monotonic()
            self._health_file = (self._session_dir / f'eeg_health_part_{self.eeg_part:03d}.jsonl').open('x', encoding='utf-8')
            self._health_thread = threading.Thread(target=self._health_loop, name='video-eeg-health', daemon=True)
            self._health_thread.start()
            self._thread = threading.Thread(
                target=self._pull_loop,
                name="video-eeg-pull",
                daemon=True,
            )
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

    def begin_trial(self, *, trial_idx: int, video_name: str, stim_file: str | None = None) -> None:
        self.emit("trial_start", trial_idx=trial_idx, video_name=video_name, stim_file=stim_file)

    def fixation_on(self, *, trial_idx: int, video_name: str, stim_file: str | None = None) -> None:
        self.emit("fixation_on", trial_idx=trial_idx, video_name=video_name, stim_file=stim_file)

    def fixation_off(self, *, trial_idx: int) -> None:
        self.emit("fixation_off", trial_idx=trial_idx)

    def video_on(self, *, trial_idx: int, video_name: str, stim_file: str | None = None) -> None:
        self.emit("video_on", trial_idx=trial_idx, video_name=video_name, stim_file=stim_file)

    def video_off(self, *, trial_idx: int, video_name: str, stim_file: str | None = None) -> None:
        self.emit("video_off", trial_idx=trial_idx, video_name=video_name, stim_file=stim_file)

    def break_start(self, *, trial_idx: int, video_name: str, stim_file: str | None = None) -> None:
        self.emit("break_start", trial_idx=trial_idx, video_name=video_name, stim_file=stim_file)

    def break_end(self, *, trial_idx: int, video_name: str, stim_file: str | None = None) -> None:
        self.emit("break_end", trial_idx=trial_idx, video_name=video_name, stim_file=stim_file)

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

    def end_trial(self, *, trial_idx: int, video_name: str, stim_file: str | None = None) -> None:
        self.emit("trial_end", trial_idx=trial_idx, video_name=video_name, stim_file=stim_file)

    def stop_and_export(self, *, metadata: dict[str, Any] | None = None) -> Path | None:
        if not self._running:
            return self._session_dir

        if self._background_error is None:
            self.emit("session_end", subject_id=self._subject_id, session_id=self._session_id)
        self._stop_event.set()
        if self._health_thread is not None:
            self._health_thread.join(timeout=2.0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self._record_local_eeg:
            # Freeze before closing a failed SDK: a blocked read may return later.
            self._recorder.freeze()
            try:
                self._acquirer.stop_stream()
            except Exception as exc:
                self._shutdown_errors.append(repr(exc))
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
            "eeg_session_dir": str(self._session_dir),
            "trigger_codes": dict(PROTOCOL_EVENT_CODES),
            "local_only_events": sorted(LOCAL_ONLY_EVENT_NAMES),
            "eeg_part": self._recorder.part_index,
            "eeg_file": self._recorder.eeg_filename or None,
            "local_eeg_recorded": self._record_local_eeg,
            "events_file": self._recorder.events_filename,
            "metadata_file": self._recorder.metadata_filename,
        }
        if self._acquirer.metadata.eeg_channel_count is not None:
            export_metadata.update(
                {
                    "eeg_channel_count": int(
                        self._acquirer.metadata.eeg_channel_count
                    ),
                    "trigger_channel_index": (
                        self._acquirer.metadata.trigger_channel_index
                    ),
                    "trigger_channel_name": (
                        self._acquirer.metadata.trigger_channel_name
                    ),
                }
            )
        export_metadata.update(self._start_metadata)
        if metadata:
            export_metadata.update(metadata)
        if self._background_error is not None:
            export_metadata["termination_reason"] = "eeg_background_error"
            export_metadata["background_error"] = repr(self._background_error)
        export_metadata['eeg_health_monitor'] = dict(enabled=self._record_local_eeg,
            no_sample_timeout_sec=self._watchdog.timeout, startup_timeout_sec=self._watchdog.startup_timeout,
            error=self._health_error, shutdown_errors=self._shutdown_errors,
            measures='sample arrival only; does not measure impedance, battery, or signal quality')
        try:
            self._recorder.export(self._session_dir, metadata=export_metadata, pull_final=False)
        finally:
            self._marker_backend.close()
        return self._session_dir

    def emit(self, event_name: str, **payload: Any) -> None:
        # Preserve abort offsets locally; never send hardware markers after a fault.
        if self._background_error is not None and event_name in {'video_off', 'trial_end'}:
            payload.update(completed=False, eeg_available=False, background_error=repr(self._background_error),
                           external_marker_sent=False, marker_code=None)
            self._recorder.add_event(event_name, **payload)
            return
        self.raise_if_background_failed()
        code = PROTOCOL_EVENT_CODES.get(event_name)
        is_local_only = event_name in LOCAL_ONLY_EVENT_NAMES
        if code is None and not is_local_only:
            raise ValueError(f"Unknown protocol event: {event_name}")
        callback_monotonic = time.perf_counter()
        if is_local_only:
            self._recorder.add_event(
                event_name,
                subject_id=self._subject_id,
                session_id=self._session_id,
                marker_code=None,
                flip_callback_time_monotonic_sec=callback_monotonic,
                marker_send_started_monotonic_sec=None,
                marker_send_completed_monotonic_sec=None,
                marker_backend="local_event_log",
                external_marker_sent=False,
                marker_send_success=None,
                **payload,
            )
            return
        marker_started = time.perf_counter()
        marker_backend = type(self._marker_backend).__name__
        external_marker = marker_backend != "NoOpMarkerBackend"
        event_payload = {
            "subject_id": self._subject_id,
            "session_id": self._session_id,
            "marker_code": code,
            "flip_callback_time_monotonic_sec": callback_monotonic,
            "marker_send_started_monotonic_sec": marker_started,
            "marker_backend": marker_backend,
            "external_marker_sent": external_marker,
            **payload,
        }
        try:
            self._marker_backend.send_event(event_name)
        except BaseException as exc:
            self._recorder.add_event(
                event_name,
                **event_payload,
                marker_send_completed_monotonic_sec=time.perf_counter(),
                marker_send_success=False,
                marker_send_error=repr(exc),
            )
            raise
        self._recorder.add_event(
            event_name,
            **event_payload,
            marker_send_completed_monotonic_sec=time.perf_counter(),
            marker_send_success=True,
        )

    def _pull_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._recorder.pull()
                time.sleep(0.01)
        except BaseException as exc:
            if not self._stop_event.is_set():
                self._latch_fault('acquisition_exception', repr(exc))

    def _latch_fault(self, code, detail, observation=None):
        with self._fault_lock:
            if self._background_error is not None or self._stop_event.is_set():
                return
            self._recorder.freeze()
            self._health_error = dict(code=code, detail=detail, timestamp_unix_sec=time.time(),
                monotonic_sec=time.monotonic(), sample_count=self._recorder.sample_count,
                observation=observation, hardware_cause='unknown')
            self._background_error = EegAcquisitionError(detail)
            self._recorder.add_event('eeg_acquisition_error', **self._health_error)
            # Persist independently of final export and never overwrite another run.
            try:
                path=self._session_dir/f'eeg_error_part_{self.eeg_part:03d}.json'
                with path.open('x',encoding='utf-8') as f:
                    json.dump(self._health_error,f,ensure_ascii=False,indent=2)
            except Exception as exc:
                self._shutdown_errors.append('error log: '+repr(exc))
            self._stop_event.set()

    def _health_loop(self):
        next_log=0.
        last_log_time=time.monotonic();last_log_count=0
        try:
            while not self._stop_event.is_set():
                now=time.monotonic()
                observation=self._watchdog.observe(self._recorder.sample_count,now)
                if now>=next_log or observation['status']!='ok':
                    interval=max(0.,now-last_log_time)
                    delta=observation['sample_count']-last_log_count
                    self._health_file.write(json.dumps(dict(observation, timestamp_unix_sec=time.time(),
                        monotonic_sec=now, relative_time_sec=self._recorder.elapsed_sec,
                        sample_delta=delta, interval_sec=interval,
                        effective_samples_per_sec=delta/interval if interval>0 else None))+'\n')
                    self._health_file.flush();next_log=now+1.
                    last_log_time=now;last_log_count=observation['sample_count']
                if observation['status']!='ok':
                    self._latch_fault('no_samples_timeout',
                        f"连续 {observation['seconds_without_new_samples']:.1f} 秒未收到新的EEG样本（阈值 {observation['timeout_sec']:g} 秒）。设备或数据链路可能中断，具体硬件原因未知。", observation)
                    break
                self._stop_event.wait(.1)
        except Exception as exc:
            self._latch_fault('health_monitor_error',repr(exc))
        finally:
            if self._health_file is not None:self._health_file.close()

    def raise_if_background_failed(self) -> None:
        if self._background_error is not None:
            raise EegAcquisitionError(f"EEG 后台采集失败：{self._background_error}") from self._background_error

    @staticmethod
    def _sleep(duration_sec: float, *, heartbeat: Heartbeat = None) -> None:
        end = time.monotonic() + max(duration_sec, 0.0)
        while time.monotonic() < end:
            if heartbeat is not None:
                heartbeat()
            time.sleep(min(0.05, end - time.monotonic()))

