"""Experiment session UI — runs inside a dedicated popup browser window."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from protocol.video_protocol import EegSessionManager, VideoProtocolConfig
from utils.session_store import load as load_session_store
from utils.session_store import save as save_session_store
from utils.video_library import (
    VideoAsset,
    deserialize_playlist,
    load_video_library,
    serialize_playlist,
)

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


def persist_session(config: dict) -> None:
    playlist_raw = st.session_state.get("playlist", [])
    if playlist_raw and isinstance(playlist_raw[0], VideoAsset):
        playlist_payload = serialize_playlist(playlist_raw)
    else:
        playlist_payload = list(playlist_raw)

    save_session_store(
        config,
        {
            "playlist": playlist_payload,
            "current_trial": int(st.session_state.get("current_trial", 0)),
            "results": list(st.session_state.get("results", [])),
            "experiment_state": str(st.session_state.get("experiment_state", "idle")),
            "baseline_done": bool(st.session_state.get("baseline_done", False)),
            "eeg_session_dir": st.session_state.get("eeg_session_dir"),
            "phase_log": list(st.session_state.get("phase_log", [])),
            "popup_open": True,
        },
    )


def bootstrap_popup_session(config: dict) -> None:
    """Load playlist only; always start a fresh run inside the popup."""

    defaults = {
        "experiment_state": "idle",
        "current_trial": 0,
        "results": [],
        "playlist": [],
        "eeg_manager": None,
        "eeg_session_dir": None,
        "baseline_done": False,
        "phase_log": [],
        "show_start_dialog": False,
        "rating_started_at": None,
        "popup_bootstrapped": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if st.session_state.popup_bootstrapped:
        return

    stored = load_session_store(config)
    if stored.get("playlist"):
        st.session_state.playlist = deserialize_playlist(stored["playlist"])

    protocol = VideoProtocolConfig.from_config(config)
    st.session_state.current_trial = 0
    st.session_state.results = []
    st.session_state.experiment_state = "idle"
    st.session_state.baseline_done = protocol.baseline_sec <= 0
    st.session_state.eeg_manager = None
    st.session_state.eeg_session_dir = None
    st.session_state.rating_started_at = None
    st.session_state.popup_bootstrapped = True


def _playlist_assets() -> list[VideoAsset]:
    return deserialize_playlist(st.session_state.get("playlist", []))


def _asset_at(trial_idx: int) -> VideoAsset:
    return _playlist_assets()[trial_idx]


def _ensure_manager(config: dict, *, get_eeg_manager, start_eeg_session) -> EegSessionManager:
    manager = get_eeg_manager(config)
    if manager is None:
        manager = start_eeg_session(config)
    return manager


def _render_library_video(config: dict, asset: VideoAsset) -> float:
    """Play a library video fitted to the viewport; return playback duration in seconds."""

    library = load_video_library(config)
    media_path = library.resolve(asset)
    duration_sec = library.playback_duration(asset)

    if library.is_available(asset):
        st.video(str(media_path), autoplay=True, loop=False, muted=False)
    else:
        st.markdown(
            (
                f"<div style='width:100vw;height:100vh;background:#000;color:#888;display:flex;"
                f"flex-direction:column;align-items:center;justify-content:center;"
                f"font-size:1.2rem;line-height:1.8;text-align:center;'>"
                f"<div>虚拟播放 ({duration_sec:.0f}s)</div>"
                f"<div style='color:#666;font-size:0.95rem;'>库路径: {media_path.name}</div>"
                f"<div style='color:#555;font-size:0.85rem;'>ID: {asset.asset_id}</div>"
                f"</div>"
            ),
            unsafe_allow_html=True,
        )
    return duration_sec


def _inject_popup_styles() -> None:
    st.markdown(
        """
        <style>
        html, body, #root {
          width: 100vw !important;
          height: 100dvh !important;
          margin: 0 !important;
          overflow: hidden !important;
          box-sizing: border-box !important;
        }
        *, *::before, *::after {
          box-sizing: border-box !important;
        }
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"] {
          width: 100vw !important;
          height: 100dvh !important;
          max-width: 100vw !important;
          max-height: 100dvh !important;
          min-height: 0 !important;
          background-color: #000000 !important;
          color: #ffffff !important;
          overflow: hidden !important;
        }
        [data-testid="stHeader"] { display: none !important; }
        section[data-testid="stSidebar"] { display: none !important; }
        [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer {
          visibility: hidden !important;
        }
        .block-container {
          padding: 0 !important;
          width: 100vw !important;
          height: 100dvh !important;
          max-width: 100% !important;
          max-height: 100dvh !important;
          overflow: hidden !important;
        }
        .stElementContainer, [data-testid="stElementContainer"] {
          max-width: 100vw !important;
        }
        .stMarkdown, .stText, p, label, h1, h2, h3, h4, h5, h6, span { color: #ffffff !important; }
        [data-testid="stVideo"] {
          width: 100vw !important;
          height: 100dvh !important;
          max-width: 100vw !important;
          max-height: 100dvh !important;
          display: flex !important;
          align-items: center !important;
          justify-content: center !important;
          background: #000 !important;
          overflow: hidden !important;
        }
        [data-testid="stVideo"] video {
          max-width: 100vw !important;
          max-height: 100dvh !important;
          width: auto !important;
          height: auto !important;
          object-fit: contain !important;
          background: #000 !important;
        }
        .rating-title {
          font-size: clamp(1rem, 2.4vh, 1.6rem);
          line-height: 1.2;
          margin: 0 0 clamp(6px, 1.5vh, 14px) 0 !important;
          text-align: center;
          color: #ffffff !important;
        }
        [data-testid="stVerticalBlock"] {
          gap: clamp(2px, 0.8vh, 8px) !important;
        }
        [data-testid="stHorizontalBlock"] {
          gap: clamp(16px, 3vw, 40px) !important;
        }
        [data-testid="stSlider"] {
          min-height: 0 !important;
          padding: 0 !important;
        }
        [data-testid="stSlider"] label {
          min-height: 0 !important;
          padding-bottom: 0 !important;
          font-size: clamp(0.78rem, 1.8vh, 1rem) !important;
        }
        [data-baseweb="slider"] {
          padding-top: clamp(2px, 0.6vh, 6px) !important;
          padding-bottom: clamp(2px, 0.6vh, 6px) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _request_fullscreen() -> None:
    components.html(
        """
        <script>
        (function () {
          const el = window.parent.document.documentElement;
          const req = el.requestFullscreen || el.webkitRequestFullscreen;
          if (req) req.call(el).catch(function () {});
        })();
        </script>
        """,
        height=0,
    )


def _exit_fullscreen() -> None:
    components.html(
        """
        <script>
        (function () {
          const doc = window.parent.document;
          const exit = doc.exitFullscreen || doc.webkitExitFullscreen;
          if (exit && doc.fullscreenElement) exit.call(doc).catch(function () {});
        })();
        </script>
        """,
        height=0,
    )


def _close_popup_window() -> None:
    components.html(
        """
        <script>
        (function () {
          try {
            if (window.opener) {
              window.opener.postMessage({ type: "video_eeg_experiment_closed" }, "*");
              window.opener.focus();
            }
          } catch (e) {}
          window.close();
        })();
        </script>
        """,
        height=0,
    )


def _pin_start_experiment_button() -> None:
    components.html(
        """
        <script>
        (function () {
          const label = "开始实验";

          function pinButton() {
            const doc = window.parent.document;
            const button = Array.from(doc.querySelectorAll("button")).find(function (el) {
              return el.textContent && el.textContent.trim() === label;
            });
            if (!button) return false;

            const wrapper = button.closest('[data-testid="stButton"]') || button.parentElement;
            Object.assign(wrapper.style, {
              position: "fixed",
              left: "50%",
              bottom: "48px",
              transform: "translateX(-50%)",
              width: "min(360px, calc(100vw - 48px))",
              zIndex: "1000"
            });
            Object.assign(button.style, {
              width: "100%",
              minHeight: "3rem",
              fontSize: "1.1rem"
            });
            return true;
          }

          if (pinButton()) return;
          const observer = new MutationObserver(function () {
            if (pinButton()) observer.disconnect();
          });
          observer.observe(window.parent.document.body, { childList: true, subtree: true });
          setTimeout(function () { observer.disconnect(); }, 3000);
        })();
        </script>
        """,
        height=0,
    )


def _render_phase_banner(phase: str) -> None:
    labels = {
        "fixation": ("+", "注视中央十字，保持静止"),
        "blank": ("", "空屏 — 保持静止"),
        "iti": ("…", "休息一下"),
        "baseline": ("+", "基线采集 — 睁眼注视中央十字"),
        "ready": ("◎", "准备就绪"),
        "finished": ("✓", "Session 完成"),
    }
    symbol, hint = labels.get(phase, ("·", phase))
    st.markdown(
        f"""
        <div style='width:100vw;height:100dvh;max-width:100vw;max-height:100dvh;
        display:flex;flex-direction:column;align-items:center;justify-content:center;
        text-align:center;background:#000;color:#fff;overflow:hidden;padding:24px;'>
          <div style='font-size:clamp(3rem,14vh,6rem);font-weight:700;line-height:1;color:#ffffff;'>{symbol}</div>
          <div style='font-size:clamp(1rem,3vh,1.4rem);margin-top:clamp(0.75rem,3vh,1.5rem);color:#cccccc;'>{hint}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_rating_page(
    *,
    trial_idx: int,
    remaining: float,
) -> None:
    st.markdown(
        f"""
        <h2 class="rating-title">请对刚才的视频进行评分 — 剩余 {remaining:.0f} 秒</h2>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(2)
    for index, dim in enumerate(RATING_DIMENSIONS):
        slider_key = f"rating_{trial_idx}_{index}"
        cols[index % 2].slider(
            dim,
            min_value=1,
            max_value=9,
            value=int(st.session_state.get(slider_key, 5)),
            key=slider_key,
        )


def _collect_ratings(trial_idx: int) -> dict[str, int]:
    ratings: dict[str, int] = {}
    for index, dim in enumerate(RATING_DIMENSIONS):
        slider_key = f"rating_{trial_idx}_{index}"
        ratings[dim] = int(st.session_state.get(slider_key, 5))
    return ratings


@st.dialog("实验即将开始")
def _confirm_experiment_start(
    config: dict,
    protocol: VideoProtocolConfig,
    *,
    start_eeg_session,
) -> None:
    st.markdown(
        f"""
        **请确认：**
        - 您已坐好并保持舒适姿势
        - 窗口即将进入全屏
        - 实验开始后将自动进行全部 trial
        - 每个视频评分限时 **{protocol.rating_sec:.0f} 秒**
        """
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("取消", use_container_width=True):
            st.session_state.show_start_dialog = False
            st.rerun()
    with col2:
        if st.button("确认开始", type="primary", use_container_width=True):
            st.session_state.show_start_dialog = False
            start_eeg_session(config)
            st.session_state.baseline_done = protocol.baseline_sec <= 0
            st.session_state.experiment_state = (
                "baseline" if protocol.baseline_sec > 0 else "fixation"
            )
            persist_session(config)
            st.rerun()


def _finalize_rating(
    config: dict,
    manager: EegSessionManager | None,
    *,
    trial_idx: int,
    asset: VideoAsset,
    ratings: dict[str, int],
    timed_out: bool,
) -> None:
    if manager is not None:
        manager.rating_off(trial_idx=trial_idx)
    result = {
        "subject_id": config.get("subject_id"),
        "session_id": config.get("session_id"),
        "trial_idx": trial_idx,
        "asset_id": asset.asset_id,
        "rel_path": asset.rel_path,
        "timestamp": time.time(),
        "eeg_session_dir": st.session_state.get("eeg_session_dir"),
        "rating_timed_out": timed_out,
    }
    result.update(ratings)
    st.session_state.results.append(result)
    if manager is not None:
        manager.end_trial(trial_idx=trial_idx, video_name=asset.asset_id)
    st.session_state.current_trial += 1
    st.session_state.rating_started_at = None
    persist_session(config)


def render_experiment_popup(
    config: dict,
    *,
    get_eeg_manager,
    start_eeg_session,
    stop_eeg_session,
) -> None:
    """Render the full experiment flow inside a popup window."""
    bootstrap_popup_session(config)
    _inject_popup_styles()
    protocol = VideoProtocolConfig.from_config(config)

    if not st.session_state.playlist:
        st.error("尚未生成播放列表。请关闭此窗口，在「实验设置」中生成播放列表后再试。")
        if st.button("关闭窗口"):
            _close_popup_window()
        return

    current = st.session_state.current_trial
    total = len(st.session_state.playlist)
    if current >= total:
        st.session_state.experiment_state = "finished"

    state = st.session_state.experiment_state
    phase_slot = st.empty()

    if state not in {"idle", "finished"}:
        _request_fullscreen()

    def _show_phase(content_fn) -> None:
        phase_slot.empty()
        with phase_slot.container():
            content_fn()

    if state == "idle":
        def _idle_content() -> None:
            _render_phase_banner("ready")
            if st.button("开始实验", type="primary", use_container_width=True):
                st.session_state.show_start_dialog = True
            _pin_start_experiment_button()

        _show_phase(_idle_content)
        if st.session_state.get("show_start_dialog"):
            _confirm_experiment_start(
                config,
                protocol,
                start_eeg_session=start_eeg_session,
            )

    elif state == "baseline" and not st.session_state.baseline_done:
        manager = _ensure_manager(
            config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session
        )
        _show_phase(lambda: _render_phase_banner("baseline"))
        manager.run_baseline(protocol.baseline_sec)
        st.session_state.baseline_done = True
        st.session_state.experiment_state = "fixation"
        persist_session(config)
        st.rerun()

    elif state == "fixation":
        manager = _ensure_manager(
            config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session
        )
        trial_idx = current
        asset = _asset_at(trial_idx)
        manager.begin_trial(trial_idx=trial_idx, video_name=asset.asset_id)
        manager.fixation_on(trial_idx=trial_idx, video_name=asset.asset_id)
        _show_phase(lambda: _render_phase_banner("fixation"))
        time.sleep(protocol.fixation_sec)
        manager.fixation_off(trial_idx=trial_idx)
        st.session_state.experiment_state = "video"
        persist_session(config)
        st.rerun()

    elif state == "video":
        manager = _ensure_manager(
            config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session
        )
        trial_idx = current
        asset = _asset_at(trial_idx)
        manager.video_on(trial_idx=trial_idx, video_name=asset.asset_id)
        phase_slot.empty()
        with phase_slot.container():
            duration_sec = _render_library_video(config, asset)
        time.sleep(max(duration_sec, 0.1))
        manager.video_off(trial_idx=trial_idx, video_name=asset.asset_id)
        st.session_state.experiment_state = "blank"
        persist_session(config)
        st.rerun()

    elif state == "blank":
        manager = _ensure_manager(
            config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session
        )
        trial_idx = current
        manager.blank_on(trial_idx=trial_idx)
        _show_phase(lambda: _render_phase_banner("blank"))
        time.sleep(protocol.blank_sec)
        manager.blank_off(trial_idx=trial_idx)
        manager.rating_on(trial_idx=trial_idx, video_name=_asset_at(trial_idx).asset_id)
        st.session_state.rating_started_at = time.time()
        st.session_state.experiment_state = "rating"
        persist_session(config)
        st.rerun()

    elif state == "rating":
        manager = _ensure_manager(
            config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session
        )
        trial_idx = current
        asset = _asset_at(trial_idx)
        if st.session_state.rating_started_at is None:
            st.session_state.rating_started_at = time.time()
        elapsed = time.time() - float(st.session_state.rating_started_at)
        remaining = max(0.0, protocol.rating_sec - elapsed)

        _show_phase(lambda: _render_rating_page(trial_idx=trial_idx, remaining=remaining))

        if remaining <= 0:
            _finalize_rating(
                config,
                manager,
                trial_idx=trial_idx,
                asset=asset,
                ratings=_collect_ratings(trial_idx),
                timed_out=True,
            )
            st.session_state.experiment_state = "iti"
            st.rerun()
        else:
            time.sleep(0.25)
            st.rerun()

    elif state == "iti":
        manager = _ensure_manager(
            config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session
        )
        trial_idx = max(0, current - 1)
        manager.iti_on(trial_idx=trial_idx)
        _show_phase(lambda: _render_phase_banner("iti"))
        time.sleep(protocol.iti_sec)
        manager.iti_off(trial_idx=trial_idx)
        if st.session_state.current_trial >= total:
            st.session_state.experiment_state = "finished"
        else:
            st.session_state.experiment_state = "fixation"
        persist_session(config)
        st.rerun()

    elif state == "finished":
        _exit_fullscreen()
        phase_slot.empty()
        with phase_slot.container():
            _render_phase_banner("finished")
            session_dir = stop_eeg_session(
                config,
                extra_metadata={"behavioral_trials": len(st.session_state.results)},
            )
            if session_dir is not None:
                ratings_path = Path(str(config.get("storage", {}).get("ratings_dir", "ratings_storage")))
                ratings_path.mkdir(parents=True, exist_ok=True)
                ratings_file = (
                    ratings_path / f"ratings_{config.get('subject_id')}_session_{config.get('session_id')}.csv"
                )
                pd.DataFrame(st.session_state.results).to_csv(ratings_file, index=False)
                pd.DataFrame(st.session_state.results).to_csv(session_dir / "behavioral_ratings.csv", index=False)
                st.success(f"数据已保存。EEG: `{session_dir}`")
            else:
                st.success("Session 完成。")
            persist_session(config)
            save_session_store(config, {**load_session_store(config), "popup_open": False})
            if st.button("关闭窗口并返回设置", type="primary", use_container_width=True):
                _close_popup_window()
