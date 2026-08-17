"""Standalone PsychoPy video-EEG experiment.

This entry point is intentionally independent from the Image_B experiment and
does not import or launch any Streamlit UI.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
import time
import traceback
from typing import Any

import numpy as np

from protocol.video_protocol import EegSessionManager
from utils.video_library import (
    VideoAsset,
    build_balanced_playlist,
    build_playlist,
    load_video_library,
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
_LSL_MARKER_BACKENDS: dict[tuple[str, str, str], Any] = {}


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

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "VideoExperimentConfig":
        protocol = dict(config.get("protocol", {}))
        parsed = cls(
            fixation_sec=float(protocol.get("fixation_sec", 1.5)),
            video_sec=float(protocol.get("default_video_sec", 60.0)),
            blank_sec=float(protocol.get("blank_sec", 1.0)),
            iti_sec=float(protocol.get("iti_sec", 2.0)),
            eyes_open_baseline_sec=float(protocol.get("eyes_open_baseline_sec", 60.0)),
            eyes_closed_baseline_sec=float(protocol.get("eyes_closed_baseline_sec", 60.0)),
            trials_per_session=int(protocol.get("trials_per_session", 500)),
            random_seed=int(protocol.get("random_seed", 17)),
            playlist_mode=str(protocol.get("playlist_mode", "balanced")).strip().lower(),
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
        if parsed.trials_per_session <= 0:
            raise ValueError("protocol.trials_per_session must be positive")
        if parsed.playlist_mode not in {"balanced", "shuffle", "sequential"}:
            raise ValueError(
                "protocol.playlist_mode must be balanced, shuffle, or sequential"
            )
        return parsed


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


def resolve_config_path(config_path: Path | None = None) -> Path:
    if config_path is not None:
        return Path(config_path).expanduser().resolve()
    cwd_config = Path.cwd() / DEFAULT_CONFIG_FILENAME
    if cwd_config.exists():
        return cwd_config.resolve()
    return Path(__file__).with_name(DEFAULT_CONFIG_FILENAME).resolve()


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
    from acquisition.factory import AcquirerFactory, register_default_acquirers

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
        "sfreq": float(config.get("sfreq", 250.0)),
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
    from utils.markers import (
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
            backend = LSLMarkerBackend(
                stream_name=marker_identity[0],
                stream_type=marker_identity[1],
                source_id=marker_identity[2],
            )
            _LSL_MARKER_BACKENDS[marker_identity] = backend
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行独立的 PsychoPy 视频 EEG 实验。")
    parser.add_argument("--config", type=Path, default=None, help="视频实验配置文件，默认 video_config.yaml。")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="使用 video_demo_config.yaml 和 video_library/1.mp4 至 10.mp4 运行真人流程测试。",
    )
    parser.add_argument("--subject-id", type=str, default="", help="覆盖配置中的被试编号。")
    parser.add_argument("--session-id", type=int, default=0, help="覆盖配置中的 session 编号。")
    parser.add_argument("--max-trials", type=int, default=0, help="限制本次视频数；0 使用配置值。")
    parser.add_argument("--windowed", action="store_true", help="使用窗口模式。")
    parser.add_argument("--no-dialog", action="store_true", help="跳过 PsychoPy 启动对话框。")
    parser.add_argument("--dummy-eeg", action="store_true", help="强制使用模拟 EEG。")
    parser.add_argument("--real-eeg", action="store_true", help="强制使用真实 EEG 配置。")
    parser.add_argument("--device-type", choices=["brainco", "neuracle"], default="")
    parser.add_argument("--brainco-transport", choices=["bcigo", "lsl", "sdk"], default="")
    parser.add_argument("--preflight-eeg", action="store_true", help="打开窗口前检查 EEG/Marker 连接。")
    parser.add_argument("--eeg-check-only", action="store_true", help="只检查 EEG/Marker 连接。")
    parser.add_argument("--doctor", action="store_true", help="检查视频实验运行依赖。")
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.doctor:
        return doctor()
    if args.demo and args.config is not None:
        raise RuntimeError("--demo 与 --config 不能同时使用")
    config_path = resolve_config_path(
        Path(__file__).with_name(DEMO_CONFIG_FILENAME) if args.demo else args.config
    )
    config = load_config(config_path)
    apply_cli_overrides(config, args)
    if args.subject_id.strip():
        config["subject_id"] = args.subject_id.strip()
    if args.session_id > 0:
        config["session_id"] = args.session_id
    protocol = VideoExperimentConfig.from_config(config)
    if args.max_trials > 0:
        protocol.trials_per_session = min(protocol.trials_per_session, args.max_trials)
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
    protocol.trials_per_session = startup["trials_per_session"]

    library = load_video_library(config)
    playlist_seed = protocol.random_seed + int(config["session_id"])
    if protocol.playlist_mode == "sequential":
        catalog = sorted(library.list_assets(), key=_natural_asset_key)
        if len(catalog) < protocol.trials_per_session:
            raise RuntimeError(
                f"Video library has {len(catalog)} assets but session requires "
                f"{protocol.trials_per_session}."
            )
        playlist = catalog[: protocol.trials_per_session]
    elif args.max_trials > 0 or protocol.playlist_mode == "shuffle":
        playlist = build_playlist(
            library,
            trials_per_session=protocol.trials_per_session,
            random_seed=playlist_seed,
        )
    else:
        playlist = build_balanced_playlist(
            library,
            trials_per_session=protocol.trials_per_session,
            random_seed=playlist_seed,
        )
    missing = [asset.rel_path for asset in playlist if not library.is_available(asset)]
    if missing:
        raise RuntimeError(f"播放列表包含不存在的视频，示例：{missing[:5]}")

    window_kwargs: dict[str, Any] = {
        "fullscr": startup["fullscreen"],
        "color": BACKGROUND,
        "units": "height",
        "allowGUI": not startup["fullscreen"],
    }
    win = visual.Window(**window_kwargs)
    runner = VideoRunner(
        win=win,
        keyboard=Keyboard(),
        config=config,
        protocol=protocol,
        project_dir=Path(__file__).resolve().parent,
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
    defaults = {
        "subject_id": str(config.get("subject_id", "S001")),
        "session_id": int(config.get("session_id", 1)),
        "trials_per_session": int(protocol.trials_per_session),
        "fullscreen": not bool(args.windowed),
    }
    if args.no_dialog:
        return defaults
    dlg = gui.Dlg(title="PsychoPy 视频 EEG 实验")
    dlg.addText("独立视频范式：睁眼基线 60 秒、闭眼基线 60 秒、视频默认 60 秒，无评分阶段。")
    dlg.addField("被试编号", defaults["subject_id"])
    dlg.addField("Session 编号", defaults["session_id"])
    dlg.addField("本轮视频数", defaults["trials_per_session"])
    dlg.addField("全屏显示", defaults["fullscreen"])
    values = dlg.show()
    if not dlg.OK:
        return None
    subject_id = str(values[0]).strip() or "S001"
    session_id = int(values[1])
    trial_count = int(values[2])
    if session_id <= 0 or trial_count <= 0:
        raise ValueError("Session 编号和视频数必须为正整数")
    return {
        "subject_id": subject_id,
        "session_id": session_id,
        "trials_per_session": trial_count,
        "fullscreen": _coerce_bool(values[3]),
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
        self.completed = False
        self.termination_reason = "running"
        self._run_traceback = ""
        self._phase_started_at = 0.0
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
            self._show_text("即将检查脑电和 Marker 连接。\n\n请确认设备已经准备好。\n\n按空格键继续。")
            connection = self._check_eeg_connection()
            self._show_text(self._connection_success_text(connection))
            self._start_eeg(connection)
            self._run_baselines()
            for trial_idx, asset in enumerate(self.playlist, start=1):
                self._check_abort()
                self._run_trial(trial_idx, asset)
            self.completed = True
            self.termination_reason = "completed"
        except ExperimentAbort:
            self.termination_reason = "operator_abort"
            self._show_text("实验已中止，正在保存已采集的数据。", wait_for_key=False, duration=1.0)
        except Exception as exc:
            self.termination_reason = "python_exception"
            self._run_traceback = traceback.format_exc()
            self._show_text(f"实验运行出错：\n{exc}\n\n按空格键退出。")
        finally:
            session_dir = self._stop_and_export()
            if session_dir is not None:
                if self._run_traceback:
                    (session_dir / "crash_report.txt").write_text(self._run_traceback, encoding="utf-8")
                self._show_text(f"数据已保存：\n{session_dir}\n\n按空格键退出。")

    def _show_instructions(self) -> None:
        self._show_text(
            f"被试编号：{self.config.get('subject_id')}\n"
            f"Session：{self.config.get('session_id')}\n\n"
            "本实验只进行视频观看和脑电采集，不包含主观评分。\n"
            "Session 开始后先采集睁眼基线 60 秒，再采集闭眼基线 60 秒。\n"
            f"随后观看 {len(self.playlist)} 个视频，每个视频默认呈现 {self.protocol.video_sec:.0f} 秒。\n\n"
            "观看期间请保持头部和身体静止，尽量减少眨眼。\n"
            "紧急情况下按 S 跳过当前视频，按 Esc 中止实验。\n\n"
            "按空格键继续。"
        )

    def _check_eeg_connection(self) -> dict[str, Any]:
        try:
            return probe_eeg_connection(self.config)
        except Exception as exc:
            self._show_text(f"脑电连接检查失败：\n{exc}\n\n按空格键退出。")
            raise ExperimentAbort() from exc

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
            sfreq=float(self.config.get("sfreq", 250.0)),
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
                "video_default_duration_sec": self.protocol.video_sec,
                "eyes_open_baseline_sec": self.protocol.eyes_open_baseline_sec,
                "eyes_closed_baseline_sec": self.protocol.eyes_closed_baseline_sec,
                "playlist_seed": self.protocol.random_seed + int(self.config.get("session_id", 1)),
                "playlist_mode": self.protocol.playlist_mode,
                "demo_mode": bool(self.config.get("demo_mode", False)),
                "eeg_connection_check": connection,
                "eeg_recording_mode": (
                    "bcigo_external_edf"
                    if uses_bcigo_external_recording(self.config)
                    else "local_continuous_eeg"
                ),
            }
        )
        (session_dir / "video_playlist.json").write_text(
            json.dumps(
                [asset.to_mapping() for asset in self.playlist],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

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

    def _run_trial(self, trial_idx: int, asset: VideoAsset) -> None:
        manager = self._require_manager()
        trial_started = time.time()
        self.fixation.draw()
        self.win.callOnFlip(
            manager.begin_trial,
            trial_idx=trial_idx,
            video_name=asset.asset_id,
        )
        self.win.callOnFlip(
            manager.fixation_on,
            trial_idx=trial_idx,
            video_name=asset.asset_id,
        )
        self.win.flip()
        self._wait_until(time.perf_counter() + self.protocol.fixation_sec)

        media_path = self.library.resolve(asset)
        media_load_started = time.perf_counter()
        movie = self._create_movie(media_path)
        media_load_sec = time.perf_counter() - media_load_started
        planned_duration = float(asset.duration_sec or self.protocol.video_sec)
        movie.draw()
        self.win.callOnFlip(manager.fixation_off, trial_idx=trial_idx)
        self.win.callOnFlip(movie.play)
        self.win.callOnFlip(self._set_phase_started_at)
        self.win.callOnFlip(
            manager.emit,
            "video_on",
            trial_idx=trial_idx,
            video_name=asset.asset_id,
            planned_duration_sec=planned_duration,
        )
        self.win.flip()

        skipped = False
        completed_naturally = False
        while time.perf_counter() - self._phase_started_at < planned_duration:
            keys = self.keyboard.getKeys(["escape", "s"], waitRelease=False, clear=True)
            names = {str(getattr(key, "name", key)).lower() for key in keys}
            if "escape" in names:
                raise ExperimentAbort()
            if "s" in names:
                skipped = True
                break
            if bool(getattr(movie, "isFinished", False)):
                completed_naturally = True
                break
            movie.draw()
            self.win.flip()

        actual_duration = max(0.0, time.perf_counter() - self._phase_started_at)
        stop_playback = getattr(movie, "pause", None) or movie.stop
        self.win.callOnFlip(stop_playback)
        self.win.callOnFlip(
            manager.emit,
            "video_off",
            trial_idx=trial_idx,
            video_name=asset.asset_id,
            actual_duration_sec=actual_duration,
            completed_naturally=completed_naturally,
            skipped=skipped,
        )
        self.win.callOnFlip(manager.blank_on, trial_idx=trial_idx)
        self.win.flip()
        self._wait_until(time.perf_counter() + self.protocol.blank_sec)

        self.win.callOnFlip(manager.blank_off, trial_idx=trial_idx)
        self.win.callOnFlip(manager.iti_on, trial_idx=trial_idx)
        self.win.flip()
        self._wait_until(time.perf_counter() + self.protocol.iti_sec)
        self.message.text = (
            "正在准备下一段视频…"
            if trial_idx < len(self.playlist)
            else "视频观看完成，正在整理数据…"
        )
        self.message.height = 0.035
        self.message.pos = (0, 0)
        self.message.draw()
        self.win.callOnFlip(manager.iti_off, trial_idx=trial_idx)
        self.win.callOnFlip(
            manager.end_trial,
            trial_idx=trial_idx,
            video_name=asset.asset_id,
        )
        self.win.flip()
        cleanup_started = time.perf_counter()
        try:
            # PsychoPy MovieStim.stop() closes and immediately reloads the same
            # file. That is useful for replay, but wasteful when advancing to a
            # different trial. Direct unload avoids a redundant decoder/audio
            # initialization that previously added several seconds per skip.
            movie.unload()
        except (AttributeError, RuntimeError):
            pass
        media_cleanup_sec = time.perf_counter() - cleanup_started

        self.trial_records.append(
            TrialRecord(
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
            )
        )
        self._write_trial_log()

    def _create_movie(self, media_path: Path) -> Any:
        movie_cls = getattr(visual, "MovieStim", None) or getattr(visual, "MovieStim3", None)
        if movie_cls is None:
            raise RuntimeError("当前 PsychoPy 版本不提供 MovieStim")
        movie = movie_cls(
            self.win,
            filename=str(media_path),
            units="pix",
            loop=False,
            autoStart=False,
            noAudio=False,
            autoLog=False,
        )
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
        if manager.session_dir is None:
            return
        path = manager.session_dir / "trial_log.csv"
        rows = [asdict(record) for record in self.trial_records]
        if not rows:
            return
        temp_path = path.with_suffix(".csv.tmp")
        with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        temp_path.replace(path)

    def _stop_and_export(self) -> Path | None:
        if self.manager is None:
            return None
        return self.manager.stop_and_export(
            metadata={
                "completed": self.completed,
                "termination_reason": self.termination_reason,
                "completed_video_trials": len(self.trial_records),
                "rating_stage_present": False,
                "psychopy_flip_synchronized_markers": True,
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
            "sfreq": float(config.get("sfreq", 250.0)),
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
            "sfreq": float(config.get("sfreq", 250.0)),
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
    for module_name in ("psychopy", "numpy", "yaml", "pylsl"):
        try:
            module = __import__(module_name)
            checks.append((module_name, True, str(getattr(module, "__version__", "installed"))))
        except Exception as exc:
            checks.append((module_name, False, str(exc)))
    for name, ok, detail in checks:
        print(f"{name}: {'正常' if ok else '缺失'} ({detail})")
    return 0 if all(ok for _, ok, _ in checks[:3]) else 1


def _load_psychopy() -> None:
    global core, event, gui, visual, Keyboard
    try:
        from psychopy import core as psychopy_core
        from psychopy import event as psychopy_event
        from psychopy import gui as psychopy_gui
        from psychopy import visual as psychopy_visual
        from psychopy.hardware.keyboard import Keyboard as PsychoPyKeyboard
    except Exception as exc:
        raise RuntimeError("当前 Python 环境未安装 PsychoPy。") from exc
    core = psychopy_core
    event = psychopy_event
    gui = psychopy_gui
    visual = psychopy_visual
    Keyboard = PsychoPyKeyboard


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
    raise SystemExit(main(sys.argv[1:]))
