"""Standalone PsychoPy video-EEG experiment.

This entry point is intentionally independent from the Image_B experiment and
does not import or launch any Streamlit UI.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import importlib
import json
from pathlib import Path
import random
import subprocess
import sys
import time
import traceback
import tempfile
from typing import Any

import numpy as np

from video_eeg.experiment.video_protocol import EegSessionManager
from video_eeg.utils.video_library import (
    VideoAsset,
    build_balanced_playlist,
    build_fast_valid_playlist,
    build_playlist,
    load_video_library,
)
from video_eeg.utils.session_protocol import (
    SESSION_MANIFEST_VERSION,
    SessionManifestEntry,
    SessionManifest,
    SessionState,
    build_duration_balanced_manifest,
    catalog_with_durations,
    choose_rest_threshold_seconds,
    duration_progress,
    load_state,
    make_arithmetic_question,
    save_state_atomic,
    session_state_path,
    split_formal_duration_exclusions,
)


core: Any = None
event: Any = None
gui: Any = None
visual: Any = None
Keyboard: Any = None

FONT_NAME = "Microsoft YaHei"
BACKGROUND = "black"
FOREGROUND = "white"
MUTED = "#94a3b8"
DEFAULT_CONFIG_FILENAME = "video_config.yaml"
DEMO_CONFIG_FILENAME = "video_demo_config.yaml"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parent
CONFIG_DIR = PACKAGE_ROOT / "config"
_LSL_MARKER_BACKENDS: dict[tuple[str, str, str], Any] = {}

ATTENTION_BUTTON_LAYOUT = {
    "left": {"key": "F", "response": "incorrect", "label": "错误", "fill_color": "#7f1d1d", "line_color": "#f87171"},
    "right": {"key": "J", "response": "correct", "label": "正确", "fill_color": "#166534", "line_color": "#4ade80"},
}


class ExperimentAbort(Exception):
    """Raised when the operator presses Escape."""


@dataclass(slots=True)
class VideoExperimentConfig:
    fixation_sec: float
    video_sec: float
    blank_sec: float
    iti_sec: float
    eyes_open_baseline_sec: float
    eyes_closed_baseline_sec: float
    trials_per_session: int
    random_seed: int
    playlist_mode: str
    attention_enabled: bool = False
    attention_tasks_per_session: int = 18
    num_sessions: int = 17
    rest_min_net_minutes: float = 30.0
    rest_max_net_minutes: float = 45.0
    attention_timeout_sec: float | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "VideoExperimentConfig":
        protocol = dict(config.get("protocol", {}))
        parsed = cls(
            fixation_sec=float(protocol.get("fixation_sec", 1.5)),
            video_sec=float(protocol.get("default_video_sec", 60.0)),
            blank_sec=float(protocol.get("blank_sec", 1.0)),
            # iti_sec is retained for compatibility with existing fixtures.
            # Formal/demo configs expose the clearer post-video name.
            iti_sec=float(protocol.get("post_video_rest_seconds", protocol.get("iti_sec", 2.0))),
            eyes_open_baseline_sec=float(protocol.get("eyes_open_baseline_sec", 60.0)),
            eyes_closed_baseline_sec=float(protocol.get("eyes_closed_baseline_sec", 60.0)),
            trials_per_session=int(protocol.get("trials_per_session", 500)),
            random_seed=int(protocol.get("random_seed", 17)),
            playlist_mode=str(protocol.get("playlist_mode", "balanced")).strip().lower(),
            attention_enabled=_coerce_bool(protocol.get("attention_enabled", False)),
            attention_tasks_per_session=int(protocol.get("attention_tasks_per_session", protocol.get("attention_task_count", 18))),
            num_sessions=int(protocol.get("num_sessions", 17)),
            rest_min_net_minutes=float(protocol.get("rest_min_net_minutes", 30.0)),
            rest_max_net_minutes=float(protocol.get("rest_max_net_minutes", 45.0)),
            attention_timeout_sec=(None if protocol.get("attention_timeout") is None else float(protocol.get("attention_timeout"))),
        )
        for name in (
            "fixation_sec",
            "video_sec",
            "blank_sec",
            "iti_sec",
            "eyes_open_baseline_sec",
            "eyes_closed_baseline_sec",
        ):
            if float(getattr(parsed, name)) < 0:
                raise ValueError(f"protocol.{name} must be non-negative")
        if parsed.video_sec <= 0:
            raise ValueError("protocol.default_video_sec must be positive")
        if parsed.trials_per_session < 0:
            raise ValueError("protocol.trials_per_session must be non-negative")
        if parsed.playlist_mode not in {"balanced", "shuffle", "sequential"}:
            raise ValueError(
                "protocol.playlist_mode must be balanced, shuffle, or sequential"
            )
        if parsed.num_sessions <= 0 or parsed.attention_tasks_per_session < 0:
            raise ValueError("protocol.num_sessions and attention_tasks_per_session are invalid")
        if parsed.rest_min_net_minutes < 0 or parsed.rest_max_net_minutes < parsed.rest_min_net_minutes:
            raise ValueError("rest net-minute range is invalid")
        if parsed.attention_timeout_sec is not None and parsed.attention_timeout_sec <= 0:
            raise ValueError("attention_timeout must be null or positive")
        return parsed


def build_participant_instruction_text(
    *, subject_id: Any, session_id: Any, rest_min_minutes: float, rest_max_minutes: float,
) -> str:
    """Return participant-facing instructions without exposing debug counts."""

    return (
        f"被试编号：{subject_id}\n"
        f"Session：{session_id}\n\n"
        "本实验只进行视频观看和脑电采集，不包含主观评分。\n"
        "完成脑电连接检查后，您将观看一系列视频，每段视频前会先呈现注视点。\n"
        "请认真观看，每个视频都会完整播放。\n\n"
        "每个视频结束后会有短暂休息，可按空格键跳过。连续净观看约 "
        f"{rest_min_minutes:.0f}—{rest_max_minutes:.0f} 分钟后，也会在当前视频完整结束时提示较长休息。\n"
        "休息时可以在页面停留任意时间；按 F 继续，按 J 退出本次 Session。\n"
        "部分视频结束后会随机抽查刚才的视频内容，请按题目页面提示作答。\n"
        "观看期间请保持头部和身体静止，尽量减少眨眼。\n"
        "按 S 只中断当前视频，之后仍需从头完整观看；按 Esc 可紧急安全退出并保存数据。\n\n"
        "按空格键继续。"
    )


def attention_response_for_key(key_name: str) -> str:
    """Map the participant keyboard contract to the stored response value."""

    key = str(key_name).strip().lower()
    if key == "j":
        return "correct"
    if key == "f":
        return "incorrect"
    return ""


def attention_response_is_correct(key_name: str, statement_truth: bool) -> bool | None:
    """Score F=false and J=true according to the participant-facing contract."""

    response = attention_response_for_key(key_name)
    if not response:
        return None
    return response == ("correct" if bool(statement_truth) else "incorrect")


def attention_effective_reaction_time(dwell_time_sec: float, rest_total_sec: float) -> float:
    """Attention RT excluding time spent in the optional rest state."""

    return max(0.0, float(dwell_time_sec) - float(rest_total_sec))


def rest_action_for_key(key_name: str) -> str:
    """Map the rest-page keyboard contract to continue/exit."""

    key = str(key_name).strip().lower()
    if key == "f":
        return "continue"
    if key == "j":
        return "exit"
    if key == "escape":
        return "emergency"
    return ""


@dataclass(slots=True)
class TrialRecord:
    subject_id: str
    session_id: int
    trial_idx: int
    asset_id: str
    rel_path: str
    category: str | None
    media_load_sec: float
    planned_video_sec: float
    actual_video_sec: float
    media_cleanup_sec: float
    video_completed_naturally: bool
    video_skipped: bool
    started_at_unix_sec: float
    completed_at_unix_sec: float
    trial_type: str
    video_file: str
    stim_file: str
    video_duration_sec: float | None
    video_duration_status: str
    fixation_onset: float
    fixation_offset: float
    video_onset: float
    video_offset: float
    break_onset: float
    break_offset: float
    actual_break_sec: float
    break_skipped: bool
    attempt_id: int = 1
    status: str = "completed"
    abort_reason: str = ""
    skip_pressed: bool = False
    session_completed_net_sec: float = 0.0
    eeg_relative_onset_sec: float = 0.0
    eeg_relative_offset_sec: float = 0.0
    eeg_part: int = 1


@dataclass(slots=True)
class AttentionRecord:
    subject_id: str
    session_id: int
    attention_idx: int
    attention_id: int
    scheduled_net_time: float
    actual_trigger_net_time: float
    question_text: str
    operator: str
    operand_a: int
    operand_b: int
    true_result: int
    displayed_result: int
    statement_truth: bool
    response: str
    response_key: str
    response_correct: bool | None
    reaction_time_sec: float | None
    timeout: bool
    page_onset_timestamp: str
    response_timestamp: str
    dwell_time_sec: float
    completed: bool
    aborted: bool
    abort_reason: str


class OpenCVVideoPlayer:
    """Lightweight video player backed by OpenCV frames and PsychoPy ImageStim."""

    def __init__(self, win: Any, filename: str, *, autoLog: bool = False, **_kwargs: Any) -> None:
        import cv2

        if visual is None:
            raise RuntimeError("PsychoPy visual module is not loaded")
        self._cv2 = cv2
        self.win = win
        self.filename = filename
        self._cap = cv2.VideoCapture(filename)
        if not self._cap.isOpened():
            raise RuntimeError(f"无法打开视频文件：{filename}")
        self._fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if not np.isfinite(self._fps) or self._fps <= 0:
            self._fps = 30.0
        self._frame_interval = 1.0 / self._fps
        self._frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self._current_index = -1
        self._start_time = 0.0
        self._next_frame_time = 0.0
        self._finished = False
        self._ended_prematurely = False
        self._size = (1, 1)
        self._image = np.zeros((2, 2, 3), dtype=np.float32)
        self._audio_data: np.ndarray | None = None
        self._audio_rate: int | None = None
        self._audio_temp_path: Path | None = None
        self._audio_started = False
        self._play_started = False
        self._start_scheduled_on_flip = False
        self._stim = visual.ImageStim(
            win,
            image=self._image,
            units="pix",
            autoLog=autoLog,
            interpolate=True,
        )
        self.size = self._probe_initial_size()
        self._prepare_audio()
        self._load_first_frame()

    def _probe_initial_size(self) -> tuple[int, int]:
        width = int(self._cap.get(self._cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(self._cap.get(self._cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if width > 0 and height > 0:
            return (width, height)
        return (1, 1)

    def _load_first_frame(self) -> None:
        self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"无法读取视频首帧：{self.filename}")
        self._current_index = 0
        self._set_frame(frame)

    def _prepare_audio(self) -> None:
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
            import sounddevice as sd
            import soundfile as sf
        except Exception:
            return
        try:
            temp_handle = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            temp_handle.close()
            temp_path = Path(temp_handle.name)
            cmd = [
                get_ffmpeg_exe(),
                "-y",
                "-i",
                self.filename,
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "44100",
                "-ac",
                "2",
                str(temp_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0 or not temp_path.exists() or temp_path.stat().st_size == 0:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return
            data, samplerate = sf.read(str(temp_path), dtype="float32", always_2d=False)
            if data.size == 0:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return
            self._audio_data = data
            self._audio_rate = int(samplerate)
            self._audio_temp_path = temp_path
        except Exception:
            return

    def _start_audio(self) -> None:
        if self._audio_data is None or self._audio_rate is None:
            return
        try:
            import sounddevice as sd

            sd.stop()
            sd.play(self._audio_data, self._audio_rate, blocking=False)
            self._audio_started = True
        except Exception:
            return

    def _begin_playback_on_flip(self) -> None:
        self._start_time = time.perf_counter()
        self._next_frame_time = self._start_time + self._frame_interval
        self._play_started = True
        self._start_scheduled_on_flip = False
        self._start_audio()

    def _stop_audio(self) -> None:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass

    def _set_frame(self, frame: Any) -> None:
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        corrected = np.flipud(rgb)
        self._image = corrected.astype(np.float32) / 255.0
        self._stim.image = self._image
        h, w = corrected.shape[:2]
        self._size = (w, h)

    @property
    def isFinished(self) -> bool:
        return self._finished

    def getVideoSize(self) -> tuple[int, int]:
        return self._size

    def play(self) -> None:
        self._finished = False
        self._ended_prematurely = False
        self._start_time = 0.0
        self._next_frame_time = float("inf")
        self._audio_started = False
        self._play_started = False
        self._start_scheduled_on_flip = False
        self._load_first_frame()

    def pause(self) -> None:
        self._finished = True
        self._stop_audio()

    def stop(self) -> None:
        self._finished = True
        self._stop_audio()

    def unload(self) -> None:
        self._finished = True
        self._stop_audio()
        cap = getattr(self, "_cap", None)
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        self._cap = None
        if self._audio_temp_path is not None:
            try:
                self._audio_temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            self._audio_temp_path = None

    def draw(self) -> None:
        if self._finished:
            return
        if not self._play_started:
            self._stim.size = self.size
            self._stim.draw()
            if not self._start_scheduled_on_flip:
                self.win.callOnFlip(self._begin_playback_on_flip)
                self._start_scheduled_on_flip = True
            return
        now = time.perf_counter()
        elapsed = max(0.0, now - self._start_time)
        target_index = int(elapsed * self._fps)
        if self._frame_count > 0 and target_index >= self._frame_count:
            self._finished = True
            self._stop_audio()
            return
        if target_index > self._current_index:
            frames_to_advance = target_index - self._current_index
            frames_to_advance = min(frames_to_advance, 3)
            frame = None
            ok = False
            for _ in range(frames_to_advance):
                ok, frame = self._cap.read()
                if not ok or frame is None:
                    break
                self._current_index += 1
            if not ok or frame is None:
                self._finished = True
                self._ended_prematurely = True
                self._stop_audio()
                return
            self._set_frame(frame)
        self._stim.size = self.size
        self._stim.draw()


def resolve_config_path(config_path: Path | None = None) -> Path:
    if config_path is not None:
        return Path(config_path).expanduser().resolve()
    cwd_config = Path.cwd() / DEFAULT_CONFIG_FILENAME
    if cwd_config.exists():
        return cwd_config.resolve()
    return (CONFIG_DIR / DEFAULT_CONFIG_FILENAME).resolve()


def load_config(path: Path) -> dict[str, Any]:
    resolved = resolve_config_path(path)
    if not resolved.exists():
        raise RuntimeError(f"未找到视频实验配置文件：{resolved}")
    try:
        import yaml
    except ImportError:
        config = _load_simple_yaml(resolved)
    else:
        with resolved.open("r", encoding="utf-8-sig") as handle:
            config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        raise RuntimeError(f"配置文件必须是键值结构：{resolved}")
    return config


def build_acquirer(*, device_name: str, config: dict[str, Any]) -> Any:
    from video_eeg.devices.factory import AcquirerFactory, register_default_acquirers

    register_default_acquirers()
    device_cfg = dict(config.get("device", {}))
    selected = (
        "dummy"
        if bool(config.get("hardware_dummy_mode", False))
        else str(device_name or config.get("device_type", "brainco")).strip().lower()
    )
    n_channels = 32 if selected == "brainco" else 64
    neuracle_eeg_channels: int | None = None
    neuracle_include_trigger = False
    if selected == "neuracle":
        neuracle_eeg_channels = int(device_cfg.get("neuracle_eeg_channels", 64))
        if neuracle_eeg_channels <= 0:
            raise RuntimeError("device.neuracle_eeg_channels must be positive")
        neuracle_include_trigger = bool(device_cfg.get("neuracle_include_trigger_channel", True))
        n_channels = neuracle_eeg_channels + int(neuracle_include_trigger)
    kwargs: dict[str, Any] = {
        "sfreq": expected_sampling_rate(config),
        "n_channels": n_channels,
        "buffer_sec": float(config.get("buffer_sec", 180.0)),
    }
    factory_name = selected
    if selected == "neuracle":
        kwargs.update(
            {
                "eeg_channel_count": neuracle_eeg_channels,
                "include_trigger_channel": neuracle_include_trigger,
                "neuracle_host": str(device_cfg.get("neuracle_host", "127.0.0.1")),
                "neuracle_port": int(device_cfg.get("neuracle_port", 8712)),
            }
        )
    elif selected == "brainco":
        transport = str(device_cfg.get("brainco_transport", "bcigo")).strip().lower()
        if transport == "bcigo":
            factory_name = "brainco_bcigo"
            kwargs["backend_name"] = "brainco_bcigo"
        elif transport == "lsl":
            factory_name = "brainco_lsl"
            kwargs.update(
                {
                    "stream_name": str(device_cfg.get("brainco_lsl_stream_name", "")),
                    "stream_type": str(device_cfg.get("brainco_lsl_stream_type", "EEG")),
                    "source_id": str(device_cfg.get("brainco_lsl_source_id", "")),
                    "resolve_timeout_sec": float(device_cfg.get("brainco_lsl_resolve_timeout_sec", 15.0)),
                    "ready_timeout_sec": float(device_cfg.get("brainco_lsl_ready_timeout_sec", 10.0)),
                    "backend_name": "brainco_lsl",
                }
            )
        elif transport == "sdk":
            kwargs.update(
                {
                    "brainco_addr": str(device_cfg.get("brainco_addr", "")),
                    "brainco_port": int(device_cfg.get("brainco_port", 0)),
                    "auto_discover": bool(device_cfg.get("brainco_auto_discover", True)),
                    "scan_timeout_sec": float(device_cfg.get("brainco_scan_timeout_sec", 6.0)),
                    "ready_timeout_sec": float(device_cfg.get("brainco_ready_timeout_sec", 20.0)),
                    "start_retries": int(device_cfg.get("brainco_start_retries", 2)),
                    "eeg_gain": int(device_cfg.get("brainco_gain", 6)),
                    "signal_source": str(device_cfg.get("brainco_signal_source", "NORMAL")),
                    "device_id": str(device_cfg.get("brainco_device_id", "bcigo")),
                }
            )
        else:
            raise RuntimeError("device.brainco_transport must be bcigo, lsl, or sdk")
    return AcquirerFactory.create(factory_name, **kwargs)


def build_marker_backend(config: dict[str, Any]) -> Any:
    from video_eeg.utils.markers import (
        CompositeMarkerBackend,
        LSLMarkerBackend,
        NoOpMarkerBackend,
        TriggerBoxMarkerBackend,
    )

    device_cfg = dict(config.get("device", {}))
    backends: list[Any] = []
    serial_port = str(device_cfg.get("trigger_serial_port", "")).strip()
    if serial_port:
        backends.append(
            TriggerBoxMarkerBackend(
                serial_port,
                timeout_sec=float(device_cfg.get("trigger_serial_timeout_sec", 1.5)),
            )
        )
    brainco_marker = (
        str(config.get("device_type", "")).strip().lower() == "brainco"
        and str(device_cfg.get("brainco_transport", "bcigo")).strip().lower() in {"bcigo", "lsl"}
    )
    if brainco_marker and bool(device_cfg.get("lsl_marker_enabled", True)):
        marker_identity = (
            str(device_cfg.get("lsl_marker_stream_name", "video-eeg-Markers")),
            str(device_cfg.get("lsl_marker_stream_type", "Markers")),
            str(device_cfg.get("lsl_marker_source_id", "video-eeg-marker")),
        )
        backend = _LSL_MARKER_BACKENDS.get(marker_identity)
        if backend is None:
            try:
                backend = LSLMarkerBackend(
                    stream_name=marker_identity[0],
                    stream_type=marker_identity[1],
                    source_id=marker_identity[2],
                )
            except ImportError:
                backend = None
            if backend is not None:
                _LSL_MARKER_BACKENDS[marker_identity] = backend
        if backend is None:
            return NoOpMarkerBackend()
        backends.append(backend)
    if not backends:
        return NoOpMarkerBackend()
    if len(backends) == 1:
        return backends[0]
    return CompositeMarkerBackend(*backends)


def uses_bcigo_external_recording(config: dict[str, Any]) -> bool:
    if bool(config.get("hardware_dummy_mode", False)):
        return False
    return (
        str(config.get("device_type", "brainco")).strip().lower() == "brainco"
        and str(config.get("device", {}).get("brainco_transport", "bcigo")).strip().lower()
        == "bcigo"
    )


def _marker_mode(backend: Any) -> str:
    if type(backend).__name__ == "NoOpMarkerBackend":
        return "noop"
    if type(backend).__name__ == "LSLMarkerBackend":
        return "lsl"
    if type(backend).__name__ == "CompositeMarkerBackend":
        return "lsl" if hasattr(backend, "wait_for_consumers") else "trigger_box"
    return "trigger_box"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行独立的 PsychoPy 视频 EEG 实验。")
    parser.add_argument("--config", type=Path, default=None, help="视频实验配置文件，默认 video_config.yaml。")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="使用 video_demo_config.yaml，运行不污染正式进度的快速真人流程测试。",
    )
    parser.add_argument("--subject-id", type=str, default="", help="覆盖配置中的被试编号。")
    parser.add_argument("--session-id", "--session", dest="session_id", type=int, default=0, help="覆盖配置中的 Session 编号（1-17）。")
    parser.add_argument("--windowed", action="store_true", help="使用窗口模式。")
    parser.add_argument("--no-dialog", action="store_true", help="跳过 PsychoPy 启动对话框。")
    parser.add_argument("--dummy-eeg", action="store_true", help="强制使用模拟 EEG。")
    parser.add_argument("--real-eeg", action="store_true", help="强制使用真实 EEG 配置。")
    parser.add_argument("--device-type", choices=["brainco", "neuracle"], default="")
    parser.add_argument("--brainco-transport", choices=["bcigo", "lsl", "sdk"], default="")
    parser.add_argument("--preflight-eeg", action="store_true", help="打开窗口前检查 EEG/Marker 连接。")
    parser.add_argument("--eeg-check-only", action="store_true", help="只检查 EEG/Marker 连接。")
    parser.add_argument("--doctor", action="store_true", help="检查视频实验运行依赖。")
    parser.add_argument("--seed", type=int, default=None, help="显式固定本次随机种子（测试/复现使用）。")
    return parser.parse_args(argv)


def apply_cli_overrides(config: dict[str, Any], args: argparse.Namespace) -> None:
    if args.dummy_eeg and args.real_eeg:
        raise RuntimeError("--dummy-eeg and --real-eeg cannot be used together")
    if args.dummy_eeg:
        config["hardware_dummy_mode"] = True
    if args.real_eeg:
        config["hardware_dummy_mode"] = False
    if args.device_type:
        config["device_type"] = args.device_type
    device_cfg = dict(config.get("device", {}))
    if args.brainco_transport:
        device_cfg["brainco_transport"] = args.brainco_transport
    config["device"] = device_cfg


def expected_sampling_rate(config: dict[str, Any]) -> float:
    """Return the video paradigm's declared rate; never resample EEG."""

    value = config.get("eeg_sampling_rate_hz", config.get("sfreq", 1000.0))
    rate = float(value)
    if rate <= 0:
        raise ValueError("video EEG expected sampling rate must be positive")
    return rate


def _resolve_config_value(config: dict[str, Any], value: str, *, default_base: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path.resolve()
    return (default_base / path).resolve()


def _session_manifest_path(config: dict[str, Any]) -> Path:
    protocol = dict(config.get("protocol", {}))
    return _resolve_config_value(
        config,
        str(protocol.get("session_manifest_path", "video_eeg/config/session_manifest.csv")),
        default_base=PROJECT_ROOT,
    )


def _records_dir(config: dict[str, Any]) -> Path:
    return _resolve_config_value(
        config,
        str(config.get("storage", {}).get("records_dir", "data/sourcedata")),
        default_base=PROJECT_ROOT,
    )


def ensure_session_manifest(config: dict[str, Any], library: Any, *, force_rebuild: bool = False) -> SessionManifest:
    path = _session_manifest_path(config)
    if path.is_file() and not force_rebuild:
        try:
            return SessionManifest.load(path, session_count=VideoExperimentConfig.from_config(config).num_sessions)
        except ValueError:
            # The previous v1 manifest did not exclude the legacy >60-second
            # files and cannot be mixed with new subject/session checkpoints.
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                first = next(csv.DictReader(handle), None)
            if str((first or {}).get("manifest_version") or "") == SESSION_MANIFEST_VERSION:
                raise
            force_rebuild = True
    assets, warnings = catalog_with_durations(library)
    if warnings:
        raise RuntimeError("无法获得正式视频真实 duration：" + "; ".join(warnings[:10]))
    protocol = dict(config.get("protocol", {}))
    maximum_duration_sec = float(protocol.get("formal_max_video_duration_sec", 60.0))
    eligible, excluded = split_formal_duration_exclusions(assets, maximum_duration_sec=maximum_duration_sec)
    exclusion_report = Path(config.get("formal_exclusion_report_path", CONFIG_DIR / "formal_excluded_over_60s.csv"))
    _write_formal_exclusion_report(exclusion_report, excluded)
    manifest = build_duration_balanced_manifest(
        eligible,
        session_count=int(protocol.get("num_sessions", 17)),
        random_seed=int(protocol.get("random_seed", 17)),
        source_library=str(protocol.get("video_library_dir", library.root)),
        source_video_count=len(assets),
        excluded_video_count=len(excluded),
        maximum_duration_sec=maximum_duration_sec,
        bucket_count=int(protocol.get("duration_bucket_count", 5)),
    )
    manifest.write_atomic(path)
    return manifest


def _write_formal_exclusion_report(path: Path, excluded: list[VideoAsset]) -> None:
    """Persist the non-destructive formal-material exclusion list atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["video_id", "filename", "duration_sec", "reason"])
        writer.writeheader()
        for asset in sorted(excluded, key=lambda item: item.rel_path):
            writer.writerow({
                "video_id": asset.asset_id,
                "filename": asset.rel_path,
                "duration_sec": f"{float(asset.duration_sec or 0.0):.6f}",
                "reason": "legacy_formal_max_duration_exceeded_60_sec",
            })
        handle.flush()
    temp_path.replace(path)


def next_incomplete_session(config: dict[str, Any], subject_id: str, *, num_sessions: int) -> int:
    for session_id in range(1, int(num_sessions) + 1):
        state = load_state(session_state_path(_records_dir(config), subject_id, session_id))
        if state is None or not state.session_completed:
            return session_id
    return int(num_sessions)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.doctor:
        return doctor()
    if args.demo and args.config is not None:
        raise RuntimeError("--demo 与 --config 不能同时使用")
    config_path = resolve_config_path(CONFIG_DIR / DEMO_CONFIG_FILENAME if args.demo else args.config)
    config = load_config(config_path)
    config["_project_dir"] = str(PROJECT_ROOT)
    config["_config_dir"] = str(config_path.resolve().parent)
    apply_cli_overrides(config, args)
    if args.demo:
        config["hardware_dummy_mode"] = True
    elif bool(config.get("hardware_dummy_mode", False)):
        raise RuntimeError("正式视频实验禁止使用 Dummy EEG，请使用真实 EEG 配置或 --real-eeg。")
    if args.demo and args.seed is None:
        protocol_config = dict(config.get("protocol", {}))
        protocol_config["random_seed"] = random.SystemRandom().randint(1, 2**31 - 1)
        config["protocol"] = protocol_config
    if args.seed is not None:
        protocol_config = dict(config.get("protocol", {}))
        protocol_config["random_seed"] = int(args.seed)
        config["protocol"] = protocol_config
    config["explicit_run_seed"] = args.seed
    if args.subject_id.strip():
        config["subject_id"] = args.subject_id.strip()
    protocol = VideoExperimentConfig.from_config(config)
    if args.session_id > 0:
        config["session_id"] = args.session_id
    if args.eeg_check_only:
        return run_eeg_check(config, wait_for_enter=False)
    if args.preflight_eeg:
        status = run_eeg_check(config, wait_for_enter=True)
        if status != 0:
            return status

    _load_psychopy()
    startup = startup_dialog(config, protocol, args)
    if startup is None:
        return 0
    config["subject_id"] = startup["subject_id"]
    config["session_id"] = startup["session_id"]

    library = load_video_library(config)
    if args.demo and not library.list_candidate_assets():
        demo_root = PROJECT_ROOT / 'stimuli' / 'demo'
        if not (demo_root / 'question_bank.json').is_file():
            raise RuntimeError('Practice materials missing. Run scripts/install_lab_env_uv.bat first.')
        config['protocol']['video_library_dir'] = str(demo_root)
        config['protocol']['question_bank_path'] = 'stimuli/demo/question_bank.json'
        config['practice_materials'] = True
        library = load_video_library(config)
    runner_class = VideoRunner
    if config.get('protocol', {}).get('question_bank_path'):
        from video_eeg.experiment.ready_question_runner import QuestionVideoRunner, ReadyLibrary, load_questions, question_path
        runner_class = QuestionVideoRunner
        if args.demo:
            library = ReadyLibrary(library, load_questions(question_path(config)))
    playlist_seed = protocol.random_seed + int(config["session_id"])
    requested_trials = protocol.trials_per_session or 10
    try:
        if args.demo and requested_trials > 0 and protocol.playlist_mode == "shuffle":
            playlist, probed_count = build_fast_valid_playlist(
                library,
                trials_per_session=requested_trials,
                random_seed=playlist_seed,
            )
            print(f"Demo 快速选片完成：从 {probed_count} 个候选视频中找到 {len(playlist)} 个合法视频。")
        elif args.demo:
            playlist = build_playlist(library, trials_per_session=requested_trials, random_seed=playlist_seed)
        else:
            manifest = ensure_session_manifest(config, library)
            playlist = manifest.session_assets(int(config["session_id"]))
            if not playlist:
                raise RuntimeError(f"Session {config['session_id']} has no assigned videos")
            config["session_manifest_path"] = str(_session_manifest_path(config))
            config["session_manifest_hash"] = manifest.content_hash
    except RuntimeError as exc:
        print(f"\n视频库检查失败：{exc}\n视频目录：{library.root}\n", file=sys.stderr)
        return 1
    config["playlist_seed"] = playlist_seed
    config["playlist_version"] = "fixed-session-manifest" if not args.demo else "demo-random-playlist"
    missing = [asset.rel_path for asset in playlist if not library.is_available(asset)]
    if missing:
        raise RuntimeError(
            f"Session {config['session_id']:02d}: missing videos={len(missing)}; "
            f"examples={missing[:10]}; manifest={config.get('session_manifest_path', 'Demo sample')}; "
            f"video root={library.root}. Restore the correct library; no videos were skipped."
        )

    window_kwargs: dict[str, Any] = {
        "fullscr": startup["fullscreen"],
        "color": BACKGROUND,
        "units": "height",
        "allowGUI": not startup["fullscreen"],
    }
    win = visual.Window(**window_kwargs)
    runner = runner_class(
        win=win,
        keyboard=Keyboard(),
        config=config,
        protocol=protocol,
        project_dir=PROJECT_ROOT,
        playlist=playlist,
        library=library,
    )
    try:
        runner.run()
    finally:
        win.close()
    core.quit()
    return 0


def startup_dialog(
    config: dict[str, Any],
    protocol: VideoExperimentConfig,
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    subject_default = str(config.get("subject_id", "S001"))
    suggested_session = int(config.get("session_id", 1))
    if args.session_id <= 0 and not bool(config.get("demo_mode", False)) and not args.demo:
        suggested_session = next_incomplete_session(config, subject_default, num_sessions=protocol.num_sessions)
    defaults = {
        "subject_id": subject_default,
        "session_id": suggested_session,
        "fullscreen": not bool(args.windowed),
    }
    if args.no_dialog:
        return defaults
    if gui is None or not hasattr(gui, "Dlg"):
        print("\n请输入本次实验信息（直接按回车使用括号内默认值）：")
        subject_id = input(f"被试编号 [{defaults['subject_id']}]: ").strip() or defaults["subject_id"]
        session_raw = input(f"Session 编号 [{defaults['session_id']}]: ").strip()
        fullscreen_raw = input("全屏显示 [Y/n]: ").strip().lower()
        try:
            session_id = int(session_raw) if session_raw else defaults["session_id"]
        except ValueError as exc:
            raise ValueError("Session 编号必须是整数。") from exc
        if session_id < 1 or session_id > protocol.num_sessions:
            raise ValueError(f"Session 编号必须在 1-{protocol.num_sessions} 范围内")
        return {
            "subject_id": subject_id,
            "session_id": session_id,
            "fullscreen": fullscreen_raw not in {"n", "no", "0"},
        }
    dlg = gui.Dlg(title="PsychoPy 视频 EEG 实验")
    resume_hint = "；默认 Session 为最近一个未完成 Session" if not args.demo else ""
    dlg.addText(f"连续视频观看范式：固定 Session 清单，视频完整播放，无主观评分{resume_hint}。")
    dlg.addField("被试编号", defaults["subject_id"])
    dlg.addField("Session 编号", defaults["session_id"])
    dlg.addField("全屏显示", defaults["fullscreen"])
    values = dlg.show()
    if not dlg.OK:
        return None
    subject_id = str(values[0]).strip() or "S001"
    session_id = int(values[1])
    if session_id < 1 or session_id > protocol.num_sessions:
        raise ValueError(f"Session 编号必须在 1-{protocol.num_sessions} 范围内")
    return {
        "subject_id": subject_id,
        "session_id": session_id,
        "fullscreen": _coerce_bool(values[2]),
    }


class VideoRunner:
    def __init__(
        self,
        *,
        win: Any,
        keyboard: Any,
        config: dict[str, Any],
        protocol: VideoExperimentConfig,
        project_dir: Path,
        playlist: list[VideoAsset],
        library: Any,
    ) -> None:
        self.win = win
        self.keyboard = keyboard
        self.config = config
        self.protocol = protocol
        self.project_dir = project_dir
        self.playlist = playlist
        self.library = library
        self.manager: EegSessionManager | None = None
        self.trial_records: list[TrialRecord] = []
        self.attention_records: list[AttentionRecord] = []
        self._asset_by_id = {asset.asset_id: asset for asset in self.playlist}
        self.state: SessionState | None = None
        self.state_path: Path | None = None
        self.progress_dir: Path | None = None
        demo_mode = bool(self.config.get("demo_mode", False))
        if demo_mode:
            records_dir = _records_dir({**self.config, "storage": {"records_dir": "data/demo_runs"}})
        else:
            records_dir = _records_dir(self.config)
        session_id = int(self.config.get("session_id", 1))
        progress_root = records_dir / str(self.config.get("subject_id", "S001"))
        if demo_mode:
            progress_root = progress_root / f"run_{self.protocol.random_seed}"
        self.progress_dir = progress_root / f"session_{session_id:02d}"
        self.state_path = self.progress_dir / "session_state.json"
        manifest = SessionManifest(
            version=SESSION_MANIFEST_VERSION,
            entries=[
                SessionManifestEntry(session_id=session_id, video_id=asset.asset_id, video_path=asset.rel_path, video_duration_sec=float(asset.duration_sec or self.protocol.video_sec))
                for asset in self.playlist
            ],
        )
        existing = load_state(self.state_path)
        expected_manifest_hash = str(self.config.get("session_manifest_hash", manifest.content_hash))
        if existing is not None:
            expected_task_type = 'video_mcq' if hasattr(self, 'questions') else 'arithmetic'
            if existing.attention_task_type != expected_task_type:
                raise RuntimeError('Saved Session uses a different attention protocol; use a new subject ID or records directory')
            if existing.question_bank_sha256 != getattr(self, 'question_bank_sha256', ''):
                raise RuntimeError('Saved Session uses a different question bank; restore the original bank or use a new subject ID')
            if existing.question_bank_sha256 != getattr(self, 'question_bank_sha256', ''):
                raise RuntimeError('Saved Session uses a different question bank; restore the original bank or use a new subject ID')
            if len(existing.attention_schedule) != (self.protocol.attention_tasks_per_session if self.protocol.attention_enabled else 0):
                raise RuntimeError('Saved Session has a different attention count; use a new subject ID')
            if existing.subject_id != str(self.config.get("subject_id", "S001")) or existing.session_id != session_id:
                raise RuntimeError("Saved Session state belongs to a different subject/session")
            if set(existing.video_ids) != set(self._asset_by_id):
                raise RuntimeError("Saved Session state does not match the fixed session manifest")
            if existing.manifest_version != SESSION_MANIFEST_VERSION:
                raise RuntimeError("Saved Session state uses an obsolete session manifest version; start a new test state")
            if existing.manifest_hash != expected_manifest_hash:
                raise RuntimeError("Saved Session state was created from a different session manifest")
            self.state = existing
        else:
            state_seed = self.protocol.random_seed
            if not demo_mode and self.config.get("explicit_run_seed") is None:
                state_seed = random.SystemRandom().randint(1, 2**63 - 1)
            self.state = SessionState.new(
                subject_id=str(self.config.get("subject_id", "S001")),
                session_id=session_id,
                manifest=manifest,
                assets=self.playlist,
                random_seed=state_seed,
                attention_task_count=(self.protocol.attention_tasks_per_session if self.protocol.attention_enabled else 0),
                rest_min_minutes=self.protocol.rest_min_net_minutes,
                rest_max_minutes=self.protocol.rest_max_net_minutes,
                demo_mode=bool(self.config.get("demo_mode", False)),
                questions=getattr(self, 'questions', None),
            )
            self.state.question_bank_sha256 = getattr(self, 'question_bank_sha256', '')
            self.state.question_bank_sha256 = getattr(self, 'question_bank_sha256', '')
            save_state_atomic(self.state_path, self.state)
        if self.state is not None:
            self.state.manifest_hash = expected_manifest_hash
            save_state_atomic(self.state_path, self.state)
        self.attention_schedule = self.state.attention_schedule
        self._attempt_counter_by_video = {
            video_id: sum(1 for item in self.state.video_attempts if item.get("video_id") == video_id)
            for video_id in self._asset_by_id
        }
        self.completed = False
        self.termination_reason = "running"
        self._run_traceback = ""
        self._phase_started_at = 0.0
        self._current_attempt: dict[str, Any] | None = None
        self.mouse = event.Mouse(win=win) if event is not None else None
        self.message = visual.TextStim(
            win,
            text="",
            color=FOREGROUND,
            font=FONT_NAME,
            height=0.035,
            wrapWidth=1.35,
            alignText="center",
        )
        self.subtitle = visual.TextStim(
            win,
            text="",
            color=MUTED,
            font=FONT_NAME,
            height=0.025,
            pos=(0, -0.10),
            wrapWidth=1.2,
        )
        self.fixation = visual.TextStim(
            win,
            text="+",
            color=FOREGROUND,
            font=FONT_NAME,
            height=0.09,
        )

    def run(self) -> None:
        try:
            self._show_instructions()
            if self.state is not None and self.state.session_completed:
                self.termination_reason = "already_completed"
                self._show_text("该 Session 已完成，未重新播放视频。\n\n按空格键退出。")
                return
            if bool(self.config.get("hardware_dummy_mode", False)):
                self._show_text("即将检查模拟脑电流程。\n\n按空格键继续。")
                connection = self._check_eeg_connection()
                self._show_text(self._connection_success_text(connection))
            else:
                connection = self._run_device_check_screen()
            self._start_eeg(connection)
            self._checkpoint("running")
            if self.state is not None and self.state.continuous_net_video_duration_sec >= self.state.next_rest_threshold_min * 60.0:
                self._maybe_run_rest_prompt()
            trial_idx = len(self.state.video_attempts) + 1 if self.state is not None else 1
            while self.state is None or self.state.queue_video_ids:
                self._check_abort()
                video_id = self.state.queue_video_ids[0] if self.state is not None else self.playlist[trial_idx - 1].asset_id
                asset = self._asset_by_id[video_id]
                if self.state is not None:
                    self.state.current_video_id = video_id
                    self._checkpoint("video_attempt_started")
                completed = self._run_trial(trial_idx, asset)
                if completed:
                    self._run_due_attention_tasks()
                    self._maybe_run_rest_prompt()
                trial_idx += 1
            if self.state is not None and self.state.completed_attention_count < self.protocol.attention_tasks_per_session:
                self._run_due_attention_tasks(force_remaining=True)
            if self.state is not None and not self.state.queue_video_ids and self.state.completed_attention_count == self.protocol.attention_tasks_per_session:
                self.state.session_completed = True
                self.completed = True
                self.termination_reason = "completed"
                self._checkpoint("completed")
            else:
                self.termination_reason = "incomplete"
        except ExperimentAbort:
            if self.termination_reason == "running":
                self.termination_reason = "esc_emergency"
            self._checkpoint(self.termination_reason)
            if self.termination_reason == "rest_exit":
                self._show_text(self._session_exit_text(), wait_for_key=False, duration=2.0)
            else:
                self._show_text("实验已安全中止，正在保存已采集的数据。", wait_for_key=False, duration=1.0)
        except Exception as exc:
            self.termination_reason = "python_exception"
            self._run_traceback = traceback.format_exc()
            self._checkpoint("python_exception")
            self._show_text(f"实验运行出错：\n{exc}\n\n按空格键退出。")
        finally:
            session_dir = self._stop_and_export()
            if session_dir is not None:
                if self._run_traceback:
                    (session_dir / "crash_report.txt").write_text(self._run_traceback, encoding="utf-8")
                self._show_text(f"数据已保存：\n{session_dir}\n\n按空格键退出。")

    def _show_instructions(self) -> None:
        self._show_text(build_participant_instruction_text(
            subject_id=self.config.get("subject_id"),
            session_id=self.config.get("session_id"),
            rest_min_minutes=self.protocol.rest_min_net_minutes,
            rest_max_minutes=self.protocol.rest_max_net_minutes,
        ))

    def _check_eeg_connection(self) -> dict[str, Any]:
        try:
            return probe_eeg_connection(self.config)
        except Exception as exc:
            self._show_text(f"脑电连接检查失败：\n{exc}\n\n按空格键退出。")
            raise ExperimentAbort() from exc

    def _run_device_check_screen(self) -> dict[str, Any]:
        while True:
            self._draw_device_status(
                title="正在检测强脑设备",
                body=(
                    "程序正在通过 BrainCo SDK 检查设备连接和 EEG 数据流。\n\n"
                    "请确认设备已开机、电量充足，并保持靠近电脑。"
                ),
                accent="#facc15",
            )
            self.win.flip()
            try:
                info = probe_eeg_connection(self.config)
            except Exception as exc:
                action = self._device_check_failure_action(str(exc))
                if action == "retry":
                    continue
                raise ExperimentAbort() from exc
            action = self._device_check_success_action(info)
            if action == "start":
                return info

    def _draw_device_status(self, *, title: str, body: str, accent: str) -> None:
        visual.TextStim(
            self.win,
            text=title,
            color=accent,
            font=FONT_NAME,
            height=0.055,
            pos=(0, 0.22),
            wrapWidth=1.35,
            alignText="center",
        ).draw()
        visual.TextStim(
            self.win,
            text=body,
            color=FOREGROUND,
            font=FONT_NAME,
            height=0.032,
            pos=(0, 0.03),
            wrapWidth=1.35,
            alignText="center",
        ).draw()

    def _device_check_success_action(self, info: dict[str, Any]) -> str:
        body = (
            "强脑 SDK 连接成功，并已读到 EEG 样本。正式实验尚未开始。\n\n"
            f"设备：{info.get('device')}\n"
            f"通道数：{info.get('channels')}\n"
            f"采样率：{info.get('sfreq')} Hz\n"
            f"检查样本数：{info.get('samples')}\n\n"
            "确认 BCIGo/采集设备状态正常后，点击“开始实验”或按空格键继续。"
        )
        return self._device_check_action_screen(
            title="设备连接成功",
            body=body,
            accent="#22c55e",
            primary_label="开始实验",
            secondary_label="重新检测",
            primary_key="space",
            secondary_key="r",
        )

    def _device_check_failure_action(self, error_text: str) -> str:
        body = (
            "强脑 SDK 连接失败，正式实验尚未开始。\n\n"
            f"错误信息：{error_text}\n\n"
            "请检查设备电源、连接状态、SDK 服务和电脑网络/蓝牙后重试。"
        )
        return self._device_check_action_screen(
            title="设备连接失败",
            body=body,
            accent="#ef4444",
            primary_label="重试",
            secondary_label="退出",
            primary_key="r",
            secondary_key="escape",
        )

    def _device_check_action_screen(
        self,
        *,
        title: str,
        body: str,
        accent: str,
        primary_label: str,
        secondary_label: str,
        primary_key: str,
        secondary_key: str,
    ) -> str:
        primary_rect = visual.Rect(
            self.win,
            width=0.34,
            height=0.105,
            pos=(-0.21, -0.30),
            fillColor=accent,
            lineColor=accent,
        )
        secondary_rect = visual.Rect(
            self.win,
            width=0.34,
            height=0.105,
            pos=(0.21, -0.30),
            fillColor="#334155",
            lineColor="#64748b",
        )
        primary_text = visual.TextStim(
            self.win,
            text=primary_label,
            color="black" if accent != "#ef4444" else "white",
            font=FONT_NAME,
            height=0.032,
            pos=primary_rect.pos,
        )
        secondary_text = visual.TextStim(
            self.win,
            text=secondary_label,
            color=FOREGROUND,
            font=FONT_NAME,
            height=0.032,
            pos=secondary_rect.pos,
        )
        hint = visual.TextStim(
            self.win,
            text=f"{primary_label}: {primary_key.upper()}    {secondary_label}: {secondary_key.upper()}",
            color=MUTED,
            font=FONT_NAME,
            height=0.022,
            pos=(0, -0.43),
        )
        self._clear_keyboard()
        while True:
            self._draw_device_status(title=title, body=body, accent=accent)
            primary_rect.draw()
            secondary_rect.draw()
            primary_text.draw()
            secondary_text.draw()
            hint.draw()
            self.win.flip()
            keys = self.keyboard.getKeys(["space", "r", "escape"], waitRelease=False, clear=True)
            names = {str(getattr(key, "name", key)).lower() for key in keys}
            if primary_key in names:
                return "start" if primary_label == "开始实验" else "retry"
            if secondary_key in names:
                if secondary_label == "重新检测":
                    return "retry"
                raise ExperimentAbort()
            if "escape" in names:
                raise ExperimentAbort()
            if self.mouse is not None and any(self.mouse.getPressed()):
                if primary_rect.contains(self.mouse):
                    return "start" if primary_label == "开始实验" else "retry"
                if secondary_rect.contains(self.mouse):
                    if secondary_label == "重新检测":
                        return "retry"
                    raise ExperimentAbort()
                self.mouse.clickReset()
            core.wait(0.02)

    def _connection_success_text(self, info: dict[str, Any]) -> str:
        if info.get("recording_mode") == "bcigo_external_edf":
            return (
                "BCIGo 已连接视频实验 LSL Marker。\n\n"
                "请确认 BCIGo 正在录制 EDF。\n"
                f"Marker 流：{info.get('marker_stream')}\n\n"
                "按空格键开始本 Session。"
            )
        return (
            "脑电连接检查通过。\n\n"
            f"设备：{info.get('device')}\n"
            f"通道数：{info.get('channels')}\n"
            f"采样率：{info.get('sfreq')} Hz\n"
            f"检查样本数：{info.get('samples')}\n\n"
            "按空格键开始本 Session。"
        )

    def _start_eeg(self, connection: dict[str, Any]) -> None:
        acquirer = build_acquirer(
            device_name=str(self.config.get("device_type", "brainco")),
            config=self.config,
        )
        marker_backend = build_marker_backend(self.config)
        records_dir = self.project_dir / Path(
            str(self.config.get("storage", {}).get("records_dir", "video_records_storage"))
        )
        self.manager = EegSessionManager(
            acquirer,
            marker_backend,
            sfreq=expected_sampling_rate(self.config),
            records_dir=records_dir,
            subject_id=str(self.config.get("subject_id", "S001")),
            session_id=int(self.config.get("session_id", 1)),
            record_local_eeg=not uses_bcigo_external_recording(self.config),
        )
        session_dir = self.manager.start(
            metadata={
                "task_mode": "video",
                "psychopy_runner": True,
                "video_trials": len(self.playlist),
                "num_sessions": self.protocol.num_sessions,
                "attention_enabled": self.protocol.attention_enabled,
                "attention_tasks_per_session": self.protocol.attention_tasks_per_session,
                "attention_schedule": self.attention_schedule,
                "session_manifest_path": self.config.get("session_manifest_path"),
                "session_manifest_hash": self.config.get("session_manifest_hash"),
                "video_default_duration_sec": None,
                "baseline_enabled": False,
                "fixation_duration_sec": self.protocol.fixation_sec,
                "rest_min_net_minutes": self.protocol.rest_min_net_minutes,
                "rest_max_net_minutes": self.protocol.rest_max_net_minutes,
                "video_min_duration_sec": 5.0,
                "video_max_duration_sec": 60.0,
                "video_root": str(self.library.root),
                "playlist_seed": int(self.config.get("playlist_seed", self.protocol.random_seed + int(self.config.get("session_id", 1)))),
                "playlist_mode": self.protocol.playlist_mode,
                "demo_mode": bool(self.config.get("demo_mode", False)),
                "eeg_mode": "dummy" if bool(self.config.get("hardware_dummy_mode", False)) else "real",
                "marker_mode": _marker_mode(marker_backend),
                "eeg_connection_check": connection,
                "expected_sampling_rate_hz": expected_sampling_rate(self.config),
                "eeg_recording_mode": (
                    "bcigo_external_edf"
                    if uses_bcigo_external_recording(self.config)
                    else "local_continuous_eeg"
                ),
            }
        )
        playlist_path = session_dir / "video_playlist.json"
        playlist_tmp = playlist_path.with_name(playlist_path.name + ".tmp")
        with playlist_tmp.open("w", encoding="utf-8") as handle:
            json.dump(
                [asset.to_mapping() for asset in self.playlist],
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.flush()
        playlist_tmp.replace(playlist_path)

    def _run_baselines(self) -> None:
        manager = self._require_manager()
        self._show_text(
            f"即将采集睁眼基线 {self.protocol.eyes_open_baseline_sec:.0f} 秒。\n\n"
            "请睁眼注视中央十字，保持放松和静止。\n\n按空格键开始。"
        )
        self._run_baseline_phase(
            symbol="+",
            subtitle="睁眼基线：请注视中央并保持静止",
            duration_sec=self.protocol.eyes_open_baseline_sec,
            start_event="eyes_open_baseline_start",
            end_event="eyes_open_baseline_end",
        )
        self._show_text(
            f"睁眼基线完成。\n\n即将采集闭眼基线 {self.protocol.eyes_closed_baseline_sec:.0f} 秒。\n"
            "请先按空格键，然后立即闭眼并保持放松和静止。"
        )
        self._run_baseline_phase(
            symbol="",
            subtitle="",
            duration_sec=self.protocol.eyes_closed_baseline_sec,
            start_event="eyes_closed_baseline_start",
            end_event="eyes_closed_baseline_end",
        )
        self._show_text("基线采集完成，请睁眼。\n\n按空格键开始视频观看。")

    def _run_baseline_phase(
        self,
        *,
        symbol: str,
        subtitle: str,
        duration_sec: float,
        start_event: str,
        end_event: str,
    ) -> None:
        manager = self._require_manager()
        if symbol:
            self.message.text = symbol
            self.message.height = 0.09
            self.message.pos = (0, 0.02)
            self.message.draw()
        if subtitle:
            self.subtitle.text = subtitle
            self.subtitle.draw()
        self.win.callOnFlip(self._set_phase_started_at)
        if start_event == "eyes_open_baseline_start":
            self.win.callOnFlip(
                manager.emit,
                "baseline_start",
                duration_sec=(
                    self.protocol.eyes_open_baseline_sec
                    + self.protocol.eyes_closed_baseline_sec
                ),
                baseline_design="eyes_open_then_eyes_closed",
            )
        self.win.callOnFlip(manager.emit, start_event, duration_sec=duration_sec)
        self.win.flip()
        self._wait_until(self._phase_started_at + duration_sec)
        self.win.callOnFlip(manager.emit, end_event, duration_sec=duration_sec)
        if end_event == "eyes_closed_baseline_end":
            self.win.callOnFlip(
                manager.emit,
                "baseline_end",
                eyes_open_duration_sec=self.protocol.eyes_open_baseline_sec,
                eyes_closed_duration_sec=self.protocol.eyes_closed_baseline_sec,
            )
        self.win.flip()

    def _run_trial(self, trial_idx: int, asset: VideoAsset) -> bool:
        manager = self._require_manager()
        trial_started = time.time()
        stim_file = asset.rel_path
        fixation_onset = time.perf_counter()
        self.fixation.draw()
        self.win.callOnFlip(
            manager.begin_trial,
            trial_idx=trial_idx,
            video_name=asset.asset_id,
            stim_file=stim_file,
        )
        self.win.callOnFlip(
            manager.fixation_on,
            trial_idx=trial_idx,
            video_name=asset.asset_id,
            stim_file=stim_file,
        )
        self.win.flip()
        self._wait_until(time.perf_counter() + self.protocol.fixation_sec)
        fixation_offset = time.perf_counter()

        media_path = self.library.resolve(asset)
        media_load_started = time.perf_counter()
        movie = self._create_movie(media_path)
        media_load_sec = time.perf_counter() - media_load_started
        planned_duration = asset.duration_sec
        self.win.callOnFlip(manager.fixation_off, trial_idx=trial_idx)
        self.win.callOnFlip(movie.play)
        self.win.callOnFlip(self._set_phase_started_at)
        self.win.callOnFlip(
            manager.emit,
            "video_on",
            trial_idx=trial_idx,
            video_name=asset.asset_id,
            stim_file=stim_file,
            planned_duration_sec=planned_duration,
        )
        self.win.flip()
        video_onset = time.perf_counter()
        eeg_relative_onset_sec = float(getattr(manager, "recording_elapsed_sec", 0.0))

        skipped = False
        completed_naturally = False
        abort_reason = ""
        status = "running"
        try:
            while True:
                keys = self.keyboard.getKeys(["escape", "s"], waitRelease=False, clear=True)
                names = {str(getattr(key, "name", key)).lower() for key in keys}
                elapsed = time.perf_counter() - self._phase_started_at
                if "escape" in names:
                    abort_reason = "esc"
                    status = "aborted"
                    break
                if "s" in names:
                    skipped = True
                    abort_reason = "s_skip"
                    status = "skipped"
                    break
                if bool(getattr(movie, "isFinished", False)):
                    completed_naturally = True
                    status = "completed"
                    break
                if planned_duration is not None and elapsed >= max(0.0, planned_duration - 0.25):
                    completed_naturally = True
                    status = "completed"
                    break
                try:
                    movie.draw()
                    self.win.flip()
                except RuntimeError as exc:
                    message = str(exc)
                    if "Failed to return a frame after multiple attempts" in message or "End of file" in message:
                        completed_naturally = True
                        status = "completed"
                        break
                    abort_reason = "playback_error"
                    status = "aborted"
                    print(f"视频播放异常，已记录为 aborted：{asset.rel_path}: {message}")
                    break
                except Exception as exc:
                    abort_reason = "playback_error"
                    status = "aborted"
                    print(f"视频播放异常，已记录为 aborted：{asset.rel_path}: {exc}")
                    break
        except ExperimentAbort:
            abort_reason = "esc"
            status = "aborted"
        actual_duration = max(0.0, time.perf_counter() - self._phase_started_at)
        video_offset = time.perf_counter()
        eeg_relative_offset_sec = float(getattr(manager, "recording_elapsed_sec", 0.0))
        stop_playback = getattr(movie, "pause", None) or movie.stop
        self.win.callOnFlip(stop_playback)
        self.win.callOnFlip(
            manager.emit,
            "video_off",
            trial_idx=trial_idx,
            video_name=asset.asset_id,
            stim_file=stim_file,
            actual_duration_sec=actual_duration,
            completed_naturally=completed_naturally,
            skipped=skipped,
            status=status,
            abort_reason=abort_reason,
        )
        self.message.text = "正在保存本次视频 attempt…"
        self.message.height = 0.035
        self.message.pos = (0, 0)
        self.message.draw()
        self.win.callOnFlip(
            manager.emit,
            "trial_end",
            trial_idx=trial_idx,
            video_name=asset.asset_id,
            stim_file=stim_file,
            status=status,
            completed=completed_naturally,
        )
        self.win.flip()
        cleanup_started = time.perf_counter()
        try:
            player = getattr(movie, "_player", None)
            if (
                player is not None
                and hasattr(player, "_cleanupAudioTrack")
                and not hasattr(player, "_cleanUpAudioTrack")
            ):
                player._cleanUpAudioTrack = player._cleanupAudioTrack
            if player is not None and not hasattr(movie, "_freePlayer"):
                movie.stop()
            else:
                movie.unload()
        except (AttributeError, RuntimeError):
            if hasattr(movie, "_isLoaded"):
                movie._isLoaded = False
            if hasattr(movie, "_player"):
                movie._player = None
        else:
            if hasattr(movie, "_isLoaded"):
                movie._isLoaded = False
            if hasattr(movie, "_player"):
                movie._player = None
        media_cleanup_sec = time.perf_counter() - cleanup_started

        next_completed_sec = self._state_completed_duration() + (float(planned_duration or 0.0) if completed_naturally else 0.0)
        record = TrialRecord(
                subject_id=str(self.config.get("subject_id", "S001")),
                session_id=int(self.config.get("session_id", 1)),
                trial_idx=trial_idx,
                asset_id=asset.asset_id,
                rel_path=asset.rel_path,
                category=asset.category,
                media_load_sec=media_load_sec,
                planned_video_sec=planned_duration,
                actual_video_sec=actual_duration,
                media_cleanup_sec=media_cleanup_sec,
                video_completed_naturally=completed_naturally,
                video_skipped=skipped,
                started_at_unix_sec=trial_started,
                completed_at_unix_sec=time.time(),
                # The converter preserves BIDS' standard trial_type column, so
                # encode attempt status there while retaining the detailed
                # status/abort_reason fields in the source log.
                trial_type=(
                    "video_completed"
                    if completed_naturally
                    else ("video_skipped" if skipped else "video_aborted")
                ),
                video_file=asset.rel_path,
                stim_file=stim_file,
                video_duration_sec=asset.duration_sec,
                video_duration_status=asset.duration_status,
                fixation_onset=fixation_onset,
                fixation_offset=fixation_offset,
                video_onset=video_onset,
                video_offset=video_offset,
                break_onset=0.0,
                break_offset=0.0,
                actual_break_sec=0.0,
                break_skipped=not completed_naturally,
                attempt_id=self._next_attempt_id(asset.asset_id),
                status=status,
                abort_reason=abort_reason,
                skip_pressed=skipped,
                session_completed_net_sec=next_completed_sec,
                eeg_relative_onset_sec=eeg_relative_onset_sec,
                eeg_relative_offset_sec=eeg_relative_offset_sec,
                eeg_part=int(getattr(manager, "eeg_part", 1)),
            )
        self.trial_records.append(record)
        self._record_video_attempt(record, completed_naturally=completed_naturally, skipped=skipped)
        self._write_trial_log()
        if status == "aborted" and abort_reason == "esc":
            raise ExperimentAbort()
        if completed_naturally:
            self._run_post_video_rest(trial_idx=trial_idx, asset=asset, record=record)
        return completed_naturally

    def _next_attempt_id(self, video_id: str) -> int:
        if hasattr(self, "_attempt_counter_by_video"):
            value = int(self._attempt_counter_by_video.get(video_id, 0)) + 1
            self._attempt_counter_by_video[video_id] = value
            return value
        return 1

    def _state_completed_duration(self) -> float:
        state = getattr(self, "state", None)
        return float(state.completed_net_video_duration_sec) if state is not None else 0.0

    def _checkpoint(self, reason: str) -> None:
        state = getattr(self, "state", None)
        path = getattr(self, "state_path", None)
        if state is not None and path is not None:
            state.last_exit_reason = str(reason)
            state.latest_resume_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            self._write_session_summary()
            save_state_atomic(path, state, last_exit_reason=reason)

    def _record_video_attempt(self, record: TrialRecord, *, completed_naturally: bool, skipped: bool) -> None:
        state = getattr(self, "state", None)
        if state is None:
            return
        video_id = record.asset_id
        state.video_attempts.append({
            **asdict(record),
            "video_id": video_id,
            "completed": completed_naturally,
            # eeg-bids-converter consumes these stable relative timing aliases;
            # the existing video_onset/video_offset fields remain unchanged.
            "image_onset": record.eeg_relative_onset_sec,
            "image_offset": record.eeg_relative_offset_sec,
        })
        if completed_naturally:
            state.commit_completed_video(video_id, float(record.planned_video_sec or 0.0))
        elif skipped:
            state.requeue_skipped_video(video_id)
        else:
            state.preserve_aborted_video(video_id)
        self._checkpoint("video_completed" if completed_naturally else ("video_skipped" if skipped else record.abort_reason or "video_aborted"))

    def _run_post_video_rest(self, *, trial_idx: int, asset: VideoAsset, record: TrialRecord) -> None:
        """Allow Space to end the short rest early after a natural EOF."""

        duration_sec = max(0.0, float(self.protocol.iti_sec))
        if duration_sec <= 0.0:
            record.break_skipped = True
            return
        manager = self._require_manager()
        self._clear_keyboard()
        self.message.text = "请短暂休息，随后继续观看。\n\n按空格键可立即继续。"
        self.message.height = 0.04
        self.message.pos = (0, 0)
        self.message.draw()
        self.win.callOnFlip(
            manager.break_start,
            trial_idx=trial_idx,
            video_name=asset.asset_id,
            stim_file=asset.rel_path,
        )
        self.win.flip()
        break_onset = time.perf_counter()
        break_skipped = False
        deadline = break_onset + duration_sec
        while time.perf_counter() < deadline:
            keys = self.keyboard.getKeys(["escape", "space"], waitRelease=False, clear=True)
            names = [str(getattr(key, "name", key)).lower() for key in keys]
            if "escape" in names:
                raise ExperimentAbort()
            if "space" in names:
                break_skipped = True
                break
            core.wait(min(0.01, max(0.0, deadline - time.perf_counter())))
        break_offset = time.perf_counter()
        self.win.callOnFlip(
            manager.break_end,
            trial_idx=trial_idx,
            video_name=asset.asset_id,
            stim_file=asset.rel_path,
        )
        self.win.flip()
        record.break_onset = break_onset
        record.break_offset = break_offset
        record.actual_break_sec = max(0.0, break_offset - break_onset)
        record.break_skipped = break_skipped
        state = getattr(self, "state", None)
        if state is not None and state.video_attempts:
            state.video_attempts[-1].update({
                "break_onset": record.break_onset,
                "break_offset": record.break_offset,
                "actual_break_sec": record.actual_break_sec,
                "break_skipped": break_skipped,
            })
        self._write_trial_log()
        self._checkpoint("post_video_rest_skipped" if break_skipped else "post_video_rest_completed")

    def _run_due_attention_tasks(self, *, force_remaining: bool = False) -> None:
        state = getattr(self, "state", None)
        if state is None:
            return
        for item in state.attention_schedule:
            attention_id = int(item["attention_id"])
            if attention_id in state.completed_attention_ids:
                continue
            due = force_remaining or state.completed_net_video_duration_sec >= float(item["scheduled_net_time_sec"])
            if not due:
                continue
            self._run_attention_task(schedule_item=item)

    def _run_attention_task(self, *, schedule_item: dict[str, Any]) -> bool:
        manager = self._require_manager()
        attention_idx = int(schedule_item["attention_id"])
        question = str(schedule_item["question_text"])
        statement_truth = bool(schedule_item["statement_truth"])
        self._clear_keyboard()
        if self.mouse is not None:
            self.mouse.clickReset()
        left = ATTENTION_BUTTON_LAYOUT["left"]
        right = ATTENTION_BUTTON_LAYOUT["right"]
        incorrect_rect = visual.Rect(self.win, width=0.34, height=0.12, pos=(-0.22, -0.25), fillColor=left["fill_color"], lineColor=left["line_color"])
        correct_rect = visual.Rect(self.win, width=0.34, height=0.12, pos=(0.22, -0.25), fillColor=right["fill_color"], lineColor=right["line_color"])
        incorrect_text = visual.TextStim(self.win, text=f"{left['key']}\n{left['label']}", color=FOREGROUND, font=FONT_NAME, height=0.032, pos=incorrect_rect.pos)
        correct_text = visual.TextStim(self.win, text=f"{right['key']}\n{right['label']}", color=FOREGROUND, font=FONT_NAME, height=0.032, pos=correct_rect.pos)
        self.message.text = question
        self.message.height = 0.042
        self.message.pos = (0, 0.16)
        def draw_attention_page(resting: bool = False) -> None:
            self.message.draw()
            correct_rect.draw(); incorrect_rect.draw(); correct_text.draw(); incorrect_text.draw()
            self.subtitle.text = (
                "休息中，再按 Space 继续答题\nF/J 暂不作答"
                if resting else
                "如需休息，可停留在此页面，按 Space 开始/结束休息。\nF = 错误　　 J = 正确"
            )
            self.subtitle.draw()

        draw_attention_page()
        self.win.callOnFlip(
            manager.emit,
            "attention_task_on",
            attention_idx=attention_idx,
            question=question,
            scheduled_net_time_sec=float(schedule_item["scheduled_net_time_sec"]),
        )
        self.win.flip()
        onset = time.perf_counter()
        page_onset_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        response = ""
        response_key = ""
        response_rt: float | None = None
        timeout = False
        resting = False
        rest_started: float | None = None
        rest_total = 0.0
        while True:
            # Waiting for release prevents a held Space key from toggling twice.
            keys = self.keyboard.getKeys(["escape", "f", "j", "space"], waitRelease=True, clear=True)
            names = [str(getattr(key, "name", key)).lower() for key in keys]
            if "escape" in names:
                dwell = max(0.0, time.perf_counter() - onset)
                self._append_attention_record(
                    schedule_item, response="", response_key="escape", response_correct=None,
                    reaction_time_sec=None, timeout=False, page_onset_timestamp=page_onset_timestamp,
                    response_timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"), dwell_time_sec=dwell,
                    completed=False, aborted=True, abort_reason="esc",
                )
                self.termination_reason = "esc_emergency"
                raise ExperimentAbort()
            if "space" in names:
                now = time.perf_counter()
                if resting:
                    rest_total += max(0.0, now - (rest_started or now))
                    rest_started = None
                    resting = False
                else:
                    rest_started = now
                    resting = True
                draw_attention_page(resting)
                self.win.flip()
                continue
            if resting:
                # F/J are deliberately ignored while the participant rests.
                core.wait(0.005)
                continue
            pressed = next((name for name in names if name in {"f", "j"}), "")
            if pressed:
                response_key = pressed.upper()
                response = attention_response_for_key(pressed)
                offset = time.perf_counter()
                response_rt = attention_effective_reaction_time(offset - onset, rest_total)
                break
            core.wait(0.005)
        offset = time.perf_counter()
        response_correct = attention_response_is_correct(response_key, statement_truth)
        dwell = max(0.0, offset - onset)
        self.win.callOnFlip(
            manager.emit,
            "attention_response",
            attention_idx=attention_idx,
            response=response,
            correct=response_correct,
            response_rt_sec=response_rt,
            timeout=timeout,
        )
        self.win.flip()
        self._append_attention_record(
            schedule_item, response=response, response_key=response_key, response_correct=response_correct,
            reaction_time_sec=response_rt, timeout=timeout, page_onset_timestamp=page_onset_timestamp,
            response_timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"), dwell_time_sec=dwell,
            completed=True, aborted=False, abort_reason="",
        )
        return True

    def _append_attention_record(self, item: dict[str, Any], **values: Any) -> None:
        state = getattr(self, "state", None)
        attention_id = int(item["attention_id"])
        row = {
            "subject_id": str(self.config.get("subject_id", "S001")),
            "session_id": int(self.config.get("session_id", 1)),
            "attention_idx": attention_id,
            "attention_id": attention_id,
            "scheduled_net_time": float(item["scheduled_net_time_sec"]),
            "actual_trigger_net_time": self._state_completed_duration(),
            **item,
            **values,
        }
        self.attention_records.append(AttentionRecord(
            subject_id=row["subject_id"], session_id=row["session_id"], attention_idx=attention_id, attention_id=attention_id,
            scheduled_net_time=row["scheduled_net_time"], actual_trigger_net_time=row["actual_trigger_net_time"],
            question_text=row["question_text"], operator=row["operator"], operand_a=int(row["operand_a"]),
            operand_b=int(row["operand_b"]), true_result=int(row["true_result"]), displayed_result=int(row["displayed_result"]),
            statement_truth=bool(row["statement_truth"]), response=str(row["response"]), response_key=str(row["response_key"]),
            response_correct=row["response_correct"], reaction_time_sec=row["reaction_time_sec"], timeout=bool(row["timeout"]),
            page_onset_timestamp=str(row["page_onset_timestamp"]), response_timestamp=str(row["response_timestamp"]),
            dwell_time_sec=float(row["dwell_time_sec"]), completed=bool(row["completed"]), aborted=bool(row["aborted"]),
            abort_reason=str(row["abort_reason"]),
        ))
        if state is not None:
            state.attention_attempts.append(row)
            if bool(values.get("completed")) and attention_id not in state.completed_attention_ids:
                state.completed_attention_ids.append(attention_id)
            self._checkpoint("attention_completed" if bool(values.get("completed")) else "attention_aborted")
        self._write_attention_log()

    def _maybe_run_rest_prompt(self) -> None:
        state = getattr(self, "state", None)
        if state is None or not state.queue_video_ids:
            return
        threshold_sec = float(state.next_rest_threshold_min) * 60.0
        if state.continuous_net_video_duration_sec < threshold_sec:
            return
        self._run_rest_page()

    def _run_rest_page(self) -> None:
        state = self._require_state()
        manager = self._require_manager()
        rest_index = state.rest_index + 1
        trigger_net_min = state.continuous_net_video_duration_sec / 60.0
        page_onset = 0.0
        page_onset_timestamp = ""
        continue_rect = visual.Rect(self.win, width=0.38, height=0.14, pos=(-0.23, -0.28), fillColor="#166534", lineColor="#4ade80")
        exit_rect = visual.Rect(self.win, width=0.38, height=0.14, pos=(0.23, -0.28), fillColor="#7f1d1d", lineColor="#f87171")
        continue_text = visual.TextStim(self.win, text="继续（F）", color=FOREGROUND, font=FONT_NAME, height=0.04, pos=continue_rect.pos)
        exit_text = visual.TextStim(self.win, text="退出（J）", color=FOREGROUND, font=FONT_NAME, height=0.04, pos=exit_rect.pos)
        self._clear_keyboard()
        rest_started = False
        while True:
            self.message.text = (
                f"您已连续观看 {trigger_net_min:.1f} 分钟。\n\n"
                "如需休息，可以停留在此页面。\n"
                "休息结束后请选择“继续”；如希望结束本次实验，请选择“退出”。"
            )
            self.message.height = 0.032
            self.message.pos = (0, 0.16)
            self.message.draw(); continue_rect.draw(); exit_rect.draw(); continue_text.draw(); exit_text.draw()
            if not rest_started:
                self.win.callOnFlip(
                    manager.emit,
                    "rest_start",
                    rest_index=rest_index,
                    actual_trigger_net_min=trigger_net_min,
                )
            self.win.flip()
            if not rest_started:
                page_onset = time.perf_counter()
                page_onset_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                rest_started = True
            keys = self.keyboard.getKeys(["escape", "f", "j"], waitRelease=False, clear=True)
            names = {str(getattr(key, "name", key)).lower() for key in keys}
            action = ""
            reason = ""
            for name in names:
                mapped = rest_action_for_key(name)
                if mapped:
                    action = mapped
                    reason = "esc" if mapped == "emergency" else ("" if mapped == "continue" else "operator_exit")
                    break
            if not action:
                core.wait(0.01)
                continue
            dwell = max(0.0, time.perf_counter() - page_onset)
            state.rest_index = rest_index
            state.rest_events.append({
                "subject_id": state.subject_id,
                "session_id": state.session_id,
                "rest_index": rest_index,
                "planned_threshold_min": state.next_rest_threshold_min,
                "actual_trigger_net_min": trigger_net_min,
                "page_onset": page_onset_timestamp,
                "action": action,
                "dwell_time_sec": dwell,
                "session_progress": self._session_progress(),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            })
            self._write_rest_log()
            if action == "continue":
                state.continuous_net_video_duration_sec = 0.0
                rng = random.Random(state.random_seed + rest_index * 104729)
                state.next_rest_threshold_min = choose_rest_threshold_seconds(
                    rng, self.protocol.rest_min_net_minutes, self.protocol.rest_max_net_minutes
                ) / 60.0
                manager.emit("rest_end", rest_index=rest_index, action="continue", dwell_time_sec=dwell)
                self._checkpoint("rest_continue")
                return
            self.termination_reason = "esc_emergency" if reason == "esc" else "rest_exit"
            manager.emit("rest_end", rest_index=rest_index, action="exit", dwell_time_sec=dwell)
            self._checkpoint(self.termination_reason)
            raise ExperimentAbort()

    def _require_state(self) -> SessionState:
        state = getattr(self, "state", None)
        if state is None:
            raise RuntimeError("Session state has not been initialized")
        return state

    def _session_progress(self) -> float:
        state = self._require_state()
        assigned = sum(float(self._asset_by_id[item].duration_sec or 0.0) for item in self._asset_by_id)
        return duration_progress(state.completed_net_video_duration_sec, assigned)

    def _session_exit_text(self) -> str:
        state = self._require_state()
        assigned = sum(float(asset.duration_sec or 0.0) for asset in self.playlist)
        progress = duration_progress(state.completed_net_video_duration_sec, assigned)
        return (
            f"本次 Session 已完成 {progress:.1f}%。\n\n"
            f"已完成视频：{len(state.completed_video_ids)}/{len(state.video_ids)}\n"
            f"已完成净视频时长：{state.completed_net_video_duration_sec / 60.0:.1f} 分钟\n\n"
            "数据已保存。按空格键退出。"
        )

    def _create_movie(self, media_path: Path) -> Any:
        try:
            movie = OpenCVVideoPlayer(self.win, str(media_path), autoLog=False)
        except Exception:
            movie_cls = getattr(visual, "MovieStim", None) or getattr(visual, "MovieStim3", None)
            if movie_cls is None:
                raise RuntimeError("当前 PsychoPy 版本不提供 MovieStim")
            movie_kwargs = {
                "filename": str(media_path),
                "units": "pix",
                "loop": False,
                "autoStart": False,
                "noAudio": True,
                "autoLog": False,
            }
            try:
                movie = movie_cls(self.win, movieLib="opencv", **movie_kwargs)
            except Exception:
                movie = movie_cls(self.win, movieLib="ffpyplayer", **movie_kwargs)
        try:
            video_width, video_height = movie.getVideoSize()
            window_width, window_height = self.win.size
            scale = min(window_width / video_width, window_height / video_height)
            movie.size = (video_width * scale, video_height * scale)
        except (AttributeError, TypeError, ValueError, ZeroDivisionError):
            movie.size = self.win.size
        return movie

    def _write_trial_log(self) -> None:
        manager = self._require_manager()
        output_dir = getattr(self, "progress_dir", None) or manager.session_dir
        if output_dir is None:
            return
        path = output_dir / "trial_log.csv"
        state = getattr(self, "state", None)
        rows = list(state.video_attempts) if state is not None else [asdict(record) for record in self.trial_records]
        if not rows:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".csv.tmp")
        with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            fields = sorted({key for row in rows for key in row})
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
        temp_path.replace(path)

    def _write_attention_log(self) -> None:
        manager = self._require_manager()
        output_dir = getattr(self, "progress_dir", None) or manager.session_dir
        state = getattr(self, "state", None)
        rows = list(state.attention_attempts) if state is not None else [asdict(record) for record in self.attention_records]
        if output_dir is None or not rows:
            return
        path = output_dir / "attention_log.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".csv.tmp")
        with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            fields = sorted({key for row in rows for key in row})
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
        temp_path.replace(path)

    def _write_rest_log(self) -> None:
        state = getattr(self, "state", None)
        if state is None or not state.rest_events or self.progress_dir is None:
            return
        path = self.progress_dir / "rest_log.csv"
        temp_path = path.with_suffix(".csv.tmp")
        with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            fields = sorted({key for row in state.rest_events for key in row})
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader(); writer.writerows(state.rest_events); handle.flush()
        temp_path.replace(path)

    def _write_session_summary(self) -> None:
        state = getattr(self, "state", None)
        if state is None or self.progress_dir is None:
            return
        assigned_sec = sum(float(asset.duration_sec or 0.0) for asset in self.playlist)
        summary = {
            "subject_id": state.subject_id,
            "session_id": state.session_id,
            "assigned_video_count": len(state.video_ids),
            "completed_video_count": len(state.completed_video_ids),
            "assigned_total_duration_sec": assigned_sec,
            "completed_total_duration_sec": state.completed_net_video_duration_sec,
            "progress_percent": duration_progress(state.completed_net_video_duration_sec, assigned_sec),
            "attention_completed": state.completed_attention_count,
            "attention_expected": self.protocol.attention_tasks_per_session,
            "rest_prompt_count": len(state.rest_events),
            "session_start": state.session_start_timestamp,
            "latest_resume_time": state.latest_resume_timestamp,
            "exit_reason": state.last_exit_reason,
            "completed": state.session_completed,
        }
        path = self.progress_dir / "session_summary.json"
        temp_path = path.with_name(path.name + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.flush()
        temp_path.replace(path)

    def _stop_and_export(self) -> Path | None:
        if self.manager is None:
            return None
        self._write_trial_log()
        self._write_attention_log()
        self._write_rest_log()
        self._checkpoint(self.termination_reason)
        return self.manager.stop_and_export(
            metadata={
                "completed": self.completed,
                "termination_reason": self.termination_reason,
                "completed_video_trials": len(self.state.completed_video_ids) if self.state is not None else len(self.trial_records),
                "completed_attention_trials": self.state.completed_attention_count if self.state is not None else len(self.attention_records),
                "attention_tasks_per_session": self.protocol.attention_tasks_per_session,
                "session_completed": bool(self.state.session_completed) if self.state is not None else self.completed,
                "completed_net_video_duration_sec": self._state_completed_duration(),
                "session_progress_percent": self._session_progress() if self.state is not None else 0.0,
                "rating_stage_present": False,
                "psychopy_flip_synchronized_markers": True,
                "baseline_enabled": False,
                "fixation_duration_sec": self.protocol.fixation_sec,
                "rest_min_net_minutes": self.protocol.rest_min_net_minutes,
                "rest_max_net_minutes": self.protocol.rest_max_net_minutes,
                "video_min_duration_sec": 5.0,
                "video_max_duration_sec": 60.0,
                "video_root": str(self.library.root),
                "eeg_mode": "dummy" if bool(self.config.get("hardware_dummy_mode", False)) else "real",
                "expected_sampling_rate_hz": expected_sampling_rate(self.config),
            }
        )

    def _show_text(
        self,
        text: str,
        *,
        wait_for_key: bool = True,
        duration: float | None = None,
    ) -> None:
        self.message.text = text
        self.message.height = 0.035
        self.message.pos = (0, 0)
        self.message.draw()
        self.win.flip()
        if duration is not None:
            self._wait_until(time.perf_counter() + duration)
            return
        if wait_for_key:
            self._clear_keyboard()
            while True:
                self._check_abort()
                if self.keyboard.getKeys(["space"], waitRelease=False, clear=True):
                    return
                core.wait(0.01)

    def _wait_until(self, deadline: float) -> None:
        while time.perf_counter() < deadline:
            self._check_abort()
            core.wait(min(0.01, max(0.0, deadline - time.perf_counter())))

    def _check_abort(self) -> None:
        if self.keyboard.getKeys(["escape"], waitRelease=False, clear=False):
            raise ExperimentAbort()

    def _clear_keyboard(self) -> None:
        try:
            self.keyboard.clearEvents()
        except Exception:
            if event is not None:
                event.clearEvents()

    def _set_phase_started_at(self) -> None:
        self._phase_started_at = time.perf_counter()

    def _require_manager(self) -> EegSessionManager:
        if self.manager is None:
            raise RuntimeError("EEG session has not started")
        self.manager.raise_if_background_failed()
        return self.manager


def probe_eeg_connection(config: dict[str, Any]) -> dict[str, Any]:
    if uses_bcigo_external_recording(config):
        backend = build_marker_backend(config)
        if not hasattr(backend, "wait_for_consumers"):
            raise RuntimeError("BCIGo 模式必须启用 LSL Marker")
        timeout = float(config.get("device", {}).get("bcigo_marker_wait_timeout_sec", 60.0))
        if not backend.wait_for_consumers(timeout):
            stream_name = str(config.get("device", {}).get("lsl_marker_stream_name", "video-eeg-Markers"))
            raise RuntimeError(f"BCIGo 未连接 Marker 流 {stream_name}")
        return {
            "device": "brainco_bcigo",
            "channels": 32,
            "sfreq": expected_sampling_rate(config),
            "expected_sampling_rate_hz": expected_sampling_rate(config),
            "samples": None,
            "recording_mode": "bcigo_external_edf",
            "marker_stream": str(config.get("device", {}).get("lsl_marker_stream_name", "video-eeg-Markers")),
        }

    acquirer: Any | None = None
    try:
        acquirer = build_acquirer(
            device_name=str(config.get("device_type", "brainco")),
            config=config,
        )
        acquirer.start_stream()
        deadline = time.monotonic() + 8.0
        samples = np.empty((int(acquirer.metadata.n_channels), 0), dtype=np.float32)
        while samples.shape[1] == 0 and time.monotonic() < deadline:
            samples, _timestamps = acquirer.get_new_samples()
            time.sleep(0.02)
        if samples.shape[1] == 0:
            raise RuntimeError("脑电连接成功，但未读取到样本")
        return {
            "device": acquirer.metadata.name,
            "channels": int(acquirer.metadata.n_channels),
            "sfreq": float(acquirer.metadata.sfreq),
            "expected_sampling_rate_hz": expected_sampling_rate(config),
            "samples": int(samples.shape[1]),
            "recording_mode": "local_continuous_eeg",
        }
    finally:
        if acquirer is not None:
            acquirer.stop_stream()


def run_eeg_check(config: dict[str, Any], *, wait_for_enter: bool) -> int:
    print("正在检查视频实验 EEG/Marker 连接...")
    try:
        info = probe_eeg_connection(config)
    except Exception as exc:
        print(f"连接检查失败：{exc}")
        return 1
    print(f"连接检查通过：{info}")
    if wait_for_enter:
        input("确认录制已开始后按 Enter 继续，或按 Ctrl+C 取消。")
    return 0


def doctor() -> int:
    checks: list[tuple[str, bool, str]] = []
    required_modules = (
        ("numpy", "numpy"),
        ("scipy", "scipy"),
        ("pandas", "pandas"),
        ("pytz", "pytz"),
        ("python-dateutil", "dateutil"),
        ("tzdata", "tzdata"),
        ("yaml", "yaml"),
        ("pylsl", "pylsl"),
        ("psychopy", "psychopy"),
        ("psychopy.visual", "psychopy.visual"),
        ("psychopy.core", "psychopy.core"),
        ("psychopy.event", "psychopy.event"),
        ("psychopy.gui", "psychopy.gui"),
        ("psychopy.data", "psychopy.data"),
        ("psychopy.hardware.keyboard", "psychopy.hardware.keyboard"),
        ("pytest", "pytest"),
        ("eeg_bids_converter", "eeg_bids_converter"),
    )
    for label, module_name in required_modules:
        try:
            module = importlib.import_module(module_name)
            checks.append((label, True, str(getattr(module, "__version__", "installed"))))
        except Exception as exc:
            checks.append((label, False, f"{type(exc).__name__}: {exc}"))
    manifest_path = CONFIG_DIR / "session_manifest.csv"
    try:
        manifest = SessionManifest.load(manifest_path)
        max_duration = max(item.video_duration_sec for item in manifest.entries)
        manifest_ok = (
            manifest.source_video_count > 0
            and len(manifest.entries) == manifest.source_video_count - manifest.excluded_video_count
            and max_duration <= 60.0 + 1e-6
        )
        checks.append(("formal_manifest", manifest_ok, f"videos={len(manifest.entries)}, max_duration_sec={max_duration:.3f}"))
        from video_eeg.utils.session_integrity import inspect_session_files
        config = load_config(CONFIG_DIR / DEFAULT_CONFIG_FILENAME)
        config['_project_dir'] = str(PROJECT_ROOT)
        report = inspect_session_files(manifest, load_video_library(config).root)
        exclusion_path = CONFIG_DIR / 'formal_excluded_over_60s.csv'
        with exclusion_path.open(encoding='utf-8-sig', newline='') as handle:
            excluded = {row['filename'] for row in csv.DictReader(handle)}
        unexplained = set(report['unassigned']) - excluded
        checks.append(('formal_filesystem', not report['missing'] and not report['duplicate_assignments'] and not unexplained,
                       f"root={report['video_root']}; manifest={manifest_path}; sessions=17; "
                       f"eligible={report['assigned']}; missing={len(report['missing'])}; "
                       f"duplicate={len(report['duplicate_assignments'])}; unassigned_eligible={len(unexplained)}"))
        print(f"Session folder views: {report['valid_session_folders']}/17 verified hardlink folders (optional for playback)")
    except Exception as exc:
        checks.append(("formal_manifest", False, str(exc)))
    for name, ok, detail in checks:
        print(f"{name}: {'正常' if ok else '缺失'} ({detail})")
    return 0 if all(ok for _, ok, _ in checks) else 1


def _load_psychopy() -> None:
    global core, event, gui, visual, Keyboard
    try:
        import psychopy as psychopy_package
    except ModuleNotFoundError as exc:
        if exc.name == "psychopy":
            raise RuntimeError(
                "当前 Python 环境未安装 PsychoPy。请重新运行一键安装.vbs。"
            ) from exc
        raise RuntimeError(
            f"PsychoPy 已安装，但其运行依赖导入失败：{exc}。"
            "请重新运行一键安装.vbs 或 install_lab_env_uv.bat 修复环境。"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"检测到 PsychoPy 包，但初始化失败：{type(exc).__name__}: {exc}。"
            "请重新运行一键安装.vbs 或 install_lab_env_uv.bat 修复环境。"
        ) from exc
    try:
        from psychopy import core as psychopy_core
        from psychopy import event as psychopy_event
        from psychopy import gui as psychopy_gui
        from psychopy import visual as psychopy_visual
        import psychopy.visual.movies as psychopy_movies
        from psychopy.hardware.keyboard import Keyboard as PsychoPyKeyboard
    except Exception as exc:
        raise RuntimeError(
            f"PsychoPy 已安装，但其运行依赖导入失败：{type(exc).__name__}: {exc}。"
            "请重新运行一键安装.vbs 或 install_lab_env_uv.bat 修复环境。"
        ) from exc
    core = psychopy_core
    event = psychopy_event
    gui = psychopy_gui
    visual = psychopy_visual
    Keyboard = PsychoPyKeyboard
    def _safe_movie_stim_free_player(self: Any) -> None:
        player = getattr(self, "_player", None)
        if player is None:
            return
        try:
            close = getattr(player, "close", None)
            if callable(close):
                close()
            else:
                free_player = getattr(player, "_freePlayer", None)
                if callable(free_player):
                    free_player()
        except Exception:
            pass
        self._player = None

    def _safe_movie_stim_cleanup_audio(self: Any) -> None:
        audio_track = getattr(self, "_audioTrack", None)
        if audio_track is not None:
            try:
                stop = getattr(audio_track, "stop", None)
                if callable(stop):
                    stop()
            except Exception:
                pass
            self._audioTrack = None

    movie_cls = getattr(visual, "MovieStim", None)
    reader_cls = getattr(psychopy_movies, "MovieFileReader", None)
    if movie_cls is not None:
        resolved = getattr(movie_cls, "_resolve", lambda: movie_cls)()
        if hasattr(resolved, "_cleanupAudioTrack") and not hasattr(resolved, "_cleanUpAudioTrack"):
            resolved._cleanUpAudioTrack = resolved._cleanupAudioTrack
        if not hasattr(resolved, "_audioLib"):
            resolved._audioLib = None
        if not hasattr(resolved, "_freePlayer"):
            resolved._freePlayer = _safe_movie_stim_free_player
        if not hasattr(resolved, "_cleanUpAudioTrack"):
            resolved._cleanUpAudioTrack = _safe_movie_stim_cleanup_audio
    for cls_name in ("MovieStim", "MovieStim3", "MovieFileReader"):
        cls = getattr(psychopy_movies, cls_name, None)
        if cls is None:
            continue
        resolved_cls = getattr(cls, "_resolve", lambda: cls)()
        if hasattr(resolved_cls, "_cleanupAudioTrack") and not hasattr(resolved_cls, "_cleanUpAudioTrack"):
            resolved_cls._cleanUpAudioTrack = resolved_cls._cleanupAudioTrack
        if not hasattr(resolved_cls, "_audioLib"):
            resolved_cls._audioLib = None
        if cls_name in {"MovieStim", "MovieStim3", "MovieFileReader"} and not hasattr(resolved_cls, "_cleanUpAudioTrack"):
            resolved_cls._cleanUpAudioTrack = _safe_movie_stim_cleanup_audio
        if cls_name in {"MovieStim", "MovieStim3"}:
            if not hasattr(resolved_cls, "_freePlayer"):
                resolved_cls._freePlayer = _safe_movie_stim_free_player


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _natural_asset_key(asset: VideoAsset) -> tuple[Any, ...]:
    """Sort numeric demo filenames as 1, 2, ..., 10 instead of 1, 10, 2."""

    import re

    parts = re.split(r"(\d+)", Path(asset.rel_path).as_posix().lower())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _load_simple_yaml(path: Path) -> dict[str, Any]:
    """Read the scalar/nested mapping subset used by the project configs."""

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    with path.open("r", encoding="utf-8-sig") as handle:
        for raw in handle:
            line = raw.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            key, separator, value = line.strip().partition(":")
            if not separator:
                continue
            while stack and indent <= stack[-1][0]:
                stack.pop()
            parent = stack[-1][1]
            if not value.strip():
                child: dict[str, Any] = {}
                parent[key.strip()] = child
                stack.append((indent, child))
            else:
                parent[key.strip()] = _parse_scalar(value.strip())
    return root


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if text in {"''", '\"\"'}:
        return ""
    if (text.startswith("'") and text.endswith("'")) or (
        text.startswith('\"') and text.endswith('\"')
    ):
        return text[1:-1]
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


if __name__ == "__main__":
    # Keep PsychoPy globals shared with the question runner when launched via -m.
    from video_eeg.experiment.video_runner import main
    raise SystemExit(main(sys.argv[1:]))



