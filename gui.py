"""Streamlit web interface for Video-EEG Experiment."""

from __future__ import annotations

import argparse
from html import escape
import importlib
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import experiment_ui
from acquisition.factory import AcquirerFactory, register_default_acquirers
from cli import (
    build_acquirer,
    build_marker_backend,
    load_config as load_app_config,
    resolve_config_path,
    write_config,
)
from protocol.video_protocol import VideoProtocolConfig, build_experiment_playlists_from_config
from tasks.task_factory import load_task_from_config
from utils.markers import TRIGGER_REFERENCE
from utils.session_store import load as load_session_store
from utils.session_store import reset_for_popup
from utils.video_library import category_counts, load_video_library, serialize_playlist

_GUI_ROOT = Path(__file__).resolve().parent
_PAGE_ICON = "🎬"

st.set_page_config(page_title="视频神经反应实验台", page_icon=_PAGE_ICON, layout="wide")

SIDEBAR_NAV_PAGES = ("首页", "实验设置", "连通检测", "Trigger 说明", "数据导出")

TABLE_STYLES = [
    {"selector": "", "props": [("background-color", "#ffffff"), ("color", "#0f172a")]},
    {"selector": "th", "props": [("background-color", "#f1f5f9"), ("color", "#0f172a"), ("font-weight", "700")]},
    {"selector": "td", "props": [("background-color", "#ffffff"), ("color", "#0f172a")]},
]


def parse_config_path(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", dest="config_path", type=Path, default=None)
    args, _ = parser.parse_known_args(argv)
    return resolve_config_path(args.config_path)


CONFIG_PATH = parse_config_path(sys.argv[1:])


def load_config() -> dict:
    try:
        return load_app_config(CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001
        st.error(f"加载配置文件失败: {exc}")
        return {}


def save_config(cfg: dict) -> None:
    try:
        write_config(CONFIG_PATH, cfg)
    except Exception as exc:  # noqa: BLE001
        st.error(f"保存配置文件失败: {exc}")


def _is_experiment_popup() -> bool:
    return st.query_params.get("mode", "") == "experiment"


def _set_gui_nav_mode(page: str) -> None:
    st.session_state.gui_nav_mode = page


def init_session_state(config: dict) -> None:
    defaults = {
        "gui_nav_mode": "首页",
        "playlist": [],
        "practice_asset": None,
        "practice_completed": False,
        "playlist_seed": None,
        "playlist_metadata": {},
        "results": [],
        "experiment_state": "instructions",
        "eeg_manager": None,
        "phase_log": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "runtime_config" not in st.session_state:
        st.session_state.runtime_config = dict(config)



def _library_summary(config: dict) -> tuple[Path, int, str]:
    library = load_video_library(config)
    catalog = library.list_assets()
    return library.root, len(catalog), library.mode


def _append_phase_log(message: str) -> None:
    from datetime import datetime

    st.session_state.phase_log.append(f"{datetime.now().strftime('%H:%M:%S')} {message}")
    if len(st.session_state.phase_log) > 40:
        st.session_state.phase_log.pop(0)


def _get_eeg_manager(config: dict):
    return st.session_state.get("eeg_manager")


def _start_eeg_session(config: dict):
    from protocol.video_protocol import EegSessionManager

    existing = _get_eeg_manager(config)
    if existing is not None and existing.running:
        return existing

    subject_id = str(config.get("subject_id", "S001"))
    session_id = int(config.get("session_id", 1))
    acquirer = build_acquirer(device_name=str(config.get("device_type", "brainco")), config=config)
    task = load_task_from_config(config)

    def _on_phase(event_name: str, payload: dict) -> None:
        detail = ", ".join(f"{k}={v}" for k, v in payload.items())
        _append_phase_log(f"trigger {event_name}" + (f" ({detail})" if detail else ""))

    task.set_phase_callback(_on_phase)
    marker_backend = task.wrap_marker_backend(build_marker_backend(config))
    records_dir = Path(str(config.get("storage", {}).get("records_dir", "records_storage")))

    manager = EegSessionManager(
        acquirer,
        marker_backend,
        sfreq=float(config.get("sfreq", 250)),
        records_dir=records_dir,
        subject_id=subject_id,
        session_id=session_id,
    )
    session_dir = manager.start(
        metadata={
            "task_mode": str(config.get("task_mode", "visual")),
            "playlist_size": len(st.session_state.get("playlist", [])),
            "practice_asset": st.session_state.get("practice_asset"),
            "playlist_seed": st.session_state.get("playlist_seed"),
            "playlist_metadata": st.session_state.get("playlist_metadata", {}),
        }
    )
    st.session_state.eeg_manager = manager
    st.session_state.eeg_session_dir = str(session_dir)
    _append_phase_log(f"EEG session started → {session_dir}")
    return manager


def _stop_eeg_session(config: dict, *, extra_metadata: dict | None = None) -> Path | None:
    manager = _get_eeg_manager(config)
    if manager is None or not manager.running:
        return None
    session_dir = manager.stop_and_export(metadata=extra_metadata or {})
    st.session_state.eeg_manager = None
    if session_dir is not None:
        st.session_state.eeg_session_dir = str(session_dir)
        _append_phase_log(f"EEG session exported → {session_dir}")
    return session_dir


def _open_experiment_popup() -> None:
    components.html(
        """
        <script>
        (function () {
          const base = window.parent.location.href.split("?")[0];
          const token = Date.now();
          const url = base + "?mode=experiment&run=" + token;
          const features = [
            "popup=yes",
            "width=1280",
            "height=900",
            "menubar=no",
            "toolbar=no",
            "location=no",
            "status=no",
            "scrollbars=yes",
            "resizable=yes"
          ].join(",");
          const win = window.open(url, "VideoEEG_" + token, features);
          if (win) win.focus();
        })();
        </script>
        """,
        height=0,
    )


def _listen_popup_closed() -> None:
    components.html(
        """
        <script>
        (function () {
          if (window.__videoEegPopupListener) return;
          window.__videoEegPopupListener = true;
          window.addEventListener("message", function (event) {
            if (event.data && event.data.type === "video_eeg_experiment_closed") {
              window.parent.postMessage({ type: "streamlit:popupClosed" }, "*");
            }
          });
        })();
        </script>
        """,
        height=0,
    )


def _prepare_experiment_run(config: dict):
    run = build_experiment_playlists_from_config(config)
    playlist = serialize_playlist(run.formal_playlist)
    practice_asset = run.practice_asset.to_mapping()
    metadata = {
        "formal_trials": len(run.formal_playlist),
        "practice_asset": practice_asset,
        "category_counts": category_counts(run.formal_playlist),
        "used_placeholder": run.used_placeholder,
        "fallback_reason": run.fallback_reason,
    }
    return run, playlist, practice_asset, metadata


def render_home() -> None:
    st.title("视频神经反应实验台")
    st.markdown(experiment_ui.EXPERIMENT_INSTRUCTIONS_MD)


def render_settings(config: dict) -> None:
    st.title("实验参数配置")
    register_default_acquirers()
    protocol_cfg = config.setdefault("protocol", {})
    device_cfg = config.setdefault("device", {})
    storage_cfg = config.setdefault("storage", {})

    st.markdown("### 被试与会话")
    col1, col2 = st.columns(2)
    config["subject_id"] = col1.text_input("被试 ID (subject_id)", value=str(config.get("subject_id", "S001")))
    config["session_id"] = col2.number_input(
        "Session 编号",
        min_value=1,
        max_value=99,
        value=int(config.get("session_id", 1)),
        step=1,
    )

    st.markdown("### EEG 采集设备")
    devices = AcquirerFactory.list_hardware_devices()
    raw_device = str(config.get("device_type", devices[0] if devices else "brainco"))
    # Legacy configs used device_type=dummy; migrate to a real device + checkbox.
    if raw_device == "dummy" or raw_device not in devices:
        if raw_device == "dummy":
            config["hardware_dummy_mode"] = True
        current_device = devices[0] if devices else "brainco"
    else:
        current_device = raw_device
    config["device_type"] = st.selectbox(
        "采集设备 (device_type)",
        devices,
        index=devices.index(current_device) if current_device in devices else 0,
        help="仅选择真实采集设备。模拟信号请使用下方「硬件模拟模式」。",
    )
    config["hardware_dummy_mode"] = bool(
        st.checkbox(
            "硬件模拟模式",
            value=bool(config.get("hardware_dummy_mode", False)),
            help="勾选后强制使用模拟 EEG，忽略上方设备；取消勾选后 hardware_dummy_mode 为 false，按所选设备真实采集。",
        )
    )
    device_cfg["trigger_serial_port"] = st.text_input(
        "Trigger Box 串口",
        value=str(device_cfg.get("trigger_serial_port", "")),
    )
    config["sfreq"] = float(st.number_input("采样率 (Hz)", min_value=100.0, value=float(config.get("sfreq", 250.0)), step=50.0))
    config["buffer_sec"] = float(st.number_input("缓冲区时长 (秒)", min_value=30.0, value=float(config.get("buffer_sec", 120.0)), step=10.0))

    st.markdown("### 视频材料库")
    library_dir_default = str(
        protocol_cfg.get("video_library_dir")
        or protocol_cfg.get("video_dir")
        or "video_library/selected_540_balanced_videos"
    )
    protocol_cfg["video_library_dir"] = st.text_input(
        "视频库目录 (video_library_dir)",
        value=library_dir_default,
        help="正式刺激视频目录。推荐使用 video_library/selected_540_balanced_videos。",
    )
    mode_options = ("auto", "manifest", "local")
    current_mode = str(protocol_cfg.get("video_library_mode", "local"))
    protocol_cfg["video_library_mode"] = st.selectbox(
        "视频库模式 (video_library_mode)",
        mode_options,
        index=mode_options.index(current_mode) if current_mode in mode_options else mode_options.index("local"),
        help="local=扫描目录中的真实视频文件；正式实验推荐 local。",
    )
    try:
        _library_root, catalog_size, library_mode = _library_summary(config)
        st.caption(f"视频库已就绪 · 模式 {library_mode} · 可用视频 {catalog_size} 个")
    except Exception as exc:  # noqa: BLE001
        st.warning(f"视频库尚未就绪: {exc}")

    st.markdown("### 视频 Trial 时间参数")
    t_col1, t_col2, t_col3, t_col4 = st.columns(4)
    protocol_cfg["fixation_sec"] = float(t_col1.number_input("注视点 (秒)", min_value=0.5, value=float(protocol_cfg.get("fixation_sec", 1.5)), step=0.5))
    protocol_cfg["default_video_sec"] = float(t_col2.number_input("默认视频时长 (秒)", min_value=1.0, value=float(protocol_cfg.get("default_video_sec", 8.0)), step=0.5))
    protocol_cfg["blank_sec"] = float(t_col3.number_input("空屏 (秒)", min_value=0.5, value=float(protocol_cfg.get("blank_sec", 1.0)), step=0.5))
    protocol_cfg["iti_sec"] = float(t_col4.number_input("ITI (秒)", min_value=0.5, value=float(protocol_cfg.get("iti_sec", 2.0)), step=0.5))
    protocol_cfg["rating_sec"] = float(st.number_input("评分阶段时长 (秒)", min_value=3.0, value=float(protocol_cfg.get("rating_sec", 10.0)), step=1.0))
    protocol_cfg["baseline_sec"] = float(st.number_input("静息基线时长 (秒，0=跳过)", min_value=0.0, value=float(protocol_cfg.get("baseline_sec", 60.0)), step=5.0))
    protocol_cfg["trials_per_session"] = int(st.number_input("正式 Trial 数", min_value=1, value=int(protocol_cfg.get("trials_per_session", 500)), step=1))
    st.caption("每次打开实验窗口都会重新随机抽取 1 个练习 trial，并从剩余视频中均衡抽取正式 trial。")
    storage_cfg["records_dir"] = st.text_input("EEG 记录目录", value=str(storage_cfg.get("records_dir", "records_storage")))
    storage_cfg["ratings_dir"] = st.text_input("行为评分目录", value=str(storage_cfg.get("ratings_dir", "ratings_storage")))

    if st.button("保存配置", type="primary"):
        save_config(config)
        st.session_state.runtime_config = dict(config)
        st.success("配置已保存。")

    st.divider()
    st.markdown("### 启动实验")

    if st.button("生成播放列表", type="secondary"):
        try:
            protocol = VideoProtocolConfig.from_config(config)
            run, playlist, practice_asset, metadata = _prepare_experiment_run(config)
            st.session_state.playlist = playlist
            st.session_state.practice_asset = practice_asset
            st.session_state.playlist_seed = run.random_seed
            st.session_state.playlist_metadata = metadata
            st.session_state.results = []
            st.session_state.current_trial = 0
            st.session_state.experiment_state = "instructions"
            st.session_state.practice_completed = False
            st.session_state.baseline_done = protocol.baseline_sec <= 0
            st.session_state.eeg_session_dir = None
            st.session_state.phase_log = []
            experiment_ui.persist_session(config)
            counts_text = "，".join(f"{name}: {count}" for name, count in metadata["category_counts"].items())
            if run.used_placeholder:
                st.warning(
                    f"未检测到完整 540 个视频，已使用 placeholder 黑屏视频生成练习和正式 trial。"
                    f"原因: {run.fallback_reason}"
                )
            else:
                st.success(
                    f"已生成练习 1 个、正式 {len(playlist)} 个 trial。分类: {counts_text}"
                )
        except Exception as exc:  # noqa: BLE001
            st.error(f"生成播放列表失败: {exc}")

    playlist = st.session_state.get("playlist", [])
    playlist_size = len(playlist)

    if playlist_size == 0:
        st.info("打开实验窗口时会自动重新随机生成练习和正式播放列表。")

    _listen_popup_closed()

    if st.button("打开实验窗口", type="primary"):
        try:
            save_config(config)
            st.session_state.runtime_config = dict(config)
            protocol = VideoProtocolConfig.from_config(config)
            run, playlist, practice_asset, metadata = _prepare_experiment_run(config)
            reset_for_popup(
                config,
                playlist,
                practice_asset=practice_asset,
                playlist_seed=run.random_seed,
                playlist_metadata=metadata,
            )
            st.session_state.playlist = playlist
            st.session_state.practice_asset = practice_asset
            st.session_state.playlist_seed = run.random_seed
            st.session_state.playlist_metadata = metadata
            st.session_state.current_trial = 0
            st.session_state.results = []
            st.session_state.experiment_state = "instructions"
            st.session_state.practice_completed = False
            st.session_state.baseline_done = protocol.baseline_sec <= 0
            st.session_state.eeg_manager = None
            st.session_state.eeg_session_dir = None
            _open_experiment_popup()
            if run.used_placeholder:
                st.toast("实验窗口已打开：未检测到完整 540 个视频，本次将使用 placeholder 黑屏视频。")
            else:
                st.toast("实验窗口已打开，本次练习与正式 trial 顺序已重新随机生成。")
        except Exception as exc:  # noqa: BLE001
            st.error(f"打开实验窗口失败: {exc}")

    if st.button("刷新进度"):
        stored = load_session_store(config)
        if stored.get("results"):
            st.session_state.results = stored["results"]
        st.rerun()


def render_probe(config: dict) -> None:
    import time

    st.title("连通检测")
    duration = st.number_input("探测时长 (秒)", min_value=0.1, value=3.0, step=0.5)
    selected_device = str(config.get("device_type", "brainco"))
    if bool(config.get("hardware_dummy_mode", False)):
        st.caption("当前已开启硬件模拟模式：探测将使用模拟信号，而非上方所选真实设备。")
    if st.button("开始探测", type="primary"):
        probe_label = "dummy (模拟)" if bool(config.get("hardware_dummy_mode", False)) else selected_device
        with st.spinner(f"正在连接 {probe_label} ..."):
            try:
                acquirer = build_acquirer(device_name=selected_device, config=config)
                acquirer.start_stream()
                time.sleep(max(duration, 0.1))
                window, _ = acquirer.get_chunk(2.0)
                acquirer.stop_stream()
                st.success("设备连通正常。")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Shape", str(window.shape))
                c2.metric("Mean (uV)", f"{window.mean():.3f}")
                c3.metric("Std (uV)", f"{window.std():.3f}")
                c4.metric("Max Abs (uV)", f"{abs(window).max():.3f}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"连通失败: {exc}")


def render_trigger_reference() -> None:
    st.title("Trigger 事件码设计")
    rows = [{"事件码": code, "说明": desc} for code, desc in TRIGGER_REFERENCE.items()]
    body = "\n".join(
        (
            "<tr>"
            f"<td>{escape(str(row['事件码']))}</td>"
            f"<td>{escape(str(row['说明']))}</td>"
            "</tr>"
        )
        for row in rows
    )
    st.markdown(
        f"""
        <table class="trigger-table">
          <thead><tr><th>事件码</th><th>说明</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )


def render_data_export(config: dict) -> None:
    st.title("数据导出")
    stored = load_session_store(config)
    results = stored.get("results") or st.session_state.get("results", [])
    if not results:
        st.info("暂无行为评分数据。")
    else:
        df = pd.DataFrame(results)
        st.dataframe(df.style.set_table_styles(TABLE_STYLES), use_container_width=True)
        st.download_button(
            "下载行为评分 CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name=f"ratings_{config.get('subject_id')}_session_{config.get('session_id')}.csv",
            mime="text/csv",
            type="primary",
        )

    session_dir = stored.get("eeg_session_dir") or st.session_state.get("eeg_session_dir")
    if session_dir and Path(session_dir).exists():
        st.markdown("### EEG Session 文件")
        for file in sorted(Path(session_dir).iterdir()):
            st.write(f"- `{file.name}`")
        events_path = Path(session_dir) / "events.json"
        if events_path.exists():
            with events_path.open("r", encoding="utf-8") as handle:
                events = json.load(handle)
            st.dataframe(pd.DataFrame(events[:20]).style.set_table_styles(TABLE_STYLES), use_container_width=True)


def _inject_gui_nav_styles() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        #MainMenu,
        footer {
          display: none !important;
          visibility: hidden !important;
          height: 0 !important;
        }

        .stApp {
          background: #ffffff;
          color: #0f172a;
        }

        .stApp h1,
        .stApp h2,
        .stApp h3,
        .stApp h4,
        .stApp h5,
        .stApp h6,
        .stApp p,
        .stApp label,
        .stApp span {
          color: #0f172a;
        }

        section[data-testid="stSidebar"] {
          background: #f8fafc;
          border-right: 1px solid rgba(15, 23, 42, 0.08);
        }

        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] label {
          color: #0f172a !important;
        }

        div[data-testid="stButton"] > button,
        div[data-testid="stDownloadButton"] > button {
          border-radius: 8px !important;
          border: 1px solid #cbd5e1 !important;
          background: #f8fafc !important;
          color: #0f172a !important;
          box-shadow: none !important;
        }

        div[data-testid="stButton"] > button *,
        div[data-testid="stDownloadButton"] > button * {
          color: inherit !important;
          -webkit-text-fill-color: currentColor !important;
        }

        div[data-testid="stButton"] > button:hover,
        div[data-testid="stButton"] > button:focus,
        div[data-testid="stButton"] > button:active,
        div[data-testid="stDownloadButton"] > button:hover,
        div[data-testid="stDownloadButton"] > button:focus,
        div[data-testid="stDownloadButton"] > button:active {
          border-color: #0f766e !important;
          background: #ecfdf5 !important;
          color: #0f172a !important;
          box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.12) !important;
        }

        div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stDownloadButton"] > button[kind="primary"] {
          border-color: #0f766e !important;
          background: #0f766e !important;
          color: #ffffff !important;
        }

        div[data-testid="stButton"] > button[kind="primary"]:hover,
        div[data-testid="stButton"] > button[kind="primary"]:focus,
        div[data-testid="stButton"] > button[kind="primary"]:active,
        div[data-testid="stDownloadButton"] > button[kind="primary"]:hover,
        div[data-testid="stDownloadButton"] > button[kind="primary"]:focus,
        div[data-testid="stDownloadButton"] > button[kind="primary"]:active {
          border-color: #115e59 !important;
          background: #115e59 !important;
          color: #ffffff !important;
          box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.2) !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
          width: 100% !important;
          border-radius: 8px !important;
          border: 1px solid #1f2937 !important;
          background: #1f2937 !important;
          color: #ffffff !important;
          box-shadow: none !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button * {
          color: #ffffff !important;
          -webkit-text-fill-color: #ffffff !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover,
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:focus,
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:active {
          border-color: #334155 !important;
          background: #334155 !important;
          color: #ffffff !important;
          box-shadow: none !important;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"],
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:hover,
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:focus,
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"]:active {
          border-color: #0f766e !important;
          background: #0f766e !important;
          color: #ffffff !important;
        }

        .trigger-table {
          width: 100%;
          border-collapse: collapse;
          background: #ffffff;
          color: #0f172a;
          border: 1px solid #e2e8f0;
          border-radius: 8px;
          overflow: hidden;
        }

        .trigger-table th,
        .trigger-table td {
          padding: 0.7rem 0.9rem;
          border-bottom: 1px solid #e2e8f0;
          color: #0f172a;
          text-align: left;
        }

        .trigger-table th {
          background: #f1f5f9;
          font-weight: 700;
        }

        .trigger-table tr:nth-child(even) td {
          background: #f8fafc;
        }

        .trigger-table tr:last-child td {
          border-bottom: 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def run_experiment_popup_mode(config: dict) -> None:
    popup_ui = importlib.reload(experiment_ui)
    popup_ui.render_experiment_popup(
        config,
        get_eeg_manager=_get_eeg_manager,
        start_eeg_session=_start_eeg_session,
        stop_eeg_session=_stop_eeg_session,
    )


def main() -> None:
    config = load_config()
    if not config:
        return

    if _is_experiment_popup():
        run_experiment_popup_mode(config)
        return

    init_session_state(config)
    st.session_state.runtime_config = dict(config)
    _inject_gui_nav_styles()

    with st.sidebar:
        st.title("🎬 实验控制台")
        st.divider()
        for page in SIDEBAR_NAV_PAGES:
            is_active = st.session_state.gui_nav_mode == page
            st.button(
                page,
                key=f"nav_btn_{page}",
                type="primary" if is_active else "secondary",
                on_click=_set_gui_nav_mode,
                args=(page,),
            )

    runtime_config = st.session_state.runtime_config
    mode = st.session_state.gui_nav_mode
    if mode == "首页":
        render_home()
    elif mode == "实验设置":
        render_settings(runtime_config)
    elif mode == "连通检测":
        render_probe(runtime_config)
    elif mode == "Trigger 说明":
        render_trigger_reference()
    elif mode == "数据导出":
        render_data_export(runtime_config)


if __name__ == "__main__":
    main()
