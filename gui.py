"""Streamlit web interface for Video-EEG Experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from acquisition.factory import AcquirerFactory, register_default_acquirers
from cli import (
    build_acquirer,
    build_marker_backend,
    load_config as load_app_config,
    resolve_config_path,
    write_config,
)
from experiment_ui import persist_session, render_experiment_popup
from protocol.video_protocol import VideoProtocolConfig, build_playlist_from_config
from tasks.task_factory import load_task_from_config
from utils.markers import TRIGGER_REFERENCE
from utils.session_store import load as load_session_store
from utils.session_store import reset_for_popup
from utils.video_library import load_video_library, serialize_playlist

_GUI_ROOT = Path(__file__).resolve().parent
_PAGE_ICON = "🎬"

st.set_page_config(page_title="视频神经反应实验台", page_icon=_PAGE_ICON, layout="wide")

SIDEBAR_NAV_PAGES = ("首页", "实验设置", "连通检测", "Trigger 说明", "数据导出")


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
        "gui_nav_mode": "实验设置",
        "playlist": [],
        "results": [],
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
    acquirer = build_acquirer(device_name=str(config.get("device_type", "dummy")), config=config)
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


def render_home() -> None:
    st.title("视频神经反应实验台")
    st.markdown(
        """
        ### 欢迎参与本次实验

        1. 在 **实验设置** 中配置参数并生成播放列表
        2. 点击 **打开实验窗口** — 实验在独立弹出窗口中全屏运行
        3. 关闭弹出窗口即可回到设置界面

        弹出窗口内：点击「开始实验」后全部 trial 自动进行，评分阶段限时 10 秒。
        """
    )


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
    devices = AcquirerFactory.list_devices()
    current_device = str(config.get("device_type", devices[0] if devices else "dummy"))
    config["device_type"] = st.selectbox(
        "采集设备 (device_type)",
        devices,
        index=devices.index(current_device) if current_device in devices else 0,
    )
    config["hardware_dummy_mode"] = st.checkbox(
        "硬件模拟模式 (dummy)",
        value=bool(config.get("hardware_dummy_mode", False)),
    )
    device_cfg["trigger_serial_port"] = st.text_input(
        "Trigger Box 串口",
        value=str(device_cfg.get("trigger_serial_port", "")),
    )
    config["sfreq"] = float(st.number_input("采样率 (Hz)", min_value=100.0, value=float(config.get("sfreq", 250.0)), step=50.0))
    config["buffer_sec"] = float(st.number_input("缓冲区时长 (秒)", min_value=30.0, value=float(config.get("buffer_sec", 120.0)), step=10.0))

    st.markdown("### 视频材料库")
    library_dir_default = str(
        protocol_cfg.get("video_library_dir") or protocol_cfg.get("video_dir") or "video_library"
    )
    protocol_cfg["video_library_dir"] = st.text_input(
        "视频库目录 (video_library_dir)",
        value=library_dir_default,
        help="所有刺激视频均从此固定目录加载，目录内可放置 manifest.json。",
    )
    mode_options = ("auto", "manifest", "local")
    current_mode = str(protocol_cfg.get("video_library_mode", "manifest"))
    protocol_cfg["video_library_mode"] = st.selectbox(
        "视频库模式 (video_library_mode)",
        mode_options,
        index=mode_options.index(current_mode) if current_mode in mode_options else 1,
        help="manifest=读取 manifest.json（测试可用虚拟列表）；local=扫描目录中的真实视频文件。",
    )
    try:
        library_root, catalog_size, library_mode = _library_summary(config)
        st.caption(f"当前库路径: `{library_root}` · 模式 `{library_mode}` · 可用条目 **{catalog_size}**")
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
    protocol_cfg["trials_per_session"] = int(st.number_input("每 Session Trial 数", min_value=1, value=int(protocol_cfg.get("trials_per_session", 90)), step=1))
    protocol_cfg["random_seed"] = int(st.number_input("随机种子", min_value=0, value=int(protocol_cfg.get("random_seed", 17)), step=1))
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
            playlist = build_playlist_from_config(config)
            st.session_state.playlist = serialize_playlist(playlist)
            st.session_state.results = []
            st.session_state.current_trial = 0
            st.session_state.experiment_state = "idle"
            st.session_state.baseline_done = protocol.baseline_sec <= 0
            st.session_state.eeg_session_dir = None
            st.session_state.phase_log = []
            persist_session(config)
            library = load_video_library(config)
            st.success(
                f"已从视频库 `{library.root}` 生成 {len(playlist)} 个 trial 的播放列表。"
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"生成播放列表失败: {exc}")

    playlist = st.session_state.get("playlist", [])
    playlist_size = len(playlist)

    if playlist_size == 0:
        st.warning("请先生成播放列表，再打开实验窗口。")

    _listen_popup_closed()

    if st.button("打开实验窗口", type="primary", disabled=playlist_size == 0):
        save_config(config)
        st.session_state.runtime_config = dict(config)
        protocol = VideoProtocolConfig.from_config(config)
        reset_for_popup(config, playlist)
        st.session_state.current_trial = 0
        st.session_state.results = []
        st.session_state.experiment_state = "idle"
        st.session_state.baseline_done = protocol.baseline_sec <= 0
        st.session_state.eeg_manager = None
        st.session_state.eeg_session_dir = None
        _open_experiment_popup()
        st.toast("实验窗口已打开，将从 trial 1 重新开始。")

    if st.button("刷新进度"):
        stored = load_session_store(config)
        if stored.get("results"):
            st.session_state.results = stored["results"]
        st.rerun()


def render_probe(config: dict) -> None:
    import time

    st.title("连通检测")
    duration = st.number_input("探测时长 (秒)", min_value=0.1, value=3.0, step=0.5)
    if st.button("开始探测", type="primary"):
        selected_device = str(config.get("device_type", "neuracle"))
        with st.spinner(f"正在连接 {selected_device} ..."):
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
    st.dataframe(pd.DataFrame(rows), use_container_width=True)


def render_data_export(config: dict) -> None:
    st.title("数据导出")
    stored = load_session_store(config)
    results = stored.get("results") or st.session_state.get("results", [])
    if not results:
        st.info("暂无行为评分数据。")
    else:
        df = pd.DataFrame(results)
        st.dataframe(df)
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
            st.dataframe(pd.DataFrame(events[:20]), use_container_width=True)


def _inject_gui_nav_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp { background-color: #ffffff; color: #0f172a; }
        section[data-testid="stSidebar"] {
          background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
          border-right: 1px solid rgba(15, 23, 42, 0.08);
        }
        section[data-testid="stSidebar"] .stButton > button { width: 100%; border-radius: 8px; }
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
          background-color: #0F766E; color: white;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def run_experiment_popup_mode(config: dict) -> None:
    render_experiment_popup(
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
