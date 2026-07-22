"""Standalone PsychoPy runner for the Image_B single-session EEG experiment."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from functools import partial
import json
import os
from pathlib import Path
import random
import re
import sys
import time
import traceback
from typing import Any, Callable

import numpy as np

from protocol.video_protocol import EegSessionManager, VideoProtocolConfig
from tasks.image_core import (
    FORMAL_500_PROTOCOL,
    PILOT_105_PROTOCOL,
    RATING_DIMENSIONS,
    RATING_VALUES,
    TIMESTAMP_LABEL_PATTERN,
    ImageAsset,
    ImageTrial,
    build_output_rows,
    build_session_playlist,
    default_image_set_label,
    image_path,
    make_rating_row,
    make_trial_log_row,
    normalize_experiment_protocol,
    protocol_value,
    session_type_for_id,
    write_playlist_json,
    write_rows_csv,
)
core: Any = None
event: Any = None
gui: Any = None
visual: Any = None
Keyboard: Any = None

FONT_NAME = "Microsoft YaHei"
BACKGROUND = "black"
FOREGROUND = "white"
ACCENT = "#3b82f6"
MUTED = "#94a3b8"
SELECTED = "#1d4ed8"
DEFAULT_CONFIG_FILENAME = "config.yaml"
_LSL_MARKER_BACKENDS: dict[tuple[str, str, str], Any] = {}


class ExperimentAbort(Exception):
    """Raised when the operator presses Escape."""


class MemorySafetyAbort(Exception):
    """Raised after progress is saved when process memory becomes unsafe."""


def resolve_config_path(config_path: Path | None = None) -> Path:
    if config_path is not None:
        return Path(config_path).expanduser().resolve()
    cwd_config = Path.cwd() / DEFAULT_CONFIG_FILENAME
    if cwd_config.exists():
        return cwd_config.resolve()
    return Path(__file__).with_name(DEFAULT_CONFIG_FILENAME).resolve()


def load_config(path: Path) -> dict[str, Any]:
    path = resolve_config_path(path)
    if not path.exists():
        raise RuntimeError(f"未找到配置文件：{path}")
    try:
        import yaml
    except ImportError:
        return _load_simple_yaml(path)
    with path.open("r", encoding="utf-8-sig") as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        raise RuntimeError(f"配置文件必须是键值结构：{path}")
    return config


def _fullscreen_display() -> tuple[int, tuple[int, int] | None]:
    """Return the extended display when available, otherwise the primary one."""
    try:
        import pyglet

        screens = pyglet.canvas.get_display().get_screens()
        screen_index = 1 if len(screens) > 1 else 0
        screen = screens[screen_index]
        return screen_index, (int(screen.width), int(screen.height))
    except (AttributeError, ImportError, OSError):
        return 0, None


def build_acquirer(*, device_name: str, config: dict[str, Any]) -> Any:
    from acquisition.factory import AcquirerFactory, register_default_acquirers

    register_default_acquirers()
    device_cfg = dict(config.get("device", {}))
    selected = "dummy" if bool(config.get("hardware_dummy_mode", False)) else str(device_name or config.get("device_type", "brainco")).strip().lower()
    if selected == "dummy" and not bool(config.get("hardware_dummy_mode", False)):
        config["hardware_dummy_mode"] = True
    if selected not in AcquirerFactory.list_devices():
        available = ", ".join(AcquirerFactory.list_devices())
        raise RuntimeError(f"未知脑电设备：{selected!r}。可用设备：{available}")
    kwargs: dict[str, Any] = {
        "sfreq": float(config.get("sfreq", 250.0)),
        "n_channels": 32 if selected == "brainco" else 64,
        "buffer_sec": float(config.get("buffer_sec", 120.0)),
    }
    factory_name = selected
    if selected == "neuracle":
        kwargs["neuracle_host"] = str(device_cfg.get("neuracle_host", "127.0.0.1"))
        kwargs["neuracle_port"] = int(device_cfg.get("neuracle_port", 8712))
    elif selected == "brainco":
        transport = str(device_cfg.get("brainco_transport", "sdk")).strip().lower()
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
                    "resolve_timeout_sec": float(
                        device_cfg.get("brainco_lsl_resolve_timeout_sec", 15.0)
                    ),
                    "ready_timeout_sec": float(
                        device_cfg.get("brainco_lsl_ready_timeout_sec", 10.0)
                    ),
                    "backend_name": "brainco_lsl",
                }
            )
        elif transport == "sdk":
            kwargs["brainco_addr"] = str(device_cfg.get("brainco_addr", ""))
            kwargs["brainco_port"] = int(device_cfg.get("brainco_port", 0))
            kwargs["auto_discover"] = bool(device_cfg.get("brainco_auto_discover", True))
            kwargs["scan_timeout_sec"] = float(device_cfg.get("brainco_scan_timeout_sec", 6.0))
            kwargs["ready_timeout_sec"] = float(device_cfg.get("brainco_ready_timeout_sec", 20.0))
            kwargs["start_retries"] = int(device_cfg.get("brainco_start_retries", 2))
            kwargs["eeg_gain"] = int(device_cfg.get("brainco_gain", 6))
            kwargs["signal_source"] = str(device_cfg.get("brainco_signal_source", "NORMAL"))
            kwargs["device_id"] = str(device_cfg.get("brainco_device_id", "eeg-cap"))
        else:
            raise RuntimeError("device.brainco_transport 必须是 bcigo、lsl 或 sdk。")
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
        backends.append(TriggerBoxMarkerBackend(serial_port))
    brainco_marker = (
        str(config.get("device_type", "")).strip().lower() == "brainco"
        and str(device_cfg.get("brainco_transport", "sdk")).strip().lower()
        in {"bcigo", "lsl"}
    )
    # The LSL marker outlet belongs to the BrainCo/BCIGo transport only.
    # Neuracle keeps using its Collect/JellyFish TCP forwarding path (and an
    # optional serial trigger box) even when the shared config enables BCIGo
    # markers.
    if brainco_marker and bool(device_cfg.get("lsl_marker_enabled", True)):
        marker_identity = (
            str(device_cfg.get("lsl_marker_stream_name", "visual-video-task-Markers")),
            str(device_cfg.get("lsl_marker_stream_type", "Markers")),
            str(device_cfg.get("lsl_marker_source_id", "visual-video-task-marker")),
        )
        marker_backend = _LSL_MARKER_BACKENDS.get(marker_identity)
        if marker_backend is None:
            marker_backend = LSLMarkerBackend(
                stream_name=marker_identity[0],
                stream_type=marker_identity[1],
                source_id=marker_identity[2],
            )
            # Reuse the same outlet after preflight so BCIGo keeps its selected
            # Marker stream while the participant dialog and experiment open.
            _LSL_MARKER_BACKENDS[marker_identity] = marker_backend
        backends.append(marker_backend)
    if not backends:
        return NoOpMarkerBackend()
    if len(backends) == 1:
        return backends[0]
    return CompositeMarkerBackend(*backends)


def parse_args(argv: list[str] | None = None, *, behavior_only: bool = False) -> argparse.Namespace:
    description = "运行 Image_B 纯行为评分实验。" if behavior_only else "运行单个 Image_B PsychoPy 脑电观看实验。"
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", type=Path, default=None, help="config.yaml 路径。")
    parser.add_argument("--max-trials", type=int, default=0, help="本轮图片/试次数；0 表示使用配置或被试固定图片集合。")
    parser.add_argument(
        "--experiment-protocol",
        choices=[FORMAL_500_PROTOCOL, PILOT_105_PROTOCOL],
        default="",
        help="formal500=正式500张协议；pilot105=105张预实验。",
    )
    parser.add_argument("--timestamp-label", type=str, default="", help="批次标签 yyyymmdd_xxxx；也可只输入 xxxx 自动补当天日期。")
    parser.add_argument("--windowed", action="store_true", help="窗口模式运行，而不是全屏。")
    parser.add_argument("--no-dialog", action="store_true", help="跳过 PsychoPy 启动对话框。")
    parser.add_argument("--doctor", action="store_true", help="检查当前 PsychoPy 运行环境后退出。")
    if not behavior_only:
        parser.add_argument("--device-type", choices=["brainco", "neuracle"], default="", help="命令行指定脑电设备。")
        parser.add_argument("--dummy-eeg", action="store_true", help="命令行强制使用模拟脑电。")
        parser.add_argument("--real-eeg", action="store_true", help="命令行强制使用真实脑电硬件。")
        parser.add_argument("--brainco-addr", type=str, default="", help="BrainCo 设备 IP/地址；指定后会关闭自动发现。")
        parser.add_argument("--brainco-port", type=int, default=0, help="BrainCo 设备端口；指定后会关闭自动发现。")
        parser.add_argument("--brainco-scan-timeout", type=float, default=0.0, help="BrainCo 自动发现超时时间，单位秒。")
        parser.add_argument("--brainco-ready-timeout", type=float, default=0.0, help="BrainCo 启动数据流等待时间，单位秒。")
        parser.add_argument(
            "--brainco-transport",
            choices=["bcigo", "lsl", "sdk"],
            default="",
            help="bcigo=BCIGo 录 EDF 且实验发 Marker；lsl=接收 EEG LSL；sdk=直连设备。",
        )
        parser.add_argument("--brainco-lsl-name", type=str, default="", help="BCIGo LSL EEG streamName；留空按类型自动匹配。")
        parser.add_argument("--brainco-lsl-source-id", type=str, default="", help="BCIGo LSL EEG sourceId；有同名流时用于精确匹配。")
        parser.add_argument(
            "--brainco-lsl-timeout",
            type=float,
            default=0.0,
            help="等待 BCIGo Marker 消费者或 EEG LSL 流的超时时间，单位秒。",
        )
        parser.add_argument("--eeg-check-only", action="store_true", help="只在命令行检查脑电连接，检查结束后退出。")
        parser.add_argument("--preflight-eeg", action="store_true", help="启动 PsychoPy 窗口前先在命令行检查脑电连接。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, behavior_only: bool = False) -> int:
    args = parse_args(argv, behavior_only=behavior_only)
    project_dir = Path(__file__).resolve().parent
    if args.doctor:
        return _doctor()
    config_path = resolve_config_path(args.config)
    config = load_config(config_path)
    config["task_mode"] = "image_b"
    config["collection_phase"] = "behavior_rating" if behavior_only else "eeg_repeat"
    if not behavior_only:
        _apply_cli_eeg_overrides(config, args)
    if bool(getattr(args, "eeg_check_only", False)):
        return _run_eeg_cli_check(config, wait_for_enter=False)
    if bool(getattr(args, "preflight_eeg", False)):
        status = _run_eeg_cli_check(config, wait_for_enter=True)
        if status != 0:
            return status
    _load_psychopy()
    records_dir = project_dir / Path(str(config.get("storage", {}).get("records_dir", "records_storage")))
    exp_info = _startup_dialog(config, args, records_dir=records_dir, behavior_only=behavior_only)
    if exp_info is None:
        return 0
    if not behavior_only and (
        normalize_experiment_protocol(exp_info["experiment_protocol"]) != FORMAL_500_PROTOCOL
        or int(exp_info["session_id"]) not in {2, 3, 4, 5, 6}
    ):
        raise ValueError("EEG观看程序只支持formal500协议的Session 2-6。")
    config["subject_id"] = exp_info["subject_id"]
    config["experiment_protocol"] = normalize_experiment_protocol(exp_info["experiment_protocol"])
    config["session_id"] = 1 if behavior_only else exp_info["session_id"]
    config["session_type"] = session_type_for_id(
        exp_info["session_id"], config["experiment_protocol"]
    )
    config["image_set_label"] = normalize_image_set_label(exp_info["image_set_label"])
    if behavior_only:
        config["device_type"] = "none"
        config["hardware_dummy_mode"] = False
    else:
        config["device_type"] = exp_info["device_type"]
        config["hardware_dummy_mode"] = exp_info["hardware_dummy_mode"]
    config["timestamp_label"] = unique_timestamp_label(
        records_dir,
        subject_id=str(config["subject_id"]),
        session_id=int(config["session_id"]),
        image_set_label=str(config["image_set_label"]),
        preferred=exp_info.get("timestamp_label"),
    )
    # A zero dialog value means "use the selected protocol's fixed image count".
    image_count = exp_info["max_trials"] if exp_info["max_trials"] > 0 else None
    trials, assets, playlist_metadata = build_session_playlist(
        config,
        subject_id=str(config["subject_id"]),
        session_id=int(config["session_id"]),
        records_dir=records_dir,
        base_dir=project_dir,
        image_count=image_count,
    )
    resume_state = find_resume_state(
        records_dir,
        subject_id=str(config["subject_id"]),
        session_id=int(config["session_id"]),
        trials=trials,
        image_set_label=str(config["image_set_label"]),
    )
    if resume_state:
        config["timestamp_label"] = str(
            resume_state.get("timestamp_label") or Path(resume_state["source_dir"]).parent.name
        )
    window_kwargs: dict[str, Any] = {
        "fullscr": exp_info["fullscreen"],
        "color": BACKGROUND,
        "units": "height",
        "allowGUI": not exp_info["fullscreen"],
    }
    if exp_info["fullscreen"]:
        screen_index, screen_size = _fullscreen_display()
        window_kwargs["screen"] = screen_index
        if screen_size is not None:
            window_kwargs["size"] = screen_size
    win = visual.Window(**window_kwargs)
    runner = ImageBRunner(
        win=win,
        mouse=event.Mouse(win=win),
        keyboard=Keyboard(),
        config=config,
        project_dir=project_dir,
        trials=trials,
        assets=assets,
        playlist_metadata=playlist_metadata,
        resume_state=resume_state,
        behavior_only=behavior_only,
    )
    try:
        runner.run()
    finally:
        try:
            runner.release_visual_resources()
        finally:
            win.close()
    core.quit()
    return 0


def _startup_dialog(
    config: dict[str, Any],
    args: argparse.Namespace,
    *,
    records_dir: Path,
    behavior_only: bool = False,
) -> dict[str, Any] | None:
    configured_protocol = normalize_experiment_protocol(config.get("experiment_protocol", FORMAL_500_PROTOCOL))
    config_locked = bool(config.get("experiment_config_locked", True))
    requested_protocol = normalize_experiment_protocol(args.experiment_protocol or configured_protocol)
    if config_locked and requested_protocol != configured_protocol:
        raise ValueError(
            "实验配置已锁定：rating和repetition必须使用config.yaml中的同一experiment_protocol。"
        )
    default_protocol = configured_protocol if config_locked else requested_protocol
    default_session = 1 if behavior_only else int(config.get("session_id", 2))
    if not behavior_only:
        try:
            session_type_for_id(default_session, default_protocol)
            if default_protocol != FORMAL_500_PROTOCOL or default_session == 1:
                raise ValueError
        except ValueError:
            default_protocol = FORMAL_500_PROTOCOL
            default_session = 2
    default_timestamp = normalize_timestamp_label(args.timestamp_label) if args.timestamp_label else None
    default_subject = str(config.get("subject_id", "S001"))
    configured_label = normalize_image_set_label(
        str(config.get("image_set_label") or default_image_set_label(default_protocol))
    )
    dialog_image_set_label = (
        configured_label
        if default_protocol == configured_protocol
        else default_image_set_label(default_protocol)
    )
    if args.no_dialog:
        return {
            "subject_id": default_subject,
            "experiment_protocol": default_protocol,
            "session_id": default_session,
            "image_set_label": dialog_image_set_label,
            "device_type": "none" if behavior_only else str(config.get("device_type", "brainco")),
            "hardware_dummy_mode": False if behavior_only else bool(config.get("hardware_dummy_mode", False)),
            "fullscreen": not bool(args.windowed),
            "max_trials": max(0, int(args.max_trials)),
            "timestamp_label": default_timestamp,
        }
    dlg = gui.Dlg(title="PsychoPy Image_B 纯行为评分" if behavior_only else "PsychoPy Image_B 脑电观看实验")
    if behavior_only:
        dlg.addText("本程序只进行一次图片评分，不连接脑电设备，也不发送外部事件标记。")
    else:
        dlg.addText("本程序只运行正式协议第2-6轮，共获得每张图片5次独立脑电数据。")
    dlg.addField("被试编号", default_subject)
    dlg.addField(
        "实验协议",
        default_protocol,
        choices=[FORMAL_500_PROTOCOL, PILOT_105_PROTOCOL] if behavior_only else [FORMAL_500_PROTOCOL],
    )
    if not behavior_only:
        dlg.addField("EEG Session编号", default_session)
    dlg.addField("业务/图片集标签", dialog_image_set_label)
    if not behavior_only:
        dlg.addField("脑电设备", str(config.get("device_type", "brainco")), choices=["brainco", "neuracle"])
        dlg.addField("使用模拟脑电", bool(config.get("hardware_dummy_mode", False)))
    dlg.addField("全屏显示", not bool(args.windowed))
    dlg.addField("本轮图片数（0=配置/固定集合）", max(0, int(args.max_trials)))
    values = dlg.show()
    if not dlg.OK:
        return None
    selected_protocol = normalize_experiment_protocol(values[1])
    value_index = 2
    session_id = 1 if behavior_only else int(values[value_index])
    if not behavior_only:
        value_index += 1
    session_type_for_id(session_id, selected_protocol)
    if not behavior_only and (selected_protocol != FORMAL_500_PROTOCOL or session_id not in {2, 3, 4, 5, 6}):
        raise ValueError("EEG观看程序只支持formal500协议的Session 2-6。")
    selected_subject = str(values[0]).strip() or "S001"
    entered_label = normalize_image_set_label(str(values[value_index]))
    if selected_protocol != default_protocol and entered_label == dialog_image_set_label:
        entered_label = default_image_set_label(selected_protocol)
    if config_locked and (
        selected_protocol != configured_protocol or entered_label != configured_label
    ):
        raise ValueError(
            "实验配置已锁定：rating和repetition必须使用config.yaml中的同一协议和图片集标签。"
        )
    return {
        "subject_id": selected_subject,
        "experiment_protocol": selected_protocol,
        "session_id": session_id,
        "image_set_label": entered_label,
        "timestamp_label": default_timestamp,
        "device_type": "none" if behavior_only else str(values[value_index + 1]).strip().lower(),
        "hardware_dummy_mode": False if behavior_only else _coerce_bool(values[value_index + 2]),
        "fullscreen": _coerce_bool(values[value_index + (1 if behavior_only else 3)]),
        "max_trials": max(0, int(values[value_index + (2 if behavior_only else 4)])),
    }


class ImageBRunner:
    def __init__(
        self,
        *,
        win: Any,
        mouse: Any,
        keyboard: Any,
        config: dict[str, Any],
        project_dir: Path,
        trials: list[ImageTrial],
        assets: list[ImageAsset],
        playlist_metadata: dict[str, Any],
        resume_state: dict[str, Any] | None = None,
        behavior_only: bool = False,
    ) -> None:
        self.win = win
        self.mouse = mouse
        self.keyboard = keyboard
        self.config = config
        self.project_dir = project_dir
        self.trials = trials
        self.assets = assets
        self.playlist_metadata = playlist_metadata
        self.resume_state = dict(resume_state or {})
        self.behavior_only = bool(behavior_only)
        self.protocol = VideoProtocolConfig.from_config(config)
        self.manager: EegSessionManager | None = None
        self.rating_rows: list[dict[str, Any]] = list(self.resume_state.get("rating_rows", []))
        self.trial_rows: list[dict[str, Any]] = list(self.resume_state.get("trial_rows", []))
        self.completed = False
        self.termination_reason = "running"
        self._run_traceback = ""
        self._memory_samples: list[dict[str, Any]] = []
        self._memory_baseline_rss_mb: float | None = None
        self._memory_pressure_count = 0
        self._psutil: Any | None = None
        if bool(protocol_value(config, "memory_monitor_enabled", True)):
            try:
                import psutil

                self._psutil = psutil
                self._memory_baseline_rss_mb = self._process_rss_mb()
            except (ImportError, OSError):
                self._psutil = None
        self.connection_summary: dict[str, Any] = {}
        self.session_dir: Path | None = None
        self.rng = random.Random(int(self.playlist_metadata.get("random_seed", 17)) + int(config.get("session_id", 1)))
        self.message = visual.TextStim(
            self.win,
            text="",
            color=FOREGROUND,
            font=FONT_NAME,
            height=0.035,
            wrapWidth=1.35,
            alignText="center",
            anchorHoriz="center",
            anchorVert="center",
        )
        self.fixation = visual.TextStim(self.win, text="+", color=FOREGROUND, font=FONT_NAME, height=0.09)
        self.placeholder = visual.TextStim(self.win, text="图片文件缺失", color=MUTED, font=FONT_NAME, height=0.04, wrapWidth=1.2)
        self._image_display_stim: Any | None = None
        self._build_reusable_stimuli()

    def _build_reusable_stimuli(self) -> None:
        """Create frequently redrawn PsychoPy/OpenGL objects only once."""

        self._rating_prompt_stim = visual.TextStim(
            self.win, text="", color=FOREGROUND, font=FONT_NAME,
            height=0.032, wrapWidth=1.2, pos=(0, 0.25),
        )
        self._rating_hint_stim = visual.TextStim(
            self.win, text="", color=MUTED, font=FONT_NAME,
            height=0.024, pos=(0, 0.16),
        )
        self._rating_boxes: list[Any] = []
        self._rating_numbers: list[Any] = []
        self._rating_labels: list[Any] = []
        for value, x_pos in zip(RATING_VALUES, [-0.42, -0.21, 0.0, 0.21, 0.42]):
            self._rating_boxes.append(
                visual.Rect(
                    self.win, width=0.15, height=0.12, pos=(x_pos, -0.02),
                    fillColor="#111827", lineColor="#475569", lineWidth=2,
                )
            )
            self._rating_numbers.append(
                visual.TextStim(
                    self.win, text=str(value), color=FOREGROUND,
                    font=FONT_NAME, height=0.042, pos=(x_pos, 0.0),
                )
            )
            self._rating_labels.append(
                visual.TextStim(
                    self.win, text="", color=MUTED, font=FONT_NAME,
                    height=0.018, wrapWidth=0.18, pos=(x_pos, -0.13),
                )
            )
        self._practice_progress_stim = visual.TextStim(
            self.win, text="", color=MUTED, font=FONT_NAME,
            height=0.022, pos=(0, 0.34),
        )
        self._attention_title_stim = visual.TextStim(
            self.win, text="刚才的图片中是否有人物？", color=FOREGROUND,
            font=FONT_NAME, height=0.036, pos=(0, 0.16),
        )
        self._attention_left_stim = visual.TextStim(
            self.win, text="F = 否", color=FOREGROUND,
            font=FONT_NAME, height=0.034, pos=(-0.24, -0.03),
        )
        self._attention_right_stim = visual.TextStim(
            self.win, text="J = 是", color=FOREGROUND,
            font=FONT_NAME, height=0.034, pos=(0.24, -0.03),
        )
        self._attention_footer_stim = visual.TextStim(
            self.win, text="", color=MUTED, font=FONT_NAME,
            height=0.024, pos=(0, -0.20),
        )
        self._subtitle_stim = visual.TextStim(
            self.win, text="", color=MUTED, font=FONT_NAME,
            height=0.026, wrapWidth=1.2, pos=(0, -0.08),
        )
        self._attention_confirm_stim = visual.TextStim(
            self.win, text="", color=MUTED, font=FONT_NAME,
            height=0.024, pos=(0, -0.22),
        )

    def run(self) -> None:
        try:
            self._show_instructions()
            if self.resume_state:
                self._show_text(
                    f"检测到上次中断记录：已完成 trial {self.resume_state['completed_trial']}。\n\n"
                    f"本次将从 trial {self.resume_state['next_trial']} 继续，不重复练习和基线。\n\n"
                    "按空格键继续。"
                )
            elif self._should_run_practice():
                self._run_practice()
            if self.behavior_only:
                self._start_behavior_recording()
            else:
                self._show_text("即将进行脑电连接检查。\n\n请确认脑电设备已开启并准备好。\n\n按空格键继续。")
                self.connection_summary = self._check_eeg_connection()
                self._show_text(self._connection_success_text())
                self._start_eeg()
            self._run_formal()
            self.completed = True
            self.termination_reason = "completed"
        except MemorySafetyAbort as exc:
            self.termination_reason = "memory_safety_abort"
            self._run_traceback = str(exc)
            self._show_text(
                "检测到内存压力持续超过安全阈值。已保存刚完成试次的数据，程序将安全退出；下次可从断点继续。",
                wait_for_key=False,
                duration=2.0,
            )
        except ExperimentAbort:
            self.termination_reason = "operator_abort"
            self._show_text("实验已中止，正在保存已采集的数据。", wait_for_key=False, duration=1.0)
        except Exception as exc:
            self.termination_reason = "python_exception"
            self._run_traceback = traceback.format_exc()
            self._show_text(f"实验运行出错：\n{_format_eeg_error(exc, self.config)}\n\n按空格键退出。")
        finally:
            if self.manager is not None and self.manager.background_error is not None:
                self.termination_reason = "eeg_background_error"
            try:
                session_dir = self._stop_and_export()
            except Exception as exc:
                self._run_traceback = traceback.format_exc()
                if self.manager is not None and self.manager.session_dir is not None:
                    (self.manager.session_dir / "crash_report.txt").write_text(
                        self._run_traceback, encoding="utf-8"
                    )
                phase = "行为数据" if self.behavior_only else "脑电数据"
                self._show_text(f"{phase}安全保存失败：\n{_format_eeg_error(exc, self.config)}\n\n按空格键退出。")
                session_dir = None
            if session_dir is not None and self.manager is not None and self.manager.background_error is not None:
                if not self._run_traceback:
                    error = self.manager.background_error
                    self._run_traceback = "".join(
                        traceback.format_exception(type(error), error, error.__traceback__)
                    )
                self._show_text(
                    "脑电后台采集发生错误，已安全停止并保存此前数据：\n"
                    f"{_format_eeg_error(self.manager.background_error, self.config)}\n\n按空格键继续。"
                )
            if session_dir is not None:
                self.session_dir = session_dir
                if self._run_traceback:
                    (session_dir / "crash_report.txt").write_text(self._run_traceback, encoding="utf-8")
                bcigo_text = ""
                if _uses_bcigo_external_recording(self.config):
                    bcigo_text = (
                        "\n\nBCIGo 可继续录制下一个 session；请在全部 session 完成后再停止录制。"
                    )
                self._show_text(f"数据已保存：\n{session_dir}{bcigo_text}\n\n按空格键退出。")

    def _start_behavior_recording(self) -> None:
        from acquisition.external_recorder_acquirer import ExternalRecorderAcquirer
        from utils.markers import NoOpMarkerBackend

        records_dir = self.project_dir / Path(str(self.config.get("storage", {}).get("records_dir", "records_storage")))
        self.connection_summary = {
            "device": "none",
            "recording_mode": "behavior_only",
            "external_markers": False,
        }
        self.manager = EegSessionManager(
            ExternalRecorderAcquirer(sfreq=1.0, n_channels=1, backend_name="behavior_only"),
            NoOpMarkerBackend(),
            sfreq=1.0,
            records_dir=records_dir,
            subject_id=str(self.config.get("subject_id", "S001")),
            session_id=1,
            record_local_eeg=False,
        )
        resume_output_dir = Path(self.resume_state["source_dir"]) if self.resume_state else None
        segment_start_trial = int(self.resume_state.get("next_trial", 1))
        session_dir = self.manager.start(
            metadata={
                "task_mode": "image_b",
                "collection_phase": "behavior_rating",
                "experiment_protocol": self.config.get("experiment_protocol"),
                "session_dir_layout": "subject_timestamp_session",
                "timestamp_label": self.config.get("timestamp_label"),
                "image_set_label": self.config.get("image_set_label"),
                "session_type": "labeling",
                "image_trials": len(self.trials),
                "image_unique_count": len(self.assets),
                "playlist_seed": self.playlist_metadata.get("random_seed"),
                "playlist_metadata": self.playlist_metadata,
                "subject_image_set_path": self.playlist_metadata.get("subject_image_set_path"),
                "psychopy_runner": True,
                "segment_start_trial": segment_start_trial,
                "resumed": bool(self.resume_state),
                "eeg_recording_mode": "none",
                "device_type": "none",
                "external_markers_sent": False,
            },
            output_dir=resume_output_dir,
        )
        self._write_resume_manifest(session_dir)
        if self.resume_state:
            # Promote a legacy checkpoint before the participant resumes.
            self._write_resume_checkpoint()

    def _check_eeg_connection(self) -> dict[str, Any]:
        try:
            if _uses_bcigo_external_recording(self.config):
                return _probe_bcigo_marker_connection(self.config)
            return _probe_eeg_connection(self.config)
        except Exception as exc:
            self._show_text(f"脑电连接检查失败：\n{_format_eeg_error(exc, self.config)}\n\n按空格键退出。")
            raise ExperimentAbort() from exc

    @staticmethod
    def _wait_for_probe_chunk(acquirer: Any, *, window_sec: float, timeout_sec: float) -> np.ndarray:
        return _wait_for_probe_chunk(acquirer, window_sec=window_sec, timeout_sec=timeout_sec)

    def _connection_success_text(self) -> str:
        info = self.connection_summary
        if info.get("recording_mode") == "bcigo_external_edf":
            return (
                "BCIGo Marker 连接检查通过。\n\n"
                "EEG 由 BCIGo 持续写入 EDF；本程序不会停止或复制该 EDF。\n"
                f"Marker 流：{info.get('marker_stream')}\n"
                "首次 session 前开始一次 BCIGo 录制，之后可连续运行多个 session。\n\n"
                "按空格键开始正式实验。"
            )
        return (
            "脑电连接检查通过。\n\n"
            f"设备：{info.get('device')}\n"
            f"通道数：{info.get('channels')}\n"
            f"采样率：{info.get('sfreq')} Hz\n"
            f"检查样本数：{info.get('samples')}\n"
            f"均值/标准差：{info.get('mean'):.3f} / {info.get('std'):.3f}\n\n"
            "按空格键开始正式实验。"
        )

    def _start_eeg(self) -> None:
        acquirer = build_acquirer(device_name=str(self.config.get("device_type", "brainco")), config=self.config)
        marker_backend = build_marker_backend(self.config)
        records_dir = self.project_dir / Path(str(self.config.get("storage", {}).get("records_dir", "records_storage")))
        self.manager = EegSessionManager(
            acquirer,
            marker_backend,
            sfreq=float(self.config.get("sfreq", 250.0)),
            records_dir=records_dir,
            subject_id=str(self.config.get("subject_id", "S001")),
            session_id=int(self.config.get("session_id", 1)),
            record_local_eeg=not _uses_bcigo_external_recording(self.config),
        )
        resume_output_dir = Path(self.resume_state["source_dir"]) if self.resume_state else None
        segment_start_trial = int(self.resume_state.get("next_trial", 1))
        session_dir = self.manager.start(
            metadata={
                "task_mode": "image_b",
                "collection_phase": "eeg_repeat",
                "experiment_protocol": self.config.get("experiment_protocol"),
                "session_dir_layout": "subject_timestamp_session",
                "timestamp_label": self.config.get("timestamp_label"),
                "image_set_label": self.config.get("image_set_label"),
                "session_type": self.config.get("session_type"),
                "image_trials": len(self.trials),
                "image_unique_count": len(self.assets),
                "playlist_seed": self.playlist_metadata.get("random_seed"),
                "playlist_metadata": self.playlist_metadata,
                "subject_image_set_path": self.playlist_metadata.get("subject_image_set_path"),
                "eeg_connection_check": self.connection_summary,
                "psychopy_runner": True,
                "segment_start_trial": segment_start_trial,
                "resumed": bool(self.resume_state),
                "eeg_recording_mode": (
                    "bcigo_external_edf"
                    if _uses_bcigo_external_recording(self.config)
                    else "local_continuous_eeg"
                ),
                "bcigo_recording_scope": (
                    "continuous_across_sessions"
                    if _uses_bcigo_external_recording(self.config)
                    else None
                ),
            },
            output_dir=resume_output_dir,
        )
        self._write_resume_manifest(session_dir)

    def _write_resume_manifest(self, session_dir: Path) -> None:
        (session_dir / ".resume_manifest.json").write_text(
            json.dumps(
                {
                    "subject_id": self.config.get("subject_id"),
                    "session_id": self.config.get("session_id"),
                    "experiment_protocol": self.config.get("experiment_protocol"),
                    "image_set_label": self.config.get("image_set_label"),
                    "task_mode": "image_b",
                    "collection_phase": self.config.get("collection_phase"),
                    "image_trials": len(self.trials),
                    "completed": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _run_formal(self) -> None:
        manager = self._require_manager()
        baseline_sec = float(self.protocol.baseline_sec)
        if baseline_sec > 0 and not self.resume_state and not self.behavior_only:
            self._show_phase(
                "+",
                "基线采集，请保持静止。",
                baseline_sec,
                on_start=[(manager.emit, ("baseline_start",), {"duration_sec": baseline_sec})],
                on_end=[(manager.emit, ("baseline_end",), {"duration_sec": baseline_sec})],
            )
        next_trial = int(self.resume_state.get("next_trial", 1))
        pending_trials = [trial for trial in self.trials if trial.trial_idx >= next_trial]
        active_block: int | None = None
        for trial in pending_trials:
            self._check_abort()
            if trial.block_idx != active_block:
                if active_block is not None:
                    manager.emit(
                        "block_end",
                        block_idx=active_block,
                        completed_trials=trial.trial_idx - 1,
                    )
                    self._run_block_break(active_block, trial.block_idx, trial.trial_idx - 1)
                active_block = trial.block_idx
                manager.emit(
                    "block_start",
                    block_idx=active_block,
                    block_trial_idx=trial.block_trial_idx,
                    trial_idx=trial.trial_idx,
                    resumed=bool(self.resume_state),
                )
            self._run_trial(trial)
        if active_block is not None:
            manager.emit(
                "block_end",
                block_idx=active_block,
                completed_trials=len(self.trials),
            )

    def _run_block_break(self, completed_block: int, next_block: int, completed_trials: int) -> None:
        manager = self._require_manager()
        session_type = str(self.config.get("session_type", "denoise"))
        prefix = "image_rating_block_break" if session_type == "labeling" else "image_repeat_block_break"
        default_min = 60.0 if session_type == "labeling" else 30.0
        default_max = 60.0 if session_type == "labeling" else 45.0
        min_sec = max(0.0, float(protocol_value(self.config, f"{prefix}_min_sec", default_min)))
        max_sec = max(min_sec, float(protocol_value(self.config, f"{prefix}_max_sec", default_max)))
        manager.emit(
            "block_rest_start",
            completed_block=completed_block,
            next_block=next_block,
            completed_trials=completed_trials,
            planned_min_sec=min_sec,
            planned_max_sec=max_sec,
        )
        started = time.perf_counter()
        self._clear_keyboard()
        while True:
            self._check_abort()
            elapsed = time.perf_counter() - started
            if elapsed < min_sec:
                status = f"请休息，{max(0, int(min_sec - elapsed + 0.999))} 秒后可以继续。"
            elif max_sec > min_sec:
                status = "休息时间已满足。\n按空格键继续；若不操作将自动进入下一组。"
                if self.keyboard.getKeys(["space"], waitRelease=False, clear=True):
                    break
            else:
                break
            if elapsed >= max_sec:
                break
            self.message.text = (
                f"已完成 {completed_trials}/{len(self.trials)} 张\n"
                f"Block {completed_block}/{self.playlist_metadata.get('block_count', 1)} 完成\n\n"
                f"{status}\n\n下一组：Block {next_block}"
            )
            self.message.draw()
            self.win.flip()
            core.wait(0.05)
        actual_sec = time.perf_counter() - started
        manager.emit(
            "block_rest_end",
            completed_block=completed_block,
            next_block=next_block,
            actual_duration_sec=actual_sec,
        )

    def _run_trial(self, trial: ImageTrial) -> None:
        manager = self._require_manager()
        eeg_session_dir = None if self.behavior_only else (str(manager.session_dir) if manager.session_dir else None)
        eeg_part = None if self.behavior_only else manager.eeg_part
        eeg_file = None if self.behavior_only else manager.eeg_filename
        fixation_sec = self._jitter("image_fixation", 0.5, 0.8)
        image_sec = self._jitter("image_present", 2, 3)
        self._show_fixation(
            fixation_sec,
            on_start=[
                (manager.begin_trial, (), {"trial_idx": trial.trial_idx, "video_name": trial.asset.image_id}),
                (manager.fixation_on, (), {"trial_idx": trial.trial_idx, "video_name": trial.asset.image_id}),
            ],
        )
        self._show_image(
            trial,
            image_sec,
            on_start=[
                (manager.fixation_off, (), {"trial_idx": trial.trial_idx}),
                (manager.emit, ("image_on",), {"trial_idx": trial.trial_idx, "image_id": trial.asset.image_id}),
            ],
        )
        extra_log: dict[str, Any] = {}
        if trial.trial_type == "rating":
            self._run_rating_trial(
                trial,
                eeg_session_dir=eeg_session_dir,
                eeg_part=eeg_part,
                eeg_file=eeg_file,
            )
        else:
            self._flip_blank([(manager.emit, ("image_off",), {"trial_idx": trial.trial_idx, "image_id": trial.asset.image_id})])
            if trial.attention_task_presented:
                extra_log = self._run_attention_task(trial)
        iti_sec = self._trial_iti_sec(trial.trial_type)
        self._show_phase(
            "",
            "",
            iti_sec,
            on_start=[(manager.iti_on, (), {"trial_idx": trial.trial_idx})],
            on_end=[
                (manager.iti_off, (), {"trial_idx": trial.trial_idx}),
                (manager.end_trial, (), {"trial_idx": trial.trial_idx, "video_name": trial.asset.image_id}),
            ],
        )
        self.trial_rows.append(
            make_trial_log_row(
                self.config,
                trial,
                extra=extra_log,
                eeg_session_dir=eeg_session_dir,
                eeg_part=eeg_part,
                eeg_file=eeg_file,
            )
        )
        self._write_resume_checkpoint()
        self._check_memory_safety(trial.trial_idx)

    def _write_resume_checkpoint(self) -> None:
        manager = self._require_manager()
        if manager.session_dir is None:
            return
        # Keep the hot-path checkpoint linear in completed rows. Event enrichment is
        # intentionally deferred to final export; resume only needs raw completed rows.
        trials = [dict(row) for row in self.trial_rows]
        trial_columns = list(trials[0].keys()) if trials else []
        write_rows_csv(manager.session_dir / "trial_log.csv", trials, trial_columns)
        if str(self.config.get("session_type")) == "labeling":
            ratings = [dict(row) for row in self.rating_rows]
            columns = list(ratings[0].keys()) if ratings else []
            write_rows_csv(manager.session_dir / "behavioral_ratings.csv", ratings, columns)

    def _run_rating_trial(
        self,
        trial: ImageTrial,
        *,
        eeg_session_dir: str | None,
        eeg_part: int | None,
        eeg_file: str | None,
    ) -> None:
        manager = self._require_manager()
        self._show_phase(
            "",
            "",
            float(protocol_value(self.config, "image_blank_sec", 0.5)),
            on_start=[
                (manager.emit, ("image_off",), {"trial_idx": trial.trial_idx, "image_id": trial.asset.image_id}),
                (manager.blank_on, (), {"trial_idx": trial.trial_idx}),
            ],
            on_end=[(manager.blank_off, (), {"trial_idx": trial.trial_idx})],
        )

        ratings: dict[str, int | None] = {}
        item_timings: dict[str, dict[str, Any]] = {}
        manager.rating_on(trial_idx=trial.trial_idx, video_name=trial.asset.image_id)
        rating_onset = time.perf_counter()
        for item_index, dimension in enumerate(RATING_DIMENSIONS, start=1):
            key = str(dimension["key"])
            value, rt_ms, no_keypress, onset, offset = self._run_rating_item(
                trial=trial,
                dimension=dimension,
                item_index=item_index,
            )
            ratings[key] = value
            item_timings[key] = {
                "onset": onset,
                "offset": offset,
                "rt_ms": rt_ms,
                "timed_out": False,
                "no_keypress": no_keypress,
            }
        rating_offset = time.perf_counter()
        manager.rating_off(trial_idx=trial.trial_idx)
        row = make_rating_row(
            self.config,
            trial,
            ratings=ratings,
            item_timings=item_timings,
            timed_out=False,
            eeg_session_dir=eeg_session_dir,
            eeg_part=eeg_part,
            eeg_file=eeg_file,
        )
        row["rating_onset"] = rating_onset
        row["rating_offset"] = rating_offset
        self.rating_rows.append(row)

    def _run_rating_item(
        self,
        *,
        trial: ImageTrial,
        dimension: dict[str, Any],
        item_index: int,
    ) -> tuple[int, int | None, bool, float, float]:
        manager = self._require_manager()
        selected = 3
        responded = False
        rt_ms: int | None = None
        start = time.perf_counter()
        self._clear_keyboard()
        self.win.callOnFlip(
            manager.emit,
            "rating_item_on",
            trial_idx=trial.trial_idx,
            image_id=trial.asset.image_id,
            item_key=dimension["key"],
            item_index=item_index,
        )
        while True:
            self._check_abort()
            self._draw_rating_screen(dimension, selected)
            self.win.flip()
            keys = self.keyboard.getKeys(["f", "j", "space"], waitRelease=False, clear=True)
            if keys:
                responded = True
                if rt_ms is None:
                    rt_ms = int((time.perf_counter() - start) * 1000)
                key_name = keys[-1].name.lower()
                if key_name == "f":
                    selected = max(1, selected - 1)
                elif key_name == "j":
                    selected = min(5, selected + 1)
                elif key_name == "space":
                    break
            else:
                core.wait(0.005)
        offset = time.perf_counter()
        self.win.callOnFlip(
            manager.emit,
            "rating_item_off",
            trial_idx=trial.trial_idx,
            image_id=trial.asset.image_id,
            item_key=dimension["key"],
            item_index=item_index,
            rating_value=selected,
            no_keypress=not responded,
        )
        self._draw_rating_screen(dimension, selected)
        self.win.flip()
        core.wait(0.08)
        return selected, rt_ms, not responded, start, offset

    def _run_attention_task(self, trial: ImageTrial) -> dict[str, Any]:
        manager = self._require_manager()
        correct_answer = bool(trial.asset.has_person) if trial.asset.has_person is not None else False
        response: bool | None = None
        rt_ms: int | None = None
        duration = float(protocol_value(self.config, "image_attention_sec", 2.0))
        start = time.perf_counter()
        self._clear_keyboard()
        self.win.callOnFlip(
            manager.emit,
            "attention_task_on",
            trial_idx=trial.trial_idx,
            image_id=trial.asset.image_id,
            task_type="has_person",
        )
        while (time.perf_counter() - start) < duration and response is None:
            self._check_abort()
            self._draw_attention_screen()
            self.win.flip()
            key_response = self._attention_key_response()
            if key_response is not None:
                response = key_response
                rt_ms = int((time.perf_counter() - start) * 1000)
                manager.emit(
                    "attention_response",
                    trial_idx=trial.trial_idx,
                    image_id=trial.asset.image_id,
                    response="yes" if response else "no",
                    response_mode="keyboard",
                    rt_ms=rt_ms,
                )
            else:
                core.wait(0.005)
        timed_out = response is None
        if timed_out:
            response = False
        return {
            "attention_task_onset": start,
            "attention_response": "yes" if response else "no",
            "attention_response_mode": "" if timed_out else "keyboard",
            "attention_response_time": rt_ms,
            "attention_correct": bool(response == correct_answer),
            "attention_timed_out": timed_out,
            "reaction_time_ms": rt_ms,
        }

    def _run_practice(self) -> None:
        if not self.trials:
            return
        trial = self.trials[0]
        self._show_text("练习阶段。\n\n请观看图片；出现评分或注意力问题时使用 F/J 作答。\n\n按空格键开始练习。")
        self._show_fixation(0.4)
        self._show_image(trial, min(1.0, self._jitter("image_present", 1.0, 1.5)))
        if trial.trial_type == "rating":
            self._show_text("接下来介绍正式标注中的评分题目。\n\n本阶段只用于熟悉题目，不记录评分。\n\n按空格键查看第一题说明。")
            for item_index, dimension in enumerate(RATING_DIMENSIONS, start=1):
                self._practice_rating_item(dimension, item_index, len(RATING_DIMENSIONS))
        else:
            self._practice_attention_task()
        self._show_text("练习结束。\n\n按空格键继续。")

    def _should_run_practice(self) -> bool:
        protocol_name = normalize_experiment_protocol(
            self.config.get("experiment_protocol", FORMAL_500_PROTOCOL)
        )
        session_id = int(self.config.get("session_id", 1))
        return protocol_name == PILOT_105_PROTOCOL or session_id in {1, 2}

    def _show_instructions(self) -> None:
        session_id = int(self.config.get("session_id", 1))
        protocol_name = normalize_experiment_protocol(
            self.config.get("experiment_protocol", FORMAL_500_PROTOCOL)
        )
        session_type = str(
            self.config.get("session_type", session_type_for_id(session_id, protocol_name))
        )
        block_count = int(self.playlist_metadata.get("block_count", 1))
        block_size = int(self.playlist_metadata.get("block_size", len(self.trials)))
        if session_type == "labeling":
            body = (
                "图片标注轮次。\n\n"
                "每张图片结束后会逐题评分。\n"
                "每题默认值为 3；按 F 向左调整，按 J 向右调整，按空格确认并进入下一题。\n"
                "每题不限时，请根据自己的判断完成后再确认。\n\n"
                f"本轮共 {len(self.trials)} 张，分为 {block_count} 个Block，每个Block最多 {block_size} 张。\n\n"
                "按空格键开始。"
            )
        else:
            body = (
                "脑电去噪采集轮次。\n\n"
                "请注视每张图片并尽量保持静止。\n"
                "如出现注意力问题，按 F 表示“否”，按 J 表示“是”。\n"
                f"本轮共 {len(self.trials)} 张，分为 {block_count} 个Block，每个Block最多 {block_size} 张。\n\n"
                "按空格键开始。"
            )
        protocol_label = "500张正式实验" if protocol_name == FORMAL_500_PROTOCOL else "105张预实验"
        self._show_text(
            f"被试编号：{self.config.get('subject_id')}\n"
            f"协议：{protocol_label}\n"
            f"实验轮次：{session_id}（{_session_type_label(session_type)}）\n\n{body}"
        )

    def _show_fixation(
        self,
        duration_sec: float,
        *,
        on_start: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] | None = None,
        on_end: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] | None = None,
    ) -> None:
        self.fixation.draw()
        self._schedule_callbacks(on_start)
        self.win.flip()
        core.wait(max(0.0, duration_sec))
        self._schedule_callbacks(on_end)
        self.win.flip()

    def _show_image(
        self,
        trial: ImageTrial,
        duration_sec: float,
        *,
        on_start: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] | None = None,
        on_end: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] | None = None,
    ) -> None:
        stim = self._image_stim(trial.asset)
        if stim is None:
            self.placeholder.text = f"图片文件缺失\n{trial.asset.rel_path}"
            self.placeholder.draw()
        else:
            stim.draw()
        self.fixation.draw()
        try:
            planned_flip_time = float(self.win.getFutureFlipTime(clock="ptb"))
        except (AttributeError, TypeError, ValueError):
            planned_flip_time = None
        if planned_flip_time is not None:
            enriched_callbacks = []
            for fn, args, kwargs in on_start or []:
                updated = dict(kwargs)
                if args and args[0] == "image_on":
                    updated["planned_flip_time_ptb_sec"] = planned_flip_time
                enriched_callbacks.append((fn, args, updated))
            on_start = enriched_callbacks
        self._schedule_callbacks(on_start)
        self.win.flip()
        core.wait(max(0.0, duration_sec))
        self._schedule_callbacks(on_end)
        self.win.flip()

    def _show_phase(
        self,
        text: str,
        subtitle: str,
        duration_sec: float,
        *,
        on_start: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] | None = None,
        on_end: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] | None = None,
    ) -> None:
        if text:
            self.message.text = text
            self.message.height = 0.055
            self.message.pos = (0, 0.05)
            self.message.draw()
        if subtitle:
            self._subtitle_stim.text = subtitle
            self._subtitle_stim.draw()
        self._schedule_callbacks(on_start)
        self.win.flip()
        core.wait(max(0.0, duration_sec))
        self._schedule_callbacks(on_end)
        self.win.flip()

    def _show_text(self, text: str, *, wait_for_key: bool = True, duration: float | None = None) -> None:
        self.message.text = text
        self.message.height = 0.035
        self.message.pos = (0, 0)
        self.message.draw()
        self.win.flip()
        if duration is not None:
            core.wait(max(0.0, duration))
            return
        if wait_for_key:
            self._clear_keyboard()
            while True:
                self._check_abort()
                keys = self.keyboard.getKeys(["space"], waitRelease=False, clear=True)
                if keys:
                    break
                core.wait(0.01)

    def _draw_rating_screen(self, dimension: dict[str, Any], selected: int) -> None:
        self._draw_rating_controls(
            dimension,
            selected,
            hint="F 向左   J 向右   空格确认        本题不限时",
        )

    def _draw_rating_controls(self, dimension: dict[str, Any], selected: int, *, hint: str) -> None:
        self._rating_prompt_stim.text = str(dimension["prompt"])
        self._rating_hint_stim.text = hint
        self._rating_prompt_stim.draw()
        self._rating_hint_stim.draw()
        levels = tuple(dimension.get("levels", ("1", "2", "3", "4", "5")))
        for index, value in enumerate(RATING_VALUES):
            box = self._rating_boxes[index]
            number = self._rating_numbers[index]
            label = self._rating_labels[index]
            box.fillColor = SELECTED if value == selected else "#111827"
            box.lineColor = ACCENT if value == selected else "#475569"
            label.text = str(levels[value - 1])
            label.color = FOREGROUND if value == selected else MUTED
            box.draw()
            number.draw()
            label.draw()

    def _practice_rating_item(self, dimension: dict[str, Any], item_index: int, total_items: int) -> None:
        label = str(dimension.get("label", "评分题目"))
        selected = 3
        self._clear_keyboard()
        while True:
            self._check_abort()
            self._draw_rating_controls(
                dimension,
                selected,
                hint=f"练习操作：F 向左，J 向右。当前选择为 {selected}。按空格键进入下一步。",
            )
            self._practice_progress_stim.text = f"评分题 {item_index}/{total_items} ：{label}"
            self._practice_progress_stim.draw()
            self.win.flip()
            keys = self.keyboard.getKeys(["f", "j", "space"], waitRelease=False, clear=True)
            if not keys:
                core.wait(0.01)
                continue
            key_name = keys[-1].name.lower()
            if key_name == "f":
                selected = max(1, selected - 1)
            elif key_name == "j":
                selected = min(5, selected + 1)
            elif key_name == "space":
                return

    def _practice_attention_task(self) -> None:
        self._show_text("接下来练习注意力问题。\n\n看到问题后，请按 F 表示“否”，按 J 表示“是”。\n\n本阶段只用于练习，不记录结果。")
        self._clear_keyboard()
        response_text = ""
        while True:
            self._check_abort()
            self._draw_attention_screen()
            self._attention_footer_stim.text = response_text or "请按 F 或 J 作答。"
            self._attention_footer_stim.draw()
            self.win.flip()
            keys = self.keyboard.getKeys(["f", "j"], waitRelease=False, clear=True)
            if not keys:
                core.wait(0.01)
                continue
            response_text = "已选择：否" if keys[-1].name.lower() == "f" else "已选择：是"
            self._draw_attention_screen()
            self._attention_confirm_stim.text = f"{response_text}\n\n按空格键继续。"
            self._attention_confirm_stim.draw()
            self.win.flip()
            self._wait_for_space()
            return

    def _draw_attention_screen(self) -> None:
        self._attention_title_stim.draw()
        self._attention_left_stim.draw()
        self._attention_right_stim.draw()

    def _attention_key_response(self) -> bool | None:
        keys = self.keyboard.getKeys(["f", "j"], waitRelease=False, clear=True)
        if not keys:
            return None
        return keys[-1].name.lower() == "j"

    def _image_stim(self, asset: ImageAsset) -> Any | None:
        path = image_path(self.config, asset, base_dir=self.project_dir)
        if not path.exists() or not path.is_file():
            return None
        size = self._contained_image_size(path)
        if self._image_display_stim is None:
            self._image_display_stim = visual.ImageStim(
                self.win,
                image=str(path),
                size=size,
                interpolate=True,
                units="height",
            )
        else:
            self._image_display_stim.setImage(str(path), log=False)
            self._image_display_stim.size = size
        return self._image_display_stim

    def _contained_image_size(self, path: Path) -> tuple[float, float]:
        try:
            from PIL import Image

            with Image.open(path) as image:
                width, height = image.size
        except Exception:
            return (1.1, 0.75)
        if width <= 0 or height <= 0:
            return (1.1, 0.75)
        aspect = width / height
        max_h = 0.78
        max_w = 1.28
        h = max_h
        w = h * aspect
        if w > max_w:
            w = max_w
            h = w / aspect
        return (w, h)

    def _flip_blank(
        self,
        callbacks: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] | None = None,
    ) -> None:
        self._schedule_callbacks(callbacks)
        self.win.flip()

    def _schedule_callbacks(
        self,
        callbacks: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] | None,
    ) -> None:
        for fn, args, kwargs in callbacks or []:
            self.win.callOnFlip(fn, *args, **kwargs)

    def _check_abort(self) -> None:
        keys = self.keyboard.getKeys(["escape"], waitRelease=False, clear=False)
        if keys:
            raise ExperimentAbort()

    def _clear_keyboard(self) -> None:
        try:
            self.keyboard.clearEvents()
        except Exception:
            event.clearEvents()

    def _wait_for_space(self) -> None:
        self._clear_keyboard()
        while True:
            self._check_abort()
            keys = self.keyboard.getKeys(["space"], waitRelease=False, clear=True)
            if keys:
                return
            core.wait(0.01)

    def _jitter(self, prefix: str, default_min: float, default_max: float) -> float:
        min_sec = float(protocol_value(self.config, f"{prefix}_min_sec", default_min))
        max_sec = float(protocol_value(self.config, f"{prefix}_max_sec", default_max))
        if max_sec <= min_sec:
            return max(0.0, min_sec)
        return self.rng.uniform(min_sec, max_sec)

    def _trial_iti_sec(self, trial_type: str) -> float:
        if trial_type == "rating":
            return self._jitter("image_rating_iti", 1.0, 1.5)
        return self._jitter("image_repeat_blank", 0.1, 0.1)

    def _require_manager(self) -> EegSessionManager:
        if self.manager is None:
            raise RuntimeError("脑电 session 尚未启动。")
        return self.manager

    def _process_rss_mb(self) -> float:
        if self._psutil is None:
            return 0.0
        return float(self._psutil.Process(os.getpid()).memory_info().rss) / (1024.0 * 1024.0)

    def _check_memory_safety(self, trial_idx: int) -> None:
        """Persist bounded diagnostics and stop safely before memory exhaustion."""
        if self._psutil is None:
            return
        interval = max(1, int(protocol_value(self.config, "memory_check_every_trials", 5)))
        if trial_idx % interval != 0 and trial_idx != len(self.trials):
            return
        rss_mb = self._process_rss_mb()
        baseline_mb = self._memory_baseline_rss_mb or rss_mb
        growth_mb = max(0.0, rss_mb - baseline_mb)
        available_mb = float(self._psutil.virtual_memory().available) / (1024.0 * 1024.0)
        manager = self._require_manager()
        event_count = int(manager.recorder.event_count)
        sample = {
            "trial_idx": int(trial_idx),
            "time_monotonic_sec": time.monotonic(),
            "rss_mb": round(rss_mb, 2),
            "rss_growth_mb": round(growth_mb, 2),
            "system_available_mb": round(available_mb, 2),
            "event_count": event_count,
            "rating_rows": len(self.rating_rows),
            "trial_rows": len(self.trial_rows),
        }
        self._memory_samples.append(sample)
        max_samples = max(4, (len(self.trials) // interval) + 2)
        if len(self._memory_samples) > max_samples:
            del self._memory_samples[:-max_samples]
        if manager.session_dir is not None:
            write_rows_csv(
                manager.session_dir / "memory_usage.csv",
                self._memory_samples,
                list(sample.keys()),
            )
        max_rows = len(self.trials)
        max_events = int(protocol_value(self.config, "memory_max_events", 50000))
        structural_overflow = (
            len(self.rating_rows) > max_rows
            or len(self.trial_rows) > max_rows
            or event_count > max_events
        )
        pressure = (
            rss_mb >= float(protocol_value(self.config, "memory_max_rss_mb", 4096.0))
            or growth_mb >= float(protocol_value(self.config, "memory_max_growth_mb", 2048.0))
            or available_mb <= float(protocol_value(self.config, "memory_min_available_mb", 768.0))
        )
        self._memory_pressure_count = self._memory_pressure_count + 1 if pressure else 0
        if structural_overflow or self._memory_pressure_count >= 2 or available_mb <= 256.0:
            raise MemorySafetyAbort(
                f"trial={trial_idx}, rss_mb={rss_mb:.1f}, growth_mb={growth_mb:.1f}, "
                f"available_mb={available_mb:.1f}, events={event_count}, "
                f"rating_rows={len(self.rating_rows)}, trial_rows={len(self.trial_rows)}"
            )

    def release_visual_resources(self) -> None:
        """Release PsychoPy textures while the OpenGL context is still alive."""
        stimuli = [
            self._image_display_stim,
            self.message,
            self.fixation,
            self.placeholder,
            self._rating_prompt_stim,
            self._rating_hint_stim,
            self._practice_progress_stim,
            self._attention_title_stim,
            self._attention_left_stim,
            self._attention_right_stim,
            self._attention_footer_stim,
            self._subtitle_stim,
            self._attention_confirm_stim,
            *self._rating_boxes,
            *self._rating_numbers,
            *self._rating_labels,
        ]
        for stimulus in stimuli:
            clear_textures = getattr(stimulus, "clearTextures", None)
            if callable(clear_textures):
                try:
                    clear_textures()
                except Exception:
                    pass
        self._image_display_stim = None

    def _stop_and_export(self) -> Path | None:
        if self.manager is None:
            return None
        session_dir = self.manager.stop_and_export(
            metadata={
                "completed": self.completed,
                "collection_phase": self.config.get("collection_phase"),
                "experiment_protocol": self.config.get("experiment_protocol"),
                "session_type": self.config.get("session_type"),
                "eeg_recording_mode": (
                    "none"
                    if self.behavior_only
                    else (
                        "bcigo_external_edf"
                        if _uses_bcigo_external_recording(self.config)
                        else "local_continuous_eeg"
                    )
                ),
                "external_markers_sent": not self.behavior_only,
                "timestamp_label": self.config.get("timestamp_label"),
                "rating_trials": len(self.rating_rows),
                "trial_log_rows": len(self.trial_rows),
                "termination_reason": self.termination_reason,
                "segment_start_trial": int(self.resume_state.get("next_trial", 1)),
                "segment_end_trial": max(
                    (int(row.get("trial_idx", 0)) for row in self.trial_rows),
                    default=0,
                ),
            }
        )
        if session_dir is None:
            return None
        events = []
        if self.manager.recorder is not None:
            events = list(getattr(self.manager.recorder, "events", []))
        ratings, trials, trial_columns = build_output_rows(self.rating_rows, self.trial_rows, events)
        if str(self.config.get("session_type")) == "labeling":
            write_rows_csv(session_dir / "behavioral_ratings.csv", ratings, list(ratings[0].keys()) if ratings else [])
        write_rows_csv(session_dir / "trial_log.csv", trials, trial_columns)
        write_playlist_json(session_dir / "image_playlist.json", self.trials)
        for checkpoint in (
            session_dir / ".trial_log.checkpoint.csv",
            session_dir / ".behavioral_ratings.checkpoint.csv",
            session_dir / ".behavioral_rating.checkpoint.csv",
            session_dir / ".resume_manifest.json",
        ):
            if checkpoint.exists():
                checkpoint.unlink()
        records_dir = self.project_dir / Path(str(self.config.get("storage", {}).get("records_dir", "records_storage")))
        write_subject_completion_status(
            records_dir,
            subject_id=str(self.config.get("subject_id", "S001")),
            image_set_label=str(self.config.get("image_set_label", "default")),
            image_ids=[asset.image_id for asset in self.assets],
        )
        return session_dir


def find_resume_state(
    records_dir: Path,
    *,
    subject_id: str,
    session_id: int,
    trials: list[ImageTrial],
    image_set_label: str = "default",
) -> dict[str, Any] | None:
    """Return the latest compatible incomplete Image B session checkpoint."""

    subject_root = records_dir / subject_id
    if not subject_root.exists() or not trials:
        return None
    metadata_paths = sorted(
        [
            *subject_root.rglob("eeg_segments.json"),
            *subject_root.rglob("metadata.json"),
            *subject_root.rglob(".resume_manifest.json"),
            *subject_root.rglob(".trial_log.checkpoint.csv"),
            *subject_root.rglob(".behavioral_ratings.checkpoint.csv"),
            *subject_root.rglob(".behavioral_rating.checkpoint.csv"),
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    expected_images = {trial.trial_idx: trial.asset.image_id for trial in trials}
    visited_dirs: set[Path] = set()
    for metadata_path in metadata_paths:
        session_dir = metadata_path.parent
        if session_dir in visited_dirs:
            continue
        visited_dirs.add(session_dir)
        if metadata_path.suffix.lower() == ".csv":
            metadata = {
                "task_mode": "image_b",
                "image_set_label": image_set_label,
                "session_id": int(session_id),
                "completed": False,
                "image_trials": len(trials),
            }
        else:
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
        if str(metadata.get("task_mode", "")).lower() != "image_b":
            continue
        if normalize_image_set_label(str(metadata.get("image_set_label", "default"))) != image_set_label:
            continue
        if int(metadata.get("session_id", -1)) != int(session_id) or bool(metadata.get("completed", False)):
            continue
        if int(metadata.get("image_trials", len(trials))) != len(trials):
            continue
        rating_source_rows: list[dict[str, Any]] = []
        for rating_path in (
            session_dir / "behavioral_ratings.csv",
            session_dir / ".behavioral_ratings.checkpoint.csv",
            session_dir / ".behavioral_rating.checkpoint.csv",
        ):
            rating_source_rows = _read_csv_rows(rating_path)
            if rating_source_rows:
                break
        trial_rows: list[dict[str, Any]] = []
        for trial_path in (
            session_dir / "trial_log.csv",
            session_dir / ".trial_log.checkpoint.csv",
        ):
            trial_rows = _read_csv_rows(trial_path)
            if trial_rows:
                break
        if not trial_rows and int(session_id) == 1:
            # Older rating-only builds sometimes saved only the behavioral checkpoint.
            trial_rows = [dict(row) for row in rating_source_rows]
        by_index: dict[int, dict[str, Any]] = {}
        compatible = True
        for row in trial_rows:
            try:
                trial_idx = int(row.get("trial_idx", 0))
            except (TypeError, ValueError):
                compatible = False
                break
            if trial_idx not in expected_images or str(row.get("image_id", "")) != expected_images[trial_idx]:
                compatible = False
                break
            by_index[trial_idx] = row
        if not compatible:
            continue
        completed_trial = 0
        while completed_trial + 1 in by_index:
            completed_trial += 1
        if completed_trial >= len(trials):
            continue
        completed_rows = [by_index[idx] for idx in range(1, completed_trial + 1)]
        default_eeg_file = (
            None
            if int(session_id) == 1
            or str(metadata.get("eeg_recording_mode", "")) in {"none", "bcigo_external_edf"}
            else "continuous_eeg.npy"
        )
        for row in completed_rows:
            if not row.get("eeg_part"):
                row["eeg_part"] = 1
            if not row.get("eeg_file") and default_eeg_file:
                row["eeg_file"] = default_eeg_file
        completed_ids = {str(idx) for idx in range(1, completed_trial + 1)}
        rating_rows = [row for row in rating_source_rows if str(row.get("trial_idx")) in completed_ids]
        for row in rating_rows:
            if not row.get("eeg_part"):
                row["eeg_part"] = 1
            if not row.get("eeg_file") and default_eeg_file:
                row["eeg_file"] = default_eeg_file
        return {
            "source_dir": session_dir,
            "completed_trial": completed_trial,
            "next_trial": completed_trial + 1,
            "trial_rows": completed_rows,
            "rating_rows": rating_rows,
            "timestamp_label": metadata.get("timestamp_label") or session_dir.parent.name,
        }
    return None


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size <= 0:
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows: list[dict[str, Any]] = []
            for raw_row in csv.DictReader(handle):
                row: dict[str, Any] = {
                    key: (None if value == "" else value)
                    for key, value in raw_row.items()
                }
                try:
                    row["trial_idx"] = int(row["trial_idx"])
                except (KeyError, TypeError, ValueError):
                    pass
                try:
                    row["eeg_part"] = int(row["eeg_part"])
                except (KeyError, TypeError, ValueError):
                    pass
                rows.append(row)
            return rows
    except (OSError, csv.Error):
        return []


def write_subject_completion_status(
    records_dir: Path,
    *,
    subject_id: str,
    image_set_label: str,
    image_ids: list[str],
) -> Path:
    """Summarize one behavioral rating and five valid EEG views per image."""

    subject_root = records_dir / subject_id
    status = {
        image_id: {"rating_completed": False, "eeg_sessions": []}
        for image_id in image_ids
    }
    for metadata_path in subject_root.rglob("metadata*.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not bool(metadata.get("completed", False)):
            continue
        if normalize_image_set_label(str(metadata.get("image_set_label", "default"))) != image_set_label:
            continue
        session_id = int(metadata.get("session_id", -1))
        session_dir = metadata_path.parent
        if session_id == 1 and str(metadata.get("session_type", "")) == "labeling":
            for row in _read_csv_rows(session_dir / "behavioral_ratings.csv"):
                image_id = str(row.get("image_id", ""))
                if image_id in status and all(row.get(str(item["key"])) is not None for item in RATING_DIMENSIONS):
                    status[image_id]["rating_completed"] = True
        elif session_id in {2, 3, 4, 5, 6}:
            for row in _read_csv_rows(session_dir / "trial_log.csv"):
                image_id = str(row.get("image_id", ""))
                marker_success = str(row.get("image_marker_send_success", "")).strip().lower()
                if image_id in status and row.get("image_onset") is not None and marker_success in {"true", "1"}:
                    sessions = status[image_id]["eeg_sessions"]
                    if session_id not in sessions:
                        sessions.append(session_id)
    for value in status.values():
        value["eeg_sessions"].sort()
        value["eeg_view_count"] = len(value["eeg_sessions"])
        value["complete"] = bool(value["rating_completed"] and value["eeg_sessions"] == [2, 3, 4, 5, 6])
    payload = {
        "subject_id": subject_id,
        "image_set_label": image_set_label,
        "required_rating_count_per_image": 1,
        "required_eeg_sessions": [2, 3, 4, 5, 6],
        "image_count": len(status),
        "images_with_rating": sum(bool(value["rating_completed"]) for value in status.values()),
        "images_with_five_eeg_views": sum(value["eeg_sessions"] == [2, 3, 4, 5, 6] for value in status.values()),
        "fully_complete_images": sum(bool(value["complete"]) for value in status.values()),
        "images": status,
    }
    output = subject_root / f"subject_completion_status_{image_set_label}.json"
    temp = output.with_name(f".{output.name}.{int(time.time() * 1_000_000)}.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    return output


def normalize_timestamp_label(value: str | None, *, now: datetime | None = None) -> str:
    text = str(value or "").strip()
    current = now or datetime.now()
    if not text:
        text = next_timestamp_label(now=current)
    elif re.fullmatch(r"[A-Za-z0-9_-]+", text) and "_" not in text[:9]:
        text = f"{current:%Y%m%d}_{text}"
    if not TIMESTAMP_LABEL_PATTERN.fullmatch(text):
        raise ValueError("时间批次标签必须符合 yyyymmdd_xxxx 格式，只能包含字母、数字、下划线或连字符。")
    return text


def next_timestamp_label(*, now: datetime | None = None) -> str:
    current = now or datetime.now()
    return f"{current:%Y%m%d}_{current:%H%M%S}"


def normalize_image_set_label(value: str | None) -> str:
    label = str(value or "default").strip() or "default"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", label):
        raise ValueError("图片集标签只能包含字母、数字、下划线或连字符。")
    return label


def find_last_image_set_label(records_dir: Path, subject_id: str) -> str | None:
    subject_root = records_dir / str(subject_id)
    if not subject_root.exists():
        return None
    candidates = [
        *subject_root.rglob("eeg_segments.json"),
        *subject_root.rglob("metadata.json"),
        *subject_root.rglob(".resume_manifest.json"),
    ]
    for path in sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return normalize_image_set_label(str(payload.get("image_set_label", "default")))
        except (OSError, ValueError, TypeError):
            continue
    return None


def unique_timestamp_label(
    records_dir: Path,
    *,
    subject_id: str,
    session_id: int,
    image_set_label: str = "default",
    preferred: str | None = None,
) -> str:
    """Create a valid session label without ever reusing an existing save directory."""

    label = normalize_image_set_label(image_set_label)
    base = normalize_timestamp_label(preferred) if preferred else f"{next_timestamp_label()}_{label}"
    candidate = base
    suffix = 2
    while (records_dir / subject_id / candidate / f"session_{int(session_id):02d}").exists():
        candidate = f"{base}_{suffix:02d}"
        suffix += 1
    return candidate


def _apply_cli_eeg_overrides(config: dict[str, Any], args: argparse.Namespace) -> None:
    device_cfg = dict(config.get("device", {}))
    if getattr(args, "device_type", ""):
        config["device_type"] = str(args.device_type).strip().lower()
    if bool(getattr(args, "dummy_eeg", False)) and bool(getattr(args, "real_eeg", False)):
        raise RuntimeError("--dummy-eeg 和 --real-eeg 不能同时使用。")
    if bool(getattr(args, "dummy_eeg", False)):
        config["hardware_dummy_mode"] = True
    if bool(getattr(args, "real_eeg", False)):
        config["hardware_dummy_mode"] = False
    if str(getattr(args, "brainco_addr", "")).strip():
        device_cfg["brainco_addr"] = str(args.brainco_addr).strip()
        device_cfg["brainco_auto_discover"] = False
    if int(getattr(args, "brainco_port", 0) or 0) > 0:
        device_cfg["brainco_port"] = int(args.brainco_port)
        device_cfg["brainco_auto_discover"] = False
    if float(getattr(args, "brainco_scan_timeout", 0.0) or 0.0) > 0:
        device_cfg["brainco_scan_timeout_sec"] = float(args.brainco_scan_timeout)
    if float(getattr(args, "brainco_ready_timeout", 0.0) or 0.0) > 0:
        device_cfg["brainco_ready_timeout_sec"] = float(args.brainco_ready_timeout)
    if str(getattr(args, "brainco_transport", "")).strip():
        device_cfg["brainco_transport"] = str(args.brainco_transport).strip().lower()
    if str(getattr(args, "brainco_lsl_name", "")).strip():
        device_cfg["brainco_lsl_stream_name"] = str(args.brainco_lsl_name).strip()
    if str(getattr(args, "brainco_lsl_source_id", "")).strip():
        device_cfg["brainco_lsl_source_id"] = str(args.brainco_lsl_source_id).strip()
    if float(getattr(args, "brainco_lsl_timeout", 0.0) or 0.0) > 0:
        device_cfg["brainco_lsl_resolve_timeout_sec"] = float(args.brainco_lsl_timeout)
        device_cfg["bcigo_marker_wait_timeout_sec"] = float(args.brainco_lsl_timeout)
    config["device"] = device_cfg


def _uses_bcigo_external_recording(config: dict[str, Any]) -> bool:
    if bool(config.get("hardware_dummy_mode", False)):
        return False
    return (
        str(config.get("device_type", "brainco")).strip().lower() == "brainco"
        and str(config.get("device", {}).get("brainco_transport", "sdk")).strip().lower()
        == "bcigo"
    )


def _run_eeg_cli_check(config: dict[str, Any], *, wait_for_enter: bool) -> int:
    selected = "dummy" if bool(config.get("hardware_dummy_mode", False)) else str(config.get("device_type", "brainco"))
    device_cfg = dict(config.get("device", {}))
    print("=" * 60)
    print("脑电连接命令行预检查")
    print(f"Python：{sys.executable}")
    print(f"设备类型：{selected}")
    print(f"采样率：{float(config.get('sfreq', 250.0))} Hz")
    if selected == "brainco":
        transport = str(device_cfg.get("brainco_transport", "sdk")).strip().lower()
        print(f"BrainCo 传输方式：{transport}")
        if transport in {"bcigo", "lsl"}:
            if transport == "bcigo":
                print("BCIGo 模式：BCIGo 直接录制 EEG/EDF，本程序只发送 LSL Marker。")
            else:
                print(f"EEG LSL streamName：{device_cfg.get('brainco_lsl_stream_name') or '<按 EEG 类型自动匹配>'}")
                print(f"BCIGo LSL streamType：{device_cfg.get('brainco_lsl_stream_type', 'EEG')}")
                print(f"BCIGo LSL sourceId：{device_cfg.get('brainco_lsl_source_id') or '<未限定>'}")
            print(f"实验 Marker streamName：{device_cfg.get('lsl_marker_stream_name', 'visual-video-task-Markers')}")
            print(f"实验 Marker sourceId：{device_cfg.get('lsl_marker_source_id', 'visual-video-task-marker')}")
        else:
            print(f"BrainCo 自动发现：{bool(device_cfg.get('brainco_auto_discover', True))}")
            print(f"BrainCo 手动地址：{device_cfg.get('brainco_addr') or '<未设置>'}")
            print(f"BrainCo 手动端口：{device_cfg.get('brainco_port') or '<未设置>'}")
            print(f"BrainCo 扫描超时：{float(device_cfg.get('brainco_scan_timeout_sec', 6.0))} 秒")
            print(f"BrainCo 就绪超时：{float(device_cfg.get('brainco_ready_timeout_sec', 20.0))} 秒")
    elif selected == "neuracle":
        print(f"Neuracle 地址：{device_cfg.get('neuracle_host', '127.0.0.1')}")
        print(f"Neuracle 端口：{device_cfg.get('neuracle_port', 8712)}")
    marker_backend: Any | None = None
    if (
        selected == "brainco"
        and str(device_cfg.get("brainco_transport", "sdk")).strip().lower()
        in {"bcigo", "lsl"}
        and bool(device_cfg.get("lsl_marker_enabled", True))
    ):
        # Keep this reference alive for the whole preflight. BCIGo can scan and
        # select the experiment Marker stream while we wait for its EEG stream.
        marker_backend = build_marker_backend(config)
        print("实验 Marker LSL 流已发布；现在可在 BCIGo 中点击“扫描”。")
    if _uses_bcigo_external_recording(config):
        print("正在等待 BCIGo 扫描并连接 Marker 流...")
    else:
        print("正在启动数据流并读取 1 秒脑电数据...")
    try:
        info = (
            _probe_bcigo_marker_connection(config, marker_backend=marker_backend)
            if _uses_bcigo_external_recording(config)
            else _probe_eeg_connection(config)
        )
    except Exception as exc:
        print("\n脑电连接检查失败：")
        print(_format_eeg_error(exc, config))
        print("=" * 60)
        return 1

    print("\n脑电连接检查通过：")
    print(f"设备：{info.get('device')}")
    print(f"通道数：{info.get('channels')}")
    print(f"采样率：{info.get('sfreq')} Hz")
    if info.get("recording_mode") == "bcigo_external_edf":
        print("EEG 录制：BCIGo 外部 EDF")
        print(f"Marker 流：{info.get('marker_stream')}")
        print("本程序不再等待不存在的 EEG LSL Outlet。")
    else:
        print(f"样本数：{info.get('samples')}")
        if info.get("stream_identity"):
            print(f"LSL 流：{info['stream_identity']}")
        print(f"均值/标准差：{info.get('mean'):.3f} / {info.get('std'):.3f}")
    print("=" * 60)
    if wait_for_enter:
        input(
            "确认 BCIGo 正在录制（可沿用上一 session 的连续录制）。"
            "按 Enter 启动 PsychoPy 实验窗口，或按 Ctrl+C 取消。"
        )
    # Deliberately keep the marker outlet alive until after the optional prompt.
    _ = marker_backend
    return 0


def _probe_bcigo_marker_connection(
    config: dict[str, Any],
    *,
    marker_backend: Any | None = None,
) -> dict[str, Any]:
    device_cfg = dict(config.get("device", {}))
    backend = marker_backend or build_marker_backend(config)
    if not hasattr(backend, "wait_for_consumers"):
        raise RuntimeError("BCIGo 模式需要启用 LSL Marker。")
    timeout_sec = float(device_cfg.get("bcigo_marker_wait_timeout_sec", 60.0))
    if not backend.wait_for_consumers(timeout_sec):
        raise RuntimeError(
            "BCIGo 未连接实验 Marker 流。请在 BCIGo 的第三方软件页面点击扫描，"
            "选择 visual-video-task-Markers。"
        )
    marker_stream = {
        "name": str(device_cfg.get("lsl_marker_stream_name", "visual-video-task-Markers")),
        "type": str(device_cfg.get("lsl_marker_stream_type", "Markers")),
        "source_id": str(device_cfg.get("lsl_marker_source_id", "visual-video-task-marker")),
    }
    return {
        "device": "brainco_bcigo",
        "channels": 32,
        "sfreq": float(config.get("sfreq", 250.0)),
        "samples": None,
        "recording_mode": "bcigo_external_edf",
        "marker_stream": marker_stream,
    }


def _probe_eeg_connection(config: dict[str, Any], *, window_sec: float = 1.0, timeout_sec: float = 8.0) -> dict[str, Any]:
    acquirer: Any | None = None
    try:
        acquirer = build_acquirer(device_name=str(config.get("device_type", "brainco")), config=config)
        acquirer.start_stream()
        eeg = _wait_for_probe_chunk(acquirer, window_sec=window_sec, timeout_sec=timeout_sec)
        mean = float(np.mean(eeg))
        std = float(np.std(eeg))
        if not np.isfinite(mean) or not np.isfinite(std) or std <= 0:
            raise RuntimeError(f"脑电数据统计异常：均值={mean:.3f}，标准差={std:.3f}")
        return {
            "device": acquirer.metadata.name,
            "channels": int(acquirer.metadata.n_channels),
            "sfreq": float(acquirer.metadata.sfreq),
            "samples": int(eeg.shape[1]),
            "stream_identity": getattr(acquirer, "stream_identity", None),
            "mean": mean,
            "std": std,
        }
    finally:
        if acquirer is not None:
            try:
                acquirer.stop_stream()
            except Exception:
                pass


def _wait_for_probe_chunk(acquirer: Any, *, window_sec: float, timeout_sec: float) -> np.ndarray:
    deadline = time.monotonic() + timeout_sec
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            eeg, _timestamps = acquirer.get_chunk(window_sec)
            if eeg.ndim != 2:
                raise RuntimeError(f"脑电数据形状异常：{eeg.shape}")
            required = max(1, int(float(acquirer.metadata.sfreq) * window_sec * 0.8))
            if eeg.shape[0] != int(acquirer.metadata.n_channels) or eeg.shape[1] < required:
                raise RuntimeError(f"脑电数据形状异常：{eeg.shape}")
            return np.asarray(eeg, dtype=np.float32)
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"等待有效脑电数据超时：{last_error}")


def _session_type_label(session_type: str) -> str:
    if session_type == "labeling":
        return "图片标注"
    if session_type == "denoise":
        return "去噪采集"
    return str(session_type)


def _format_eeg_error(exc: Exception, config: dict[str, Any]) -> str:
    message = str(exc)
    device = str(config.get("device_type", "brainco")).strip().lower()
    device_cfg = dict(config.get("device", {}))
    brainco_transport = str(device_cfg.get("brainco_transport", "sdk")).strip().lower()
    if isinstance(exc, ModuleNotFoundError) and getattr(exc, "name", "") == "pylsl":
        return (
            "当前 PsychoPy 环境缺少 BCIGo LSL 依赖：pylsl。\n\n"
            "请运行：python -m pip install pylsl"
        )
    if device == "brainco" and brainco_transport == "bcigo":
        return (
            f"BCIGo 尚未连接实验 Marker 流：{message}\n\n"
            "处理方式：\n"
            "1. 保持本命令运行；它正在发布 visual-video-task-Markers。\n"
            "2. 在 BCIGo 的“第三方软件”页面点击扫描并选择该 Marker 流。\n"
            "3. BCIGo 显示已连接后开始录制；程序会自动继续。\n"
            "说明：BCIGo 直接录制 EEG/EDF，本程序不再等待 EEG LSL 流。"
        )
    if device == "brainco" and brainco_transport == "lsl" and (
        "lsl" in message.lower() or "stream" in message.lower()
    ):
        return (
            f"未能连接 BCIGo LSL 实时 EEG：{message}\n\n"
            "处理方式：\n"
            "1. 在 BCIGo 中连接脑电帽并开启“LSL 实时数据流”。\n"
            "2. 确认 BCIGo 已开始实时转发 EEG，而不只是停留在设置页面。\n"
            "3. 运行 --preflight-eeg --brainco-lsl-timeout 60；命令显示 Marker 已发布后，"
            "在 BCIGo 中点击扫描并选择 visual-video-task-Markers。\n"
            "4. 如果检测到多个 EEG 流，请用 "
            "--brainco-lsl-name 和 --brainco-lsl-source-id 精确指定。\n"
            "5. BCIGo 开始录制后，在命令行按 Enter 进入实验。"
        )
    if isinstance(exc, ModuleNotFoundError) and getattr(exc, "name", "") == "bc_ecap_sdk":
        return (
            "当前 PsychoPy 运行环境缺少 BrainCo SDK：bc_ecap_sdk。\n\n"
            "处理方式：\n"
            "1. 在 PsychoPy 使用的 Python 环境中安装 BrainCo SDK（项目可选依赖名：bc-ecap-sdk）。\n"
            "2. 或在启动对话框中勾选“使用模拟脑电”，先测试实验流程。\n"
            "3. 若本次使用博睿康，请把脑电设备改为 neuracle。"
        )
    if "bc_ecap_sdk" in message:
        return (
            "BrainCo SDK 加载失败：bc_ecap_sdk 不可用。\n\n"
            "请确认是在已安装 BrainCo SDK 的 PsychoPy 环境中运行。"
        )
    if device == "brainco" and brainco_transport == "sdk" and ("timed out" in message.lower() or "timeout" in message.lower()):
        return (
            f"BrainCo SDK 已加载，但设备连接或数据流启动超时：{message}\n\n"
            "处理方式：\n"
            "1. 确认脑电帽已开机，并且电脑与脑电帽处在同一网络/连接方式下。\n"
            "2. 如果自动发现不稳定，请在 config.yaml 中填写 device.brainco_addr 和 device.brainco_port。\n"
            "3. 可临时把 device.brainco_scan_timeout_sec 调大到 15，把 device.brainco_ready_timeout_sec 调大到 30。\n"
            "4. 重新运行：python psychopy_image_b_experiment.py --eeg-check-only --real-eeg --device-type brainco。"
        )
    if device == "brainco" and brainco_transport == "sdk" and ("found no devices" in message.lower() or "auto-discovery" in message.lower()):
        port_hint = ""
        found_addr = re.search(r"device address '([^']+)' but no port", message)
        if found_addr:
            port_hint = (
                f"\n\n本次自动发现已找到设备地址：{found_addr.group(1)}，但没有返回端口。\n"
                "请向 BrainCo SDK/设备文档确认 TCP 端口，然后测试：\n"
                f"python psychopy_image_b_experiment.py --eeg-check-only --real-eeg --device-type brainco --brainco-addr {found_addr.group(1)} --brainco-port 端口号"
            )
        return (
            f"BrainCo 自动发现未找到有效设备：{message}\n\n"
            "请确认脑电帽已开机、网络可达；如果知道设备 IP/端口，请写入 config.yaml 的 "
            "device.brainco_addr 和 device.brainco_port。"
            f"{port_hint}"
        )
    if device == "neuracle" and ("connection" in message.lower() or "refused" in message.lower() or "timed out" in message.lower()):
        return (
            f"博睿康/Neuracle 数据转发连接失败：{message}\n\n"
            "请确认 JellyFish/数据转发已启动，IP 和端口与 config.yaml 中 device.neuracle_host / neuracle_port 一致。"
        )
    return message


def _doctor() -> int:
    checks: list[tuple[str, bool, str]] = []
    for module_name in ["psychopy", "numpy", "yaml", "pylsl", "bcigo_sdk", "bc_ecap_sdk"]:
        try:
            __import__(module_name)
            checks.append((module_name, True, "OK"))
        except Exception as exc:
            checks.append((module_name, False, str(exc)))
    for name, ok, detail in checks:
        status = "正常" if ok else "缺失"
        print(f"{name}: {status} ({detail})")
    return 0 if all(ok for _, ok, _ in checks[:2]) else 1


def _load_psychopy() -> None:
    global core, event, gui, visual, Keyboard
    try:
        from psychopy import core as psychopy_core
        from psychopy import event as psychopy_event
        from psychopy import gui as psychopy_gui
        from psychopy import visual as psychopy_visual
        from psychopy.hardware.keyboard import Keyboard as PsychoPyKeyboard
    except Exception as exc:
        raise RuntimeError(
            "当前 Python 环境未安装 PsychoPy。"
            "请使用 PsychoPy Standalone 打开本脚本，或安装项目的 PsychoPy 可选依赖。"
        ) from exc
    core = psychopy_core
    event = psychopy_event
    gui = psychopy_gui
    visual = psychopy_visual
    Keyboard = PsychoPyKeyboard


def _load_simple_yaml(path: Path) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    with path.open("r", encoding="utf-8-sig") as handle:
        for raw in handle:
            line = raw.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            key, sep, value = line.strip().partition(":")
            if not sep:
                continue
            while stack and indent <= stack[-1][0]:
                stack.pop()
            parent = stack[-1][1]
            if value.strip() == "":
                child: dict[str, Any] = {}
                parent[key.strip()] = child
                stack.append((indent, child))
            else:
                parent[key.strip()] = _parse_scalar(value.strip())
    return root


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if text in {"''", '""'}:
        return ""
    if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
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


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
