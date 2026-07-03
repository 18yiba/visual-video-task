"""Streamlit web interface for Video-EEG Experiment."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from acquisition.factory import AcquirerFactory, register_default_acquirers
from cli import (
    build_acquirer,
    build_marker_backend,
    load_config as load_app_config,
    resolve_config_path,
    write_config,
)
from protocol.video_protocol import EegSessionManager, VideoProtocolConfig, build_playlist
from tasks.task_factory import load_task_from_config
from utils.markers import TRIGGER_REFERENCE

_GUI_ROOT = Path(__file__).resolve().parent
_PAGE_ICON = "🎬"

st.set_page_config(page_title="视频神经反应实验台", page_icon=_PAGE_ICON, layout="wide")

SIDEBAR_NAV_PAGES = ("首页", "实验设置", "连通检测", "实验会话", "Trigger 说明", "数据导出")

RATING_DIMENSIONS = [
    "愉悦度 (Valence)",
    "唤醒度 (Arousal)",
    "专注度 (Attention)",
    "熟悉度 (Familiarity)",
    "喜好度 (Preference)",
    "真实感 (Realism)",
    "情绪强度 (Emotion)",
    "视觉质量 (Quality)",
    "动态程度 (Dynamic)",
    "整体评分 (Overall)",
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


def init_session_state(config: dict) -> None:
    protocol = VideoProtocolConfig.from_config(config)
    defaults = {
        "gui_nav_mode": SIDEBAR_NAV_PAGES[0],
        "experiment_state": "idle",
        "current_trial": 0,
        "results": [],
        "playlist": [],
        "eeg_manager": None,
        "eeg_session_dir": None,
        "baseline_done": False,
        "phase_log": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if "runtime_config" not in st.session_state:
        st.session_state.runtime_config = dict(config)


def _set_gui_nav_mode(page: str) -> None:
    st.session_state.gui_nav_mode = page


def _resolve_video_files(video_dir: Path) -> list[str]:
    if not video_dir.exists():
        return []
    extensions = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    return sorted(path.name for path in video_dir.iterdir() if path.suffix.lower() in extensions)


def _append_phase_log(message: str) -> None:
    st.session_state.phase_log.append(f"{datetime.now().strftime('%H:%M:%S')} {message}")
    if len(st.session_state.phase_log) > 40:
        st.session_state.phase_log.pop(0)


def _get_eeg_manager(config: dict) -> EegSessionManager | None:
    return st.session_state.get("eeg_manager")


def _start_eeg_session(config: dict) -> EegSessionManager:
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
            "playlist_size": len(st.session_state.playlist),
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


def render_home() -> None:
    st.title("视频神经反应实验台")
    st.markdown(
        """
        ### 欢迎参与本次实验

        在接下来的任务中，您将观看一系列简短的视频片段，同时系统同步采集脑电（EEG）信号。

        **实验流程：**
        1. 可选静息基线采集（睁眼注视中央十字）。
        2. 屏幕中央出现十字注视点（请保持静止并注视屏幕中央）。
        3. 播放一段视频（6~12 秒）。
        4. 短暂空屏。
        5. 出现评分界面，请根据真实感受对视频进行 **10 个维度的打分**。
        6. 短暂休息后自动进入下一个视频。

        **EEG 采集注意事项：**
        - 观看视频时请尽量保持身体和头部静止，减少眨眼，避免干扰脑电信号。
        - 每个实验阶段均会通过 Trigger Box 发送事件码，便于后续对齐分析。
        - 评分阶段可以自由活动和操作鼠标。

        本次实验由 NCCLab 提供。
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
        help="无真实设备时使用合成 EEG 数据。",
    )
    device_cfg["trigger_serial_port"] = st.text_input(
        "Trigger Box 串口 (留空则仅记录事件、不发送硬件 trigger)",
        value=str(device_cfg.get("trigger_serial_port", "")),
    )
    config["sfreq"] = float(
        st.number_input("采样率 (Hz)", min_value=100.0, value=float(config.get("sfreq", 250.0)), step=50.0)
    )
    config["buffer_sec"] = float(
        st.number_input("缓冲区时长 (秒)", min_value=30.0, value=float(config.get("buffer_sec", 120.0)), step=10.0)
    )

    st.markdown("### 视频 Trial 时间参数")
    t_col1, t_col2, t_col3, t_col4 = st.columns(4)
    protocol_cfg["fixation_sec"] = float(
        t_col1.number_input("注视点 (秒)", min_value=0.5, value=float(protocol_cfg.get("fixation_sec", 1.5)), step=0.5)
    )
    protocol_cfg["default_video_sec"] = float(
        t_col2.number_input(
            "默认视频时长 (秒)",
            min_value=1.0,
            value=float(protocol_cfg.get("default_video_sec", 8.0)),
            step=0.5,
            help="无真实视频文件时用于占位计时。",
        )
    )
    protocol_cfg["blank_sec"] = float(
        t_col3.number_input("空屏 (秒)", min_value=0.5, value=float(protocol_cfg.get("blank_sec", 1.0)), step=0.5)
    )
    protocol_cfg["iti_sec"] = float(
        t_col4.number_input("ITI (秒)", min_value=0.5, value=float(protocol_cfg.get("iti_sec", 2.0)), step=0.5)
    )
    protocol_cfg["baseline_sec"] = float(
        st.number_input("静息基线时长 (秒，0=跳过)", min_value=0.0, value=float(protocol_cfg.get("baseline_sec", 60.0)), step=5.0)
    )
    protocol_cfg["trials_per_session"] = int(
        st.number_input("每 Session Trial 数", min_value=1, value=int(protocol_cfg.get("trials_per_session", 90)), step=1)
    )
    protocol_cfg["video_dir"] = st.text_input("视频目录", value=str(protocol_cfg.get("video_dir", "videos")))
    protocol_cfg["random_seed"] = int(
        st.number_input("随机种子", min_value=0, value=int(protocol_cfg.get("random_seed", 17)), step=1)
    )
    storage_cfg["records_dir"] = st.text_input(
        "EEG 记录目录",
        value=str(storage_cfg.get("records_dir", "records_storage")),
    )
    storage_cfg["ratings_dir"] = st.text_input(
        "行为评分目录",
        value=str(storage_cfg.get("ratings_dir", "ratings_storage")),
    )

    if st.button("保存配置", type="primary"):
        save_config(config)
        st.session_state.runtime_config = dict(config)
        st.success("配置已保存。")

    if st.button("生成播放列表", type="secondary"):
        protocol = VideoProtocolConfig.from_config(config)
        video_dir = Path(protocol.video_dir)
        video_files = _resolve_video_files(video_dir)
        playlist = build_playlist(protocol, video_files=video_files or None)
        st.session_state.playlist = playlist
        st.session_state.current_trial = 0
        st.session_state.results = []
        st.session_state.experiment_state = "ready"
        st.session_state.baseline_done = protocol.baseline_sec <= 0
        st.success(f"已生成 {len(playlist)} 个 trial 的播放列表。")


def render_probe(config: dict) -> None:
    st.title("连通检测")
    st.markdown("在正式开始前，先确认采集设备网络可达并能返回 EEG 数据。")
    duration = st.number_input("探测时长 (秒)", min_value=0.1, value=3.0, step=0.5)

    if st.button("开始探测", type="primary"):
        selected_device = str(config.get("device_type", "neuracle"))
        with st.spinner(f"正在尝试连接 {selected_device} ..."):
            try:
                acquirer = build_acquirer(device_name=selected_device, config=config)
                acquirer.start_stream()
                time.sleep(max(duration, 0.1))
                window, _ = acquirer.get_chunk(float(config.get("window_sec", 2.0)))
                acquirer.stop_stream()
                st.success("设备连通正常。")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Shape", str(window.shape))
                col2.metric("Mean (uV)", f"{window.mean():.3f}")
                col3.metric("Std (uV)", f"{window.std():.3f}")
                col4.metric("Max Abs (uV)", f"{abs(window).max():.3f}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"连通失败: {exc}")


def _render_phase_banner(phase: str) -> None:
    labels = {
        "fixation": ("+", "注视中央十字，保持静止"),
        "video": ("▶", "专注观看视频"),
        "blank": ("", "空屏 — 保持静止"),
        "rating": ("★", "请对刚才的视频进行评分"),
        "iti": ("…", "休息一下"),
        "baseline": ("+", "基线采集 — 睁眼注视中央十字"),
        "ready": ("◎", "准备就绪"),
        "finished": ("✓", "Session 完成"),
    }
    symbol, hint = labels.get(phase, ("·", phase))
    st.markdown(
        f"""
        <div style='padding:1rem;border-radius:12px;background:#F8FAFC;border:1px solid #E2E8F0;text-align:center;'>
          <div style='font-size:3rem;font-weight:700;color:#0F766E;'>{symbol}</div>
          <div style='font-size:1.1rem;color:#334155;'>{hint}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_experiment(config: dict) -> None:
    st.title(
        f"实验进行中 — 被试: {config.get('subject_id', 'S001')} | Session: {config.get('session_id', 1)}"
    )
    protocol = VideoProtocolConfig.from_config(config)

    if not st.session_state.playlist:
        st.warning("尚未生成播放列表，请先前往「实验设置」生成。")
        return

    current = st.session_state.current_trial
    total = len(st.session_state.playlist)
    if current >= total:
        st.session_state.experiment_state = "finished"

    st.progress(current / max(total, 1), text=f"进度: {current} / {total} Trials")
    eeg_status = "采集中" if _get_eeg_manager(config) is not None else "未启动"
    st.caption(f"EEG 状态: {eeg_status} | Session 目录: {st.session_state.get('eeg_session_dir', '—')}")

    state = st.session_state.experiment_state
    container = st.empty()

    if state == "idle":
        with container.container():
            st.info("点击下方按钮启动 EEG 采集并开始实验。")
            if st.button("启动 EEG 并开始 Session", type="primary", use_container_width=True):
                _start_eeg_session(config)
                st.session_state.experiment_state = "baseline" if protocol.baseline_sec > 0 else "ready"
                st.rerun()

    elif state == "baseline" and not st.session_state.baseline_done:
        manager = _get_eeg_manager(config)
        if manager is None:
            manager = _start_eeg_session(config)
        with container.container():
            _render_phase_banner("baseline")
            st.markdown(f"基线采集 {protocol.baseline_sec:.0f} 秒…")
        manager.run_baseline(protocol.baseline_sec)
        st.session_state.baseline_done = True
        st.session_state.experiment_state = "ready"
        st.rerun()

    elif state == "ready":
        with container.container():
            _render_phase_banner("ready")
            if st.button("开始下一个 Trial", type="primary", use_container_width=True):
                if _get_eeg_manager(config) is None:
                    _start_eeg_session(config)
                st.session_state.experiment_state = "fixation"
                st.rerun()

    elif state == "fixation":
        manager = _get_eeg_manager(config)
        trial_idx = current
        video_name = st.session_state.playlist[trial_idx]
        manager.begin_trial(trial_idx=trial_idx, video_name=video_name)
        manager.fixation_on(trial_idx=trial_idx, video_name=video_name)
        with container.container():
            _render_phase_banner("fixation")
        time.sleep(protocol.fixation_sec)
        manager.fixation_off(trial_idx=trial_idx)
        st.session_state.experiment_state = "video"
        st.rerun()

    elif state == "video":
        manager = _get_eeg_manager(config)
        trial_idx = current
        video_name = st.session_state.playlist[trial_idx]
        video_path = Path(protocol.video_dir) / video_name
        manager.video_on(trial_idx=trial_idx, video_name=video_name)
        with container.container():
            _render_phase_banner("video")
            if video_path.exists():
                st.video(str(video_path))
            else:
                st.markdown(
                    f"<h3 style='text-align:center;'>占位播放: {video_name}</h3>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    "<div style='height:280px;background:#000;color:#fff;display:flex;"
                    "align-items:center;justify-content:center;'>VIDEO PLACEHOLDER</div>",
                    unsafe_allow_html=True,
                )
        duration = protocol.default_video_sec
        time.sleep(duration)
        manager.video_off(trial_idx=trial_idx, video_name=video_name)
        st.session_state.experiment_state = "blank"
        st.rerun()

    elif state == "blank":
        manager = _get_eeg_manager(config)
        trial_idx = current
        manager.blank_on(trial_idx=trial_idx)
        with container.container():
            _render_phase_banner("blank")
        time.sleep(protocol.blank_sec)
        manager.blank_off(trial_idx=trial_idx)
        manager.rating_on(trial_idx=trial_idx, video_name=st.session_state.playlist[trial_idx])
        st.session_state.experiment_state = "rating"
        st.rerun()

    elif state == "rating":
        manager = _get_eeg_manager(config)
        trial_idx = current
        video_name = st.session_state.playlist[trial_idx]
        with container.form(key=f"rating_form_{trial_idx}"):
            _render_phase_banner("rating")
            st.markdown("### 请对刚才观看的视频进行评分 (1-9 分)")
            cols = st.columns(2)
            ratings: dict[str, int] = {}
            for index, dim in enumerate(RATING_DIMENSIONS):
                ratings[dim] = cols[index % 2].slider(
                    dim, min_value=1, max_value=9, value=5, key=f"slider_{trial_idx}_{index}"
                )
            submitted = st.form_submit_button("提交评分", type="primary")
            if submitted:
                manager.rating_off(trial_idx=trial_idx)
                result = {
                    "subject_id": config.get("subject_id"),
                    "session_id": config.get("session_id"),
                    "trial_idx": trial_idx,
                    "video_name": video_name,
                    "timestamp": time.time(),
                    "eeg_session_dir": st.session_state.get("eeg_session_dir"),
                }
                result.update(ratings)
                st.session_state.results.append(result)
                manager.end_trial(trial_idx=trial_idx, video_name=video_name)
                st.session_state.current_trial += 1
                st.session_state.experiment_state = "iti"
                st.rerun()

    elif state == "iti":
        manager = _get_eeg_manager(config)
        trial_idx = current - 1
        manager.iti_on(trial_idx=trial_idx)
        with container.container():
            _render_phase_banner("iti")
        time.sleep(protocol.iti_sec)
        manager.iti_off(trial_idx=trial_idx)
        if st.session_state.current_trial >= total:
            st.session_state.experiment_state = "finished"
        else:
            st.session_state.experiment_state = "ready"
        st.rerun()

    elif state == "finished":
        with container.container():
            _render_phase_banner("finished")
            session_dir = _stop_eeg_session(
                config,
                extra_metadata={"behavioral_trials": len(st.session_state.results)},
            )
            if session_dir is not None:
                ratings_path = Path(str(config.get("storage", {}).get("ratings_dir", "ratings_storage")))
                ratings_path.mkdir(parents=True, exist_ok=True)
                ratings_file = ratings_path / f"ratings_{config.get('subject_id')}_session_{config.get('session_id')}.csv"
                pd.DataFrame(st.session_state.results).to_csv(ratings_file, index=False)
                manifest = session_dir / "behavioral_ratings.csv"
                pd.DataFrame(st.session_state.results).to_csv(manifest, index=False)
                st.success(f"Session 完成。EEG 已保存至 `{session_dir}`，行为数据已保存至 `{ratings_file}`。")
            else:
                st.success("Session 完成。")

    if st.session_state.phase_log:
        with st.expander("Trigger / 阶段日志"):
            st.code("\n".join(st.session_state.phase_log))


def render_trigger_reference() -> None:
    st.title("Trigger 事件码设计")
    st.markdown(
        """
        每个实验阶段 onset/offset 均通过 Trigger Box 发送整数事件码，
        并同步写入 `events.json`（含 sample_index 对齐信息）。

        **Trial 内时序：**

        `trial_start` → `fixation_on` → `fixation_off` → `video_on` → `video_off`
        → `blank_on` → `blank_off` → `rating_on` → `rating_off` → `trial_end` → `iti_on` → `iti_off`
        """
    )
    rows = [{"事件码": code, "事件名": name, "说明": desc} for code, desc in TRIGGER_REFERENCE.items()]
    st.dataframe(pd.DataFrame(rows), use_container_width=True)


def render_data_export(config: dict) -> None:
    st.title("数据导出")
    results = st.session_state.results
    if not results:
        st.info("暂无行为评分数据。")
    else:
        df = pd.DataFrame(results)
        st.dataframe(df)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="下载行为评分 CSV",
            data=csv,
            file_name=f"ratings_{config.get('subject_id')}_session_{config.get('session_id')}.csv",
            mime="text/csv",
            type="primary",
        )

    session_dir = st.session_state.get("eeg_session_dir")
    if session_dir:
        path = Path(session_dir)
        st.markdown("### EEG Session 文件")
        if path.exists():
            files = sorted(path.iterdir())
            for file in files:
                st.write(f"- `{file.name}` ({file.stat().st_size // 1024} KB)")
            events_path = path / "events.json"
            if events_path.exists():
                with events_path.open("r", encoding="utf-8") as handle:
                    events = json.load(handle)
                st.markdown("#### 事件预览 (前 20 条)")
                st.dataframe(pd.DataFrame(events[:20]), use_container_width=True)
        else:
            st.warning(f"Session 目录不存在: {session_dir}")


def _inject_gui_nav_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp { background-color: #ffffff; color: #0f172a; }
        section[data-testid="stSidebar"] {
          background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
          border-right: 1px solid rgba(15, 23, 42, 0.08);
        }
        section[data-testid="stSidebar"] .stButton > button {
          width: 100%; border-radius: 8px; padding: 0.6rem; font-weight: 600;
        }
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
          background-color: #0F766E; color: white;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    config = load_config()
    if not config:
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
        mode = st.session_state.gui_nav_mode

    runtime_config = st.session_state.runtime_config
    if mode == "首页":
        render_home()
    elif mode == "实验设置":
        render_settings(runtime_config)
    elif mode == "连通检测":
        render_probe(runtime_config)
    elif mode == "实验会话":
        render_experiment(runtime_config)
    elif mode == "Trigger 说明":
        render_trigger_reference()
    elif mode == "数据导出":
        render_data_export(runtime_config)


if __name__ == "__main__":
    main()
