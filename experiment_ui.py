"""Experiment session UI — runs inside a dedicated popup browser window."""

from __future__ import annotations

import time
from html import escape
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

RATING_VALUES = (1, 2, 3, 4, 5)

RATING_DIMENSIONS = [
    {
        "key": "valence",
        "label": "愉悦度 (Valence)",
        "prompt": "观看视频时感受到的情绪正负性。",
        "levels": ("非常负性", "负性", "中性", "正性", "非常正性"),
    },
    {
        "key": "arousal",
        "label": "唤醒度 (Arousal)",
        "prompt": "观看视频时身心被激活、兴奋或紧张的程度。",
        "levels": ("非常平静", "平静", "中性", "兴奋", "非常兴奋"),
    },
    {
        "key": "immersion",
        "label": "沉浸感 (Immersion)",
        "prompt": "观看视频时投入到画面事件中的程度。",
        "levels": ("非常疏离", "疏离", "中性", "投入", "非常投入"),
    },
    {
        "key": "interest",
        "label": "兴趣度 (Interest)",
        "prompt": "您认为视频内容有趣、吸引人的程度。",
        "levels": ("非常无趣", "无趣", "中性", "有趣", "非常有趣"),
    },
    {
        "key": "visual",
        "label": "视觉感受 (Visual)",
        "prompt": "您认为视频画面令人愉悦、具有吸引力的程度。",
        "levels": ("非常不吸引", "不吸引", "中性", "吸引", "非常吸引"),
    },
    {
        "key": "auditory",
        "label": "听觉感受 (Auditory)",
        "prompt": "您认为视频声音令人愉悦、具有吸引力的程度。",
        "levels": ("非常不愉悦", "不愉悦", "中性", "愉悦", "非常愉悦"),
    },
]

EXPERIMENT_INSTRUCTIONS_MD = """
### 欢迎参与本次实验

在接下来的任务中，您将观看一系列简短的视频片段。

**实验流程：**
1. 首先进行 1 个练习 trial，帮助您熟悉流程。
2. 正式实验共 500 个 trial。
3. 每个 trial 中，屏幕中央会出现十字注视点，请保持静止并注视屏幕中央。
4. 播放一段视频。
5. 短暂空屏。
6. 出现评分界面，请根据您的真实感受对视频进行 6 个维度的 5 点评分。
7. 短暂休息后自动进入下一个视频。

**注意事项：**
- 观看视频时请尽量保持身体和头部静止，减少眨眼，避免干扰脑电信号采集。
- 评分阶段可以自由活动和操作鼠标。
- 练习 trial 的评分没有时间限制，正式实验的评分阶段限时完成。

**评分维度：**
- 愉悦度：非常负性、负性、中性、正性、非常正性。
- 唤醒度：非常平静、平静、中性、兴奋、非常兴奋。
- 沉浸感：非常疏离、疏离、中性、投入、非常投入。
- 兴趣度：非常无趣、无趣、中性、有趣、非常有趣。
- 视觉感受：非常不吸引、不吸引、中性、吸引、非常吸引。
- 听觉感受：非常不愉悦、不愉悦、中性、愉悦、非常愉悦。
"""


def persist_session(config: dict) -> None:
    playlist_raw = st.session_state.get("playlist", [])
    if playlist_raw and isinstance(playlist_raw[0], VideoAsset):
        playlist_payload = serialize_playlist(playlist_raw)
    else:
        playlist_payload = list(playlist_raw)

    practice_raw = st.session_state.get("practice_asset")
    if isinstance(practice_raw, VideoAsset):
        practice_payload = practice_raw.to_mapping()
    elif isinstance(practice_raw, dict):
        practice_payload = dict(practice_raw)
    else:
        practice_payload = None

    save_session_store(
        config,
        {
            "playlist": playlist_payload,
            "practice_asset": practice_payload,
            "playlist_seed": st.session_state.get("playlist_seed"),
            "playlist_metadata": dict(st.session_state.get("playlist_metadata", {})),
            "current_trial": int(st.session_state.get("current_trial", 0)),
            "results": list(st.session_state.get("results", [])),
            "experiment_state": str(st.session_state.get("experiment_state", "instructions")),
            "practice_completed": bool(st.session_state.get("practice_completed", False)),
            "baseline_done": bool(st.session_state.get("baseline_done", False)),
            "eeg_session_dir": st.session_state.get("eeg_session_dir"),
            "phase_log": list(st.session_state.get("phase_log", [])),
            "popup_open": True,
        },
    )


def bootstrap_popup_session(config: dict) -> None:
    """Load playlist only; always start a fresh run inside the popup."""

    defaults = {
        "experiment_state": "instructions",
        "current_trial": 0,
        "results": [],
        "playlist": [],
        "practice_asset": None,
        "practice_completed": False,
        "playlist_seed": None,
        "playlist_metadata": {},
        "eeg_manager": None,
        "eeg_session_dir": None,
        "baseline_done": False,
        "phase_log": [],
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
    if stored.get("practice_asset"):
        st.session_state.practice_asset = VideoAsset.from_mapping(stored["practice_asset"])

    protocol = VideoProtocolConfig.from_config(config)
    st.session_state.current_trial = 0
    st.session_state.results = []
    st.session_state.experiment_state = str(stored.get("experiment_state", "instructions"))
    st.session_state.practice_completed = bool(stored.get("practice_completed", False))
    st.session_state.playlist_seed = stored.get("playlist_seed")
    st.session_state.playlist_metadata = dict(stored.get("playlist_metadata", {}))
    st.session_state.baseline_done = protocol.baseline_sec <= 0
    st.session_state.eeg_manager = None
    st.session_state.eeg_session_dir = None
    st.session_state.rating_started_at = None
    st.session_state.popup_bootstrapped = True


def _playlist_assets() -> list[VideoAsset]:
    return deserialize_playlist(st.session_state.get("playlist", []))


def _asset_at(trial_idx: int) -> VideoAsset:
    return _playlist_assets()[trial_idx]


def _practice_asset() -> VideoAsset:
    asset = st.session_state.get("practice_asset")
    if isinstance(asset, VideoAsset):
        return asset
    if isinstance(asset, dict):
        return VideoAsset.from_mapping(asset)
    raise RuntimeError("Practice video is missing from this run.")


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
        [data-testid="stVerticalBlock"] {
          gap: clamp(2px, 0.8vh, 8px) !important;
        }
        [data-testid="stAppViewContainer"]:has(.instruction-page-anchor),
        [data-testid="stAppViewContainer"]:has(.instruction-page-anchor) [data-testid="stMain"],
        [data-testid="stAppViewContainer"]:has(.instruction-page-anchor) [data-testid="stMainBlockContainer"],
        [data-testid="stAppViewContainer"]:has(.instruction-page-anchor) .block-container {
          overflow-y: auto !important;
          max-height: none !important;
        }
        .instruction-page-anchor + div,
        .instruction-page {
          width: min(920px, calc(100vw - 64px));
          margin: 0 auto;
          padding: clamp(28px, 5vh, 56px) 0 128px;
          color: #ffffff;
          line-height: 1.8;
        }
        .instruction-page h3 {
          font-size: clamp(1.6rem, 4vh, 2.4rem) !important;
        }
        .instruction-page li,
        .instruction-page p {
          font-size: clamp(0.95rem, 2.1vh, 1.12rem) !important;
        }
        [data-testid="stForm"]:has(.rating-page-anchor) {
          position: fixed !important;
          inset: 0 !important;
          z-index: 20 !important;
          width: 100vw !important;
          height: 100dvh !important;
          max-width: 100vw !important;
          max-height: 100dvh !important;
          border: 0 !important;
          border-radius: 0 !important;
          background: #000 !important;
          display: flex !important;
          align-items: center !important;
          justify-content: center !important;
          padding: clamp(18px, 4vh, 48px) clamp(28px, 6vw, 96px) !important;
          overflow-y: auto !important;
        }
        [data-testid="stForm"]:has(.rating-page-anchor) > div {
          width: 100% !important;
          min-height: min(100%, 680px) !important;
          display: flex !important;
          flex-direction: column !important;
          align-items: center !important;
          justify-content: center !important;
          gap: clamp(12px, 2vh, 22px) !important;
        }
        [data-testid="stForm"]:has(.rating-page-anchor) [data-testid="stMarkdownContainer"]:has(.rating-page-anchor) {
          display: none !important;
        }
        [data-testid="stForm"]:has(.rating-page-anchor) [data-testid="stHorizontalBlock"] {
          display: grid !important;
          grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) !important;
          align-items: start !important;
          justify-items: center !important;
          width: 100% !important;
          gap: clamp(28px, 5vw, 72px) !important;
        }
        [data-testid="stForm"]:has(.rating-page-anchor) [data-testid="column"] {
          width: min(480px, 100%) !important;
          min-width: 0 !important;
          flex: unset !important;
          justify-self: center !important;
        }
        [data-testid="stForm"]:has(.rating-page-anchor) [data-testid="column"] [data-testid="stVerticalBlock"] {
          display: flex !important;
          flex-direction: column !important;
          gap: clamp(12px, 2vh, 20px) !important;
          width: 100% !important;
        }
        .rating-header {
          width: min(960px, 100%);
          text-align: center;
          color: #d1d5db;
          font-size: clamp(0.9rem, 2vh, 1.05rem);
          line-height: 1.6;
        }
        .rating-dimension-title {
          margin: 0 0 4px;
          font-size: clamp(0.95rem, 2vh, 1.12rem);
          font-weight: 700;
          color: #ffffff;
        }
        .rating-dimension-prompt {
          margin: 0 0 6px;
          color: #b8c0cc;
          font-size: clamp(0.78rem, 1.6vh, 0.92rem);
          line-height: 1.35;
        }
        .rating-levels {
          display: grid;
          grid-template-columns: repeat(5, minmax(0, 1fr));
          gap: 8px;
          width: 100%;
          margin-bottom: 2px;
          color: #dbeafe;
          font-size: clamp(0.68rem, 1.45vh, 0.82rem);
          line-height: 1.25;
          text-align: center;
        }
        [data-testid="stForm"]:has(.rating-page-anchor) [data-testid="stRadio"] {
          width: 100% !important;
          margin-top: -2px !important;
        }
        [data-testid="stForm"]:has(.rating-page-anchor) [data-testid="stRadio"] > label {
          display: none !important;
        }
        [data-testid="stForm"]:has(.rating-page-anchor) [data-testid="stRadio"] [role="radiogroup"] {
          display: grid !important;
          grid-template-columns: repeat(5, minmax(0, 1fr)) !important;
          justify-items: center !important;
          gap: 8px !important;
          width: 100% !important;
        }
        [data-testid="stForm"]:has(.rating-page-anchor) [data-testid="stRadio"] [role="radiogroup"] label {
          margin: 0 !important;
        }
        [data-testid="stForm"]:has(.rating-page-anchor) [data-testid="stRadio"] [role="radiogroup"] p {
          display: none !important;
        }
        [data-testid="stForm"]:has(.timed-rating-anchor) [data-testid="stFormSubmitButton"] {
          position: fixed !important;
          left: -10000px !important;
          top: 0 !important;
          width: 1px !important;
          height: 1px !important;
          opacity: 0 !important;
          overflow: hidden !important;
        }
        [data-testid="stForm"]:has(.practice-rating-anchor) [data-testid="stFormSubmitButton"] {
          width: min(360px, calc(100vw - 56px)) !important;
          margin-top: clamp(8px, 2vh, 20px) !important;
        }
        [data-testid="stForm"]:has(.practice-rating-anchor) [data-testid="stFormSubmitButton"] button {
          width: 100% !important;
          min-height: 3rem !important;
          font-size: 1.05rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
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


def _pin_start_experiment_button(label: str = "开始实验") -> None:
    safe_label = label.replace("\\", "\\\\").replace('"', '\\"')
    components.html(
        """
        <script>
        (function () {
          const label = "__BUTTON_LABEL__";

          function pinButton() {
            const doc = window.parent.document;
            const button = Array.from(doc.querySelectorAll("button")).find(function (el) {
              return el.textContent && el.textContent.trim() === label;
            });
            if (!button) return false;

            const wrapper = button.closest('[data-testid="stButton"]') || button.parentElement;
            function hideStartButton() {
              Object.assign(wrapper.style, {
                display: "none",
                visibility: "hidden",
                opacity: "0",
                pointerEvents: "none"
              });
            }

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
            if (!button.dataset.videoEegFullscreenBound) {
              button.dataset.videoEegFullscreenBound = "true";
              button.addEventListener("click", function () {
                const el = doc.documentElement;
                const req = el.requestFullscreen || el.webkitRequestFullscreen;
                if (req) req.call(el).catch(function () {});
                hideStartButton();
              });
            }
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
        """.replace("__BUTTON_LABEL__", safe_label),
        height=0,
    )


def _schedule_rating_timeout(remaining: float) -> None:
    delay_ms = max(50, int(remaining * 1000))
    components.html(
        f"""
        <script>
        (function () {{
          const label = "评分时间到";
          const delayMs = {delay_ms};
          const doc = window.parent.document;

          function findTimeoutButton() {{
            return Array.from(doc.querySelectorAll("button")).find(function (el) {{
              return el.textContent && el.textContent.trim() === label;
            }});
          }}

          function setupTimeout() {{
            const button = findTimeoutButton();
            if (!button) return false;

            const wrapper =
              button.closest('[data-testid="stFormSubmitButton"]') ||
              button.closest('[data-testid="stButton"]') ||
              button.parentElement;
            Object.assign(wrapper.style, {{
              position: "fixed",
              left: "-10000px",
              top: "0",
              width: "1px",
              height: "1px",
              opacity: "0",
              overflow: "hidden"
            }});

            if (window.__videoEegRatingTimeout) {{
              clearTimeout(window.__videoEegRatingTimeout);
            }}
            window.__videoEegRatingTimeout = setTimeout(function () {{
              const currentButton = findTimeoutButton();
              if (currentButton) currentButton.click();
            }}, delayMs);
            return true;
          }}

          if (setupTimeout()) return;
          const observer = new MutationObserver(function () {{
            if (setupTimeout()) observer.disconnect();
          }});
          observer.observe(doc.body, {{ childList: true, subtree: true }});
          setTimeout(function () {{ observer.disconnect(); }}, 3000);
        }})();
        </script>
        """,
        height=0,
    )


def _render_phase_banner(phase: str) -> None:
    labels = {
        "fixation": ("+", "注视中央十字，保持静止"),
        "blank": ("",""),
        "iti": ("…", "短暂休息"),
        "baseline": ("+", "请注视中央十字"),
        "ready": ("◎", "准备就绪"),
        "finished": ("✓", "实验完成"),
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


def _rating_key(trial_key: int | str, dimension_key: str) -> str:
    return f"rating_{trial_key}_{dimension_key}"


def _render_rating_dimension(container, *, trial_key: int | str, dimension: dict[str, object]) -> None:
    key = str(dimension["key"])
    levels = tuple(str(level) for level in dimension["levels"])
    current_value = int(st.session_state.get(_rating_key(trial_key, key), 3))
    current_value = min(5, max(1, current_value))
    level_html = "".join(f"<span>{escape(level)}</span>" for level in levels)
    container.markdown(
        f"""
        <div class="rating-dimension-title">{escape(str(dimension["label"]))}</div>
        <div class="rating-dimension-prompt">{escape(str(dimension["prompt"]))}</div>
        <div class="rating-levels">{level_html}</div>
        """,
        unsafe_allow_html=True,
    )
    container.radio(
        str(dimension["label"]),
        options=RATING_VALUES,
        index=current_value - 1,
        format_func=lambda _: "",
        horizontal=True,
        key=_rating_key(trial_key, key),
        label_visibility="collapsed",
    )


def _render_instruction_page() -> None:
    st.markdown('<div class="instruction-page-anchor"></div>', unsafe_allow_html=True)
    st.markdown(EXPERIMENT_INSTRUCTIONS_MD)


def _render_rating_page(
    *,
    trial_key: int | str,
    remaining: float | None,
    submit_label: str,
) -> bool:
    is_timed = remaining is not None
    anchor_class = "timed-rating-anchor" if is_timed else "practice-rating-anchor"
    with st.form(key=f"rating_form_{trial_key}"):
        st.markdown(
            f'<div class="rating-page-anchor {anchor_class}"></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="rating-header">
              请根据刚才观看视频时的真实感受作答。每行从左到右表示程度由低到高，圆圈内不显示数字。
            </div>
            """,
            unsafe_allow_html=True,
        )
        cols = st.columns(2)
        midpoint = (len(RATING_DIMENSIONS) + 1) // 2
        for col, dimensions in zip(cols, (RATING_DIMENSIONS[:midpoint], RATING_DIMENSIONS[midpoint:])):
            for dimension in dimensions:
                _render_rating_dimension(col, trial_key=trial_key, dimension=dimension)
        submitted = st.form_submit_button(submit_label)
    if remaining is not None:
        _schedule_rating_timeout(remaining)
    return submitted


def _collect_ratings(trial_key: int | str) -> dict[str, int]:
    ratings: dict[str, int] = {}
    for dimension in RATING_DIMENSIONS:
        key = str(dimension["key"])
        value = int(st.session_state.get(_rating_key(trial_key, key), 3))
        ratings[str(dimension["label"])] = min(5, max(1, value))
    return ratings


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
        "category": asset.category,
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

    if not st.session_state.playlist or not st.session_state.get("practice_asset"):
        st.error("尚未生成本次练习与正式播放列表。请关闭此窗口，在「实验设置」中重新打开实验窗口。")
        if st.button("关闭窗口"):
            _close_popup_window()
        return

    current = st.session_state.current_trial
    total = len(st.session_state.playlist)
    state = st.session_state.experiment_state
    if current >= total and state not in {"iti", "finished"}:
        st.session_state.experiment_state = "finished"
        state = "finished"

    phase_slot = st.empty()

    def _show_phase(content_fn):
        with phase_slot.container():
            return content_fn()

    if state in {"idle", "instructions"}:
        def _instructions_content() -> None:
            _render_instruction_page()
            if st.button("我已理解，开始练习", type="primary", use_container_width=True):
                start_eeg_session(config)
                st.session_state.baseline_done = protocol.baseline_sec <= 0
                st.session_state.experiment_state = "practice_fixation"
                persist_session(config)
                st.rerun()
            _pin_start_experiment_button("我已理解，开始练习")

        _show_phase(_instructions_content)

    elif state == "practice_fixation":
        manager = _ensure_manager(
            config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session
        )
        trial_idx = -1
        asset = _practice_asset()
        manager.begin_trial(trial_idx=trial_idx, video_name=asset.asset_id)
        manager.fixation_on(trial_idx=trial_idx, video_name=asset.asset_id)
        _show_phase(lambda: _render_phase_banner("fixation"))
        time.sleep(protocol.fixation_sec)
        manager.fixation_off(trial_idx=trial_idx)
        st.session_state.experiment_state = "practice_video"
        persist_session(config)
        st.rerun()

    elif state == "practice_video":
        manager = _ensure_manager(
            config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session
        )
        trial_idx = -1
        asset = _practice_asset()
        manager.video_on(trial_idx=trial_idx, video_name=asset.asset_id)
        with phase_slot.container():
            duration_sec = _render_library_video(config, asset)
        time.sleep(max(duration_sec, 0.1))
        manager.video_off(trial_idx=trial_idx, video_name=asset.asset_id)
        st.session_state.experiment_state = "practice_blank"
        persist_session(config)
        st.rerun()

    elif state == "practice_blank":
        manager = _ensure_manager(
            config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session
        )
        trial_idx = -1
        asset = _practice_asset()
        manager.blank_on(trial_idx=trial_idx)
        _show_phase(lambda: _render_phase_banner("blank"))
        time.sleep(protocol.blank_sec)
        manager.blank_off(trial_idx=trial_idx)
        manager.rating_on(trial_idx=trial_idx, video_name=asset.asset_id)
        st.session_state.rating_started_at = None
        st.session_state.experiment_state = "practice_rating"
        persist_session(config)
        st.rerun()

    elif state == "practice_rating":
        manager = _ensure_manager(
            config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session
        )
        asset = _practice_asset()
        submitted = bool(_show_phase(
            lambda: _render_rating_page(
                trial_key="practice",
                remaining=None,
                submit_label="完成练习，开始正式实验",
            )
        ))
        if submitted:
            manager.rating_off(trial_idx=-1)
            manager.end_trial(trial_idx=-1, video_name=asset.asset_id)
            st.session_state.practice_completed = True
            st.session_state.experiment_state = "practice_iti"
            persist_session(config)
            st.rerun()

    elif state == "practice_iti":
        manager = _ensure_manager(
            config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session
        )
        manager.iti_on(trial_idx=-1)
        _show_phase(lambda: _render_phase_banner("iti"))
        time.sleep(protocol.iti_sec)
        manager.iti_off(trial_idx=-1)
        st.session_state.experiment_state = "baseline" if protocol.baseline_sec > 0 else "fixation"
        persist_session(config)
        st.rerun()

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

        if remaining <= 0:
            timed_out = True
        else:
            timed_out = bool(_show_phase(
                lambda: _render_rating_page(
                    trial_key=trial_idx,
                    remaining=remaining,
                    submit_label="评分时间到",
                )
            ))

        if timed_out:
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
        with phase_slot.container():
            _render_phase_banner("finished")
            session_dir = stop_eeg_session(
                config,
                extra_metadata={
                    "behavioral_trials": len(st.session_state.results),
                    "practice_asset": st.session_state.get("practice_asset"),
                    "playlist_seed": st.session_state.get("playlist_seed"),
                    "playlist_metadata": st.session_state.get("playlist_metadata", {}),
                },
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
                st.success("实验完成。")
            persist_session(config)
            save_session_store(config, {**load_session_store(config), "popup_open": False})
            if st.button("关闭窗口并返回设置", type="primary", use_container_width=True):
                _close_popup_window()
