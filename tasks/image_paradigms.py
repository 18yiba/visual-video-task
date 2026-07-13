"""Streamlit UI and helpers for the two image-rating paradigms."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
from html import escape
import json
import random
import secrets
import time
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from protocol.video_protocol import EegSessionManager, VideoProtocolConfig
from utils.session_store import load as load_session_store
from utils.session_store import save as save_session_store

IMAGE_PARADIGM_LABELS = {"image_a": "图片范式一", "image_b": "图片范式二"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
RATING_VALUES = (1, 2, 3, 4, 5)
RATING_DIMENSIONS = [
    {
        "key": "valence",
        "label": "愉悦度 Valence",
        "prompt": "请评价观看图片时的情绪是偏消极还是偏积极。",
        "levels": ("非常消极", "消极", "中性", "积极", "非常积极"),
    },
    {
        "key": "arousal",
        "label": "唤醒度 Arousal",
        "prompt": "请评价观看图片时身心被激活、兴奋或紧张的程度。",
        "levels": ("非常平静", "平静", "中性", "兴奋", "非常兴奋"),
    },
    {
        "key": "interest",
        "label": "兴趣度 Interest",
        "prompt": "请评价这张图片让你感到有趣、吸引你的程度。",
        "levels": ("非常无趣", "无趣", "中性", "有趣", "非常有趣"),
    },
    {
        "key": "visual_preference",
        "label": "视觉感受 Visual Preference",
        "prompt": "请评价你对这张图片视觉呈现的主观喜欢程度。",
        "levels": ("非常不喜欢", "不喜欢", "中性", "喜欢", "非常喜欢"),
    },
]


@dataclass(slots=True)
class ImageAsset:
    image_id: str
    rel_path: str
    category: str = "unknown"
    split: str = "train"
    has_person: bool | None = None
    is_placeholder: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ImageAsset":
        return cls(
            image_id=str(payload.get("image_id") or payload.get("asset_id") or "placeholder_image"),
            rel_path=str(payload.get("rel_path") or payload.get("image_file") or ""),
            category=str(payload.get("category") or payload.get("emotion_category") or "unknown"),
            split=str(payload.get("split") or "train"),
            has_person=payload.get("has_person"),
            is_placeholder=bool(payload.get("is_placeholder", False)),
        )


@dataclass(slots=True)
class ImageTrial:
    block_idx: int
    trial_idx: int
    block_trial_idx: int
    repeat_idx: int
    trial_type: str
    asset: ImageAsset
    attention_task_presented: bool = False

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["asset"] = self.asset.to_mapping()
        return payload

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ImageTrial":
        return cls(
            block_idx=int(payload["block_idx"]),
            trial_idx=int(payload["trial_idx"]),
            block_trial_idx=int(payload["block_trial_idx"]),
            repeat_idx=int(payload["repeat_idx"]),
            trial_type=str(payload["trial_type"]),
            asset=ImageAsset.from_mapping(dict(payload["asset"])),
            attention_task_presented=bool(payload.get("attention_task_presented", False)),
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


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        html, body, #root { width:100vw!important; height:100dvh!important; margin:0!important; overflow:hidden!important; }
        .stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],[data-testid="stMainBlockContainer"]{background:#050505!important;color:#fff!important;width:100vw!important;height:100dvh!important;overflow:hidden!important;}
        [data-testid="stHeader"],section[data-testid="stSidebar"],[data-testid="stToolbar"],[data-testid="stDecoration"],#MainMenu,footer{display:none!important;visibility:hidden!important;}
        .block-container{padding:0!important;width:100vw!important;height:100dvh!important;max-width:100vw!important;overflow:hidden!important;}
        .stMarkdown,.stText,p,label,h1,h2,h3,span{color:#fff!important;}
        .instruction-page{width:min(920px,calc(100vw - 64px));height:100dvh;margin:0 auto;padding:clamp(28px,5vh,56px) 0 160px;overflow-y:auto;line-height:1.8;position:relative;z-index:1;}
        .instruction-page h2{font-size:clamp(1.6rem,4vh,2.4rem)!important;}
        .phase-page{width:100vw;height:100dvh;display:flex;align-items:center;justify-content:center;background:#000;color:#fff;text-align:center;overflow:hidden;padding:24px;}
        .phase-symbol{font-size:clamp(3rem,14vh,6rem);font-weight:700;line-height:1;}
        .phase-hint{font-size:clamp(1rem,3vh,1.35rem);margin-top:1.2rem;color:#cbd5e1;}
        [data-testid="stElementContainer"]:has(.image-frame),
        [data-testid="stElementContainer"]:has(.image-page),
        [data-testid="stMarkdownContainer"]:has(.image-frame),
        [data-testid="stMarkdownContainer"]:has(.image-page){width:100vw!important;height:100dvh!important;margin:0!important;padding:0!important;max-width:100vw!important;}
        .image-frame,.image-page{position:fixed;inset:0;width:100vw;height:100dvh;display:flex;align-items:center;justify-content:center;background:#000;color:#fff;text-align:center;overflow:hidden;padding:0;z-index:10;}
        .image-frame img{display:block;max-width:100vw;max-height:100dvh;width:auto;height:auto;object-fit:contain;margin:auto;}
        .placeholder-image{width:min(76vw,900px);height:min(62vh,620px);border:1px solid #334155;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:clamp(1rem,3vh,1.8rem);}
        [data-testid="stForm"]{border:0!important;background:#000!important;width:100vw!important;min-height:100dvh!important;display:flex!important;align-items:center!important;justify-content:center!important;padding:clamp(16px,2.6vh,28px) clamp(28px,5vw,96px)!important;}
        [data-testid="stForm"] > div{width:min(1680px,100%)!important;height:calc(100dvh - clamp(32px,5.2vh,56px))!important;margin:0 auto!important;display:flex!important;flex-direction:column!important;align-items:stretch!important;justify-content:center!important;}
        [data-testid="stForm"] [data-testid="stVerticalBlock"]{gap:0!important;}
        .rating-panel{width:100%;margin:0 auto;text-align:center;}
        .rating-title{text-align:center;font-size:clamp(1.08rem,2.35vh,1.55rem);font-weight:700;line-height:1.2;margin:0 0 clamp(12px,1.8vh,18px);}
        .rating-panel-a{height:100%;display:flex;flex-direction:column;justify-content:flex-start;padding-top:clamp(4px,1vh,12px);}
        .rating-panel-a .rating-title{font-size:clamp(1rem,2vh,1.35rem);margin:0 0 clamp(6px,1vh,10px);}
        .rating-panel-a .rating-row{min-height:clamp(42px,5.2vh,60px);margin-bottom:clamp(3px,.55vh,7px);}
        .rating-panel-a [data-testid="stRadio"]{margin-bottom:clamp(10px,1.65vh,18px)!important;}
        [data-testid="stForm"]:has(.rating-panel-a) [data-testid="stFormSubmitButton"]{align-self:center!important;margin-left:auto!important;margin-right:auto!important;width:min(360px,calc(100vw - 64px))!important;}
        [data-testid="stForm"]:has(.rating-panel-a) [data-testid="stFormSubmitButton"] button{display:block!important;margin:0 auto!important;width:100%!important;}
        .rating-row{width:100%;min-height:clamp(48px,5.8vh,68px);margin:0 auto clamp(6px,.9vh,10px);text-align:center;display:flex;flex-direction:column;align-items:center;justify-content:center;}
        .rating-row-title{font-weight:700;font-size:clamp(.95rem,1.75vh,1.14rem);line-height:1.2;margin:0 0 clamp(4px,.55vh,6px);}
        .rating-row-prompt{color:#cbd5e1!important;font-size:clamp(.78rem,1.42vh,.94rem);line-height:1.28;margin:0;max-width:min(760px,calc(100vw - 96px));}
        [data-testid="stForm"] [data-testid="stRadio"]{width:min(1680px,calc(100vw - 96px))!important;max-width:1680px!important;margin:0 auto clamp(14px,2.1vh,24px)!important;align-self:center!important;position:relative!important;z-index:1!important;}
        [data-testid="stForm"] [data-testid="stRadio"] [role="radiogroup"]{display:grid!important;grid-template-columns:repeat(5,minmax(0,1fr))!important;gap:clamp(12px,2.2vw,48px)!important;width:100%!important;margin:0 auto!important;justify-content:center!important;align-items:center!important;}
        [data-testid="stForm"] [data-testid="stRadio"] [role="radiogroup"] label{height:clamp(48px,6.4vh,70px)!important;min-height:0!important;margin:0!important;border:1px solid #334155!important;border-radius:8px!important;padding:0 14px!important;background:#111827!important;position:relative!important;overflow:hidden!important;}
        [data-testid="stForm"] [data-testid="stRadio"] [role="radiogroup"] p{margin:0!important;text-align:center!important;font-size:clamp(.72rem,1.32vh,.92rem)!important;line-height:clamp(48px,6.4vh,70px)!important;white-space:nowrap!important;position:static!important;transform:none!important;}
        [data-testid="stForm"] [data-testid="stRadio"] [role="radiogroup"] label > div:not(:has(p)){position:relative!important;top:50%!important;transform:translateY(-50%)!important;}
        [data-testid="stFormSubmitButton"]{display:flex!important;justify-content:center!important;align-self:center!important;width:min(360px,calc(100vw - 64px))!important;margin:clamp(2px,.4vh,6px) auto 0!important;}
        .stButton>button,[data-testid="stFormSubmitButton"] button{border:1px solid #0f766e!important;background:#0f766e!important;color:#fff!important;border-radius:8px!important;min-height:clamp(2.6rem,5.2vh,3rem)!important;box-shadow:none!important;}
        [data-testid="stFormSubmitButton"] button{width:100%!important;}
        .stButton>button *,[data-testid="stFormSubmitButton"] button *{color:inherit!important;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _pin_start_button(label: str = "我已理解，开始实验") -> None:
    safe_label = label.replace("\\", "\\\\").replace('"', '\\"')
    components.html(
        """
        <script>
        (function () {
          const label = "__BUTTON_LABEL__";
          const doc = window.parent.document;

          function findButton() {
            return Array.from(doc.querySelectorAll("button")).find(function (el) {
              return el.textContent && el.textContent.trim() === label;
            });
          }

          function pinButton() {
            const button = findButton();
            if (!button) return false;
            const wrapper = button.closest('[data-testid="stButton"]') || button.parentElement;
            Object.assign(wrapper.style, {
              position: "fixed",
              left: "50%",
              bottom: "40px",
              transform: "translateX(-50%)",
              width: "min(360px, calc(100vw - 48px))",
              zIndex: "1000",
              display: "block",
              visibility: "visible",
              opacity: "1"
            });
            Object.assign(button.style, {
              width: "100%",
              minHeight: "3rem",
              fontSize: "1.05rem"
            });
            return true;
          }

          if (pinButton()) return;
          const observer = new MutationObserver(function () {
            if (pinButton()) observer.disconnect();
          });
          observer.observe(doc.body, { childList: true, subtree: true });
          setTimeout(function () { observer.disconnect(); }, 3000);
        })();
        </script>
        """.replace("__BUTTON_LABEL__", safe_label),
        height=0,
    )

def _hide_block_start_buttons() -> None:
    components.html(
        """
        <script>
        (function () {
          const doc = window.parent.document;
          const pattern = /^开始第[0-9]+轮任务$/;
          Array.from(doc.querySelectorAll("button")).forEach(function (button) {
            const text = button.textContent ? button.textContent.trim() : "";
            if (!pattern.test(text)) return;
            const wrapper = button.closest('[data-testid="stButton"]') || button.parentElement;
            if (!wrapper) return;
            Object.assign(wrapper.style, {
              display: "none",
              visibility: "hidden",
              opacity: "0",
              pointerEvents: "none"
            });
          });
        })();
        </script>
        """,
        height=0,
    )

def _hide_attention_buttons() -> None:
    components.html(
        """
        <script>
        (function () {
          const doc = window.parent.document;
          const labels = ["\u5426", "\u662f"];

          function hideOnce() {
            Array.from(doc.querySelectorAll("button")).forEach(function (button) {
              const text = button.textContent ? button.textContent.trim() : "";
              if (!labels.includes(text)) return;
              const wrapper = button.closest('[data-testid="stButton"]') || button.parentElement;
              [button, wrapper].forEach(function (el) {
                if (!el) return;
                Object.assign(el.style, {
                  display: "none",
                  visibility: "hidden",
                  opacity: "0",
                  pointerEvents: "none",
                  position: "fixed",
                  left: "-10000px",
                  top: "0",
                  width: "1px",
                  height: "1px",
                  margin: "0",
                  padding: "0",
                  overflow: "hidden"
                });
              });
            });
          }

          hideOnce();
          const observer = new MutationObserver(hideOnce);
          observer.observe(doc.body, { childList: true, subtree: true });
          setTimeout(function () { observer.disconnect(); hideOnce(); }, 900);
        })();
        </script>
        """,
        height=0,
    )

def _protocol_value(config: dict[str, Any], key: str, default: Any) -> Any:
    return dict(config.get("protocol", {})).get(key, default)


def _image_root(config: dict[str, Any]) -> Path:
    return Path(str(_protocol_value(config, "image_library_dir", "image_library")))


def _load_manifest(root: Path) -> list[ImageAsset]:
    manifest = root / "manifest.csv"
    if not manifest.exists() or manifest.stat().st_size == 0:
        return []
    try:
        df = pd.read_csv(manifest)
    except pd.errors.EmptyDataError:
        return []
    assets: list[ImageAsset] = []
    for idx, row in df.iterrows():
        rel_path = str(row.get("rel_path") or row.get("image_file") or row.get("path") or "").strip()
        if not rel_path:
            continue
        assets.append(
            ImageAsset(
                image_id=str(row.get("image_id") or Path(rel_path).stem or f"image_{idx + 1:03d}"),
                rel_path=rel_path,
                category=str(row.get("emotion_category") or row.get("category") or "unknown"),
                split=str(row.get("split") or "train"),
                has_person=(None if pd.isna(row.get("has_person", None)) else bool(row.get("has_person"))),
            )
        )
    return assets


def _scan_image_assets(config: dict[str, Any]) -> list[ImageAsset]:
    root = _image_root(config)
    assets = _load_manifest(root)
    if assets:
        return assets
    if not root.exists():
        return []
    found: list[ImageAsset] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            rel = path.relative_to(root).as_posix()
            if path.parent != root:
                category = path.parent.name
            else:
                category = path.stem.split("-", 1)[0] if "-" in path.stem else "unknown"
            found.append(ImageAsset(image_id=path.stem, rel_path=rel, category=category))
    return found


def _placeholder_assets(count: int = 105) -> list[ImageAsset]:
    categories = ["Amu"] * 15 + ["Dis"] * 15 + ["Fea"] * 15 + ["Ins"] * 15 + ["Neu"] * 15 + ["Sad"] * 15 + ["Ten"] * 15
    return [
        ImageAsset(
            image_id=f"placeholder_{idx + 1:03d}",
            rel_path="",
            category=categories[idx % len(categories)],
            split="test" if idx % 5 == 0 else "train",
            is_placeholder=True,
        )
        for idx in range(count)
    ]


def build_image_playlist(config: dict[str, Any], *, random_seed: int | None = None) -> tuple[list[ImageTrial], list[ImageAsset], dict[str, Any]]:
    seed = int(random_seed if random_seed is not None else secrets.randbits(32))
    rng = random.Random(seed)
    target_images = int(_protocol_value(config, "image_unique_count", 105))
    repeats = int(_protocol_value(config, "image_repeats", 5))
    scanned_assets = _scan_image_assets(config)
    scanned_count = len(scanned_assets)
    used_placeholder = scanned_count == 0
    if used_placeholder:
        assets = _placeholder_assets(target_images)
    else:
        assets = list(scanned_assets[:target_images])
    trials: list[ImageTrial] = []
    trial_idx = 1
    for block_idx in range(1, repeats + 1):
        block_assets = list(assets)
        rng.shuffle(block_assets)
        for block_trial_idx, asset in enumerate(block_assets, start=1):
            trials.append(
                ImageTrial(
                    block_idx=block_idx,
                    trial_idx=trial_idx,
                    block_trial_idx=block_trial_idx,
                    repeat_idx=block_idx,
                    trial_type="rating" if block_idx == 1 else "eeg_denoise",
                    asset=asset,
                    attention_task_presented=(block_idx > 1 and rng.random() < float(_protocol_value(config, "attention_probability", 0.10))),
                )
            )
            trial_idx += 1
    metadata = {
        "task_mode": str(config.get("task_mode", "image_a")),
        "image_unique_count": len(assets),
        "requested_image_count": target_images,
        "scanned_image_count": scanned_count,
        "formal_trials": len(trials),
        "image_repeats": repeats,
        "random_seed": seed,
        "used_placeholder": used_placeholder,
        "image_library_dir": str(_image_root(config)),
    }
    return trials, assets, metadata


def _serialize_trials(trials: list[ImageTrial]) -> list[dict[str, Any]]:
    return [trial.to_mapping() for trial in trials]


def _deserialize_trials(payload: list[Any]) -> list[ImageTrial]:
    return [ImageTrial.from_mapping(dict(item)) for item in payload]


def _persist_session(config: dict[str, Any]) -> None:
    save_session_store(
        config,
        {
            "image_playlist": _serialize_trials(st.session_state.get("image_trials", [])),
            "image_assets": [asset.to_mapping() for asset in st.session_state.get("image_assets", [])],
            "playlist_seed": st.session_state.get("playlist_seed"),
            "playlist_metadata": dict(st.session_state.get("playlist_metadata", {})),
            "current_trial": int(st.session_state.get("current_trial", 0)),
            "results": list(st.session_state.get("results", [])),
            "trial_log": list(st.session_state.get("trial_log", [])),
            "experiment_state": str(st.session_state.get("experiment_state", "instructions")),
            "eeg_session_dir": st.session_state.get("eeg_session_dir"),
            "popup_open": True,
            "block_start_emitted": st.session_state.get("block_start_emitted"),
        },
    )


def bootstrap_image_popup_session(config: dict[str, Any]) -> None:
    defaults = {
        "experiment_state": "instructions",
        "current_trial": 0,
        "image_trials": [],
        "image_assets": [],
        "results": [],
        "trial_log": [],
        "playlist_metadata": {},
        "playlist_seed": None,
        "eeg_manager": None,
        "eeg_session_dir": None,
        "phase_started_at": None,
        "rating_started_at": None,
        "rating_item_index": 0,
        "rating_item_started_at": None,
        "popup_bootstrapped": False,
        "block_start_emitted": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if st.session_state.popup_bootstrapped:
        return
    stored = load_session_store(config)
    if stored.get("image_playlist"):
        st.session_state.image_trials = _deserialize_trials(stored["image_playlist"])
        st.session_state.image_assets = [ImageAsset.from_mapping(item) for item in stored.get("image_assets", [])]
        st.session_state.playlist_seed = stored.get("playlist_seed")
        st.session_state.playlist_metadata = dict(stored.get("playlist_metadata", {}))
        st.session_state.block_start_emitted = stored.get("block_start_emitted")
    else:
        trials, assets, metadata = build_image_playlist(config)
        st.session_state.image_trials = trials
        st.session_state.image_assets = assets
        st.session_state.playlist_seed = metadata["random_seed"]
        st.session_state.playlist_metadata = metadata
    st.session_state.current_trial = 0
    st.session_state.results = []
    st.session_state.trial_log = []
    st.session_state.experiment_state = "instructions"
    st.session_state.popup_bootstrapped = True


def _ensure_manager(config: dict[str, Any], *, get_eeg_manager, start_eeg_session) -> EegSessionManager:
    manager = get_eeg_manager(config)
    if manager is None:
        manager = start_eeg_session(config)
    return manager


def _phase_duration(config: dict[str, Any], key: str, default: float) -> float:
    return float(_protocol_value(config, key, default))


def _jitter(config: dict[str, Any], prefix: str, default_min: float, default_max: float) -> float:
    lo = _phase_duration(config, f"{prefix}_min_sec", default_min)
    hi = _phase_duration(config, f"{prefix}_max_sec", default_max)
    return random.uniform(min(lo, hi), max(lo, hi))


def _phase_elapsed() -> float:
    started = st.session_state.get("phase_started_at")
    if started is None:
        st.session_state.phase_started_at = time.time()
        return 0.0
    return time.time() - float(started)


def _next_state(state: str) -> None:
    st.session_state.experiment_state = state
    st.session_state.phase_started_at = None
    _persist_session(st.session_state.runtime_config if "runtime_config" in st.session_state else {})
    st.rerun()


def _render_phase(symbol: str, hint: str = "", phase: str = "") -> None:
    phase_class = f" phase-{phase}" if phase else ""
    cleanup_style = ""
    if phase == "fixation":
        cleanup_style = "<style>.stApp:has(.phase-fixation) .iti-cover{display:none!important;}</style>"
    st.markdown(
        f"{cleanup_style}<div class='phase-page{phase_class}'><div><div class='phase-symbol'>{escape(symbol)}</div><div class='phase-hint'>{escape(hint)}</div></div></div>",
        unsafe_allow_html=True,
    )


def _render_iti_cover() -> None:
    st.markdown(
        """
        <style>
        .iti-cover {
            width: 100vw;
            height: 100dvh;
            min-height: 100vh;
            background: #000;
        }
        .iti-cover ~ .attention-page,
        .stApp:has(.iti-cover) .attention-page {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
        }
        </style>
        <div class='phase-page iti-cover' aria-hidden='true'></div>
        """,
        unsafe_allow_html=True,
    )

def _render_attention_prompt() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stMainBlockContainer"]:has(.attention-page),
        .block-container:has(.attention-page) {
            width: 100vw !important;
            height: 100dvh !important;
            max-width: 100vw !important;
            padding: 0 clamp(24px, 5vw, 96px) !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            overflow: hidden !important;
            background: #000 !important;
        }
        [data-testid="stVerticalBlock"]:has(.attention-page) {
            width: min(760px, calc(100vw - 64px)) !important;
            min-height: min(430px, 72dvh) !important;
            margin: 0 auto !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            gap: clamp(18px, 3vh, 34px) !important;
        }
        .attention-page {
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #fff;
            text-align: center;
            padding: 0;
        }
        .attention-content {
            width: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: clamp(22px, 4vh, 42px);
        }
        .attention-symbol {
            font-size: clamp(4rem, 14vh, 7rem);
            font-weight: 700;
            line-height: .9;
        }
        .attention-question {
            font-size: clamp(1.2rem, 3.2vh, 1.75rem);
            line-height: 1.35;
            color: #cbd5e1;
            margin: 0;
        }
        [data-testid="stVerticalBlock"]:has(.attention-page) [data-testid="stHorizontalBlock"] {
            width: min(620px, calc(100vw - 96px)) !important;
            margin: clamp(10px, 2vh, 24px) auto 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: clamp(32px, 5vw, 96px) !important;
        }
        [data-testid="stVerticalBlock"]:has(.attention-page) [data-testid="column"] {
            flex: 1 1 0 !important;
            min-width: 0 !important;
        }
        [data-testid="stVerticalBlock"]:has(.attention-page) [data-testid="stButton"] {
            width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
            display: block !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            position: static !important;
            transform: none !important;
        }
        [data-testid="stVerticalBlock"]:has(.attention-page) [data-testid="stButton"] button {
            width: 100% !important;
            min-height: 3.4rem !important;
            font-size: 1.12rem !important;
            border-radius: 8px !important;
            border: 1px solid #0f766e !important;
            background: #0f766e !important;
            color: #fff !important;
        }
        </style>
        <div class='attention-page'>
          <div class='attention-content'>
            <div class='attention-symbol'>?</div>
            <div class='attention-question'>\u56fe\u7247\u4e2d\u662f\u5426\u6709\u4eba\u7269\uff1f</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_phase_banner(phase: str) -> None:
    labels = {
        "fixation": ("+", ""),
        "blank": ("", ""),
        "iti": ("", ""),
        "baseline": ("+", " "),
        "ready": ("◎", "准备就绪"),
        "finished": ("✓", "实验完成"),
        "resting": ("...", "休息一下"),
    }
    symbol, hint = labels.get(phase, (phase, ""))
    _render_phase(symbol, hint, phase)


def _render_image(config: dict[str, Any], asset: ImageAsset) -> None:
    root = _image_root(config)
    path = root / asset.rel_path if asset.rel_path else root / "__missing__"
    if not asset.is_placeholder and path.exists():
        suffix = path.suffix.lower().lstrip(".") or "jpeg"
        mime = "jpeg" if suffix == "jpg" else suffix
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        st.markdown(
            f"<div class='image-frame'><img src='data:image/{mime};base64,{encoded}' alt='{escape(asset.image_id)}'></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div class='image-page'><div class='placeholder-image'>图片呈现<br>{escape(asset.image_id)}</div></div>",
            unsafe_allow_html=True,
        )


def _rating_key(trial_key: int | str, dimension_key: str) -> str:
    return f"image_rating_{trial_key}_{dimension_key}"


def _item_meta_key(trial_key: int | str, dimension_key: str, suffix: str) -> str:
    return f"image_rating_meta_{trial_key}_{dimension_key}_{suffix}"


def _render_dimension(dimension: dict[str, Any], *, trial_key: int | str, show_title: bool = True) -> None:
    key = str(dimension["key"])
    current = min(5, max(1, int(st.session_state.get(_rating_key(trial_key, key), 3))))
    title_html = f"<div class='rating-row-title'>{escape(str(dimension['label']))}</div>" if show_title else ""
    st.markdown(
        f"<div class='rating-row'>{title_html}"
        f"<div class='rating-row-prompt'>{escape(str(dimension['prompt']))}</div></div>",
        unsafe_allow_html=True,
    )
    st.radio(
        str(dimension["label"]),
        options=RATING_VALUES,
        index=current - 1,
        format_func=lambda value, levels=tuple(dimension["levels"]): f"{value} {levels[value - 1]}",
        horizontal=True,
        key=_rating_key(trial_key, key),
        label_visibility="collapsed",
    )


def _render_rating_a(*, trial_key: int | str) -> bool:
    with st.form(key=f"image_rating_a_{trial_key}"):
        st.markdown("<div class='rating-panel rating-panel-a'><div class='rating-title'>请根据刚才观看图片时的真实感受作答</div>", unsafe_allow_html=True)
        for dimension in RATING_DIMENSIONS:
            _render_dimension(dimension, trial_key=trial_key)
        submitted = st.form_submit_button("确认评分，进入下一屏")
        st.markdown("</div>", unsafe_allow_html=True)
    return bool(submitted)


def _schedule_item_timeout(remaining: float) -> None:
    delay_ms = max(50, int(max(remaining, 0.0) * 1000))
    components.html(
        f"""
        <script>
        (function () {{
          const label = "\u81ea\u52a8\u8df3\u8f6c";
          const doc = window.parent.document;

          function findButton() {{
            return Array.from(doc.querySelectorAll("button")).find(function (el) {{
                return el.textContent && el.textContent.trim() === label;
            }});
          }}

          function setup() {{
            const button = findButton();
            if (!button) return false;

            if (window.__imageRatingTimeout) clearTimeout(window.__imageRatingTimeout);
            window.__imageRatingTimeout = setTimeout(function () {{
                const current = findButton();
                if (current) current.click();
            }}, {delay_ms});
            return true;
          }}

          if (setup()) return;
          const observer = new MutationObserver(function () {{ if (setup()) observer.disconnect(); }});
          observer.observe(doc.body, {{childList:true, subtree:true}});
          setTimeout(function () {{ observer.disconnect(); }}, 3000);
        }})();
        </script>
        """,
        height=0,
    )



def _schedule_attention_timeout_button(label: str, remaining: float) -> None:
    delay_ms = max(50, int(max(remaining, 0.0) * 1000))
    safe_label = json.dumps(label, ensure_ascii=False)
    components.html(
        f"""
        <script>
        (function () {{
          const label = {safe_label};
          const doc = window.parent.document;

          function findButton() {{
            return Array.from(doc.querySelectorAll("button")).find(function (el) {{
              return el.textContent && el.textContent.trim() === label;
            }});
          }}

          function hideButton(button) {{
            const wrapper = button.closest('[data-testid="stButton"]') || button.parentElement;
            [button, wrapper].forEach(function (el) {{
              if (!el) return;
              Object.assign(el.style, {{
                position: "fixed",
                left: "-10000px",
                top: "0",
                width: "1px",
                height: "1px",
                margin: "0",
                padding: "0",
                opacity: "0",
                pointerEvents: "none",
                overflow: "hidden"
              }});
            }});
          }}

          function setup() {{
            const button = findButton();
            if (!button) return false;
            hideButton(button);
            if (window.__imageAttentionTimeout) clearTimeout(window.__imageAttentionTimeout);
            window.__imageAttentionTimeout = setTimeout(function () {{
              const current = findButton();
              if (current) current.click();
            }}, {delay_ms});
            return true;
          }}

          if (setup()) return;
          const observer = new MutationObserver(function () {{ if (setup()) observer.disconnect(); }});
          observer.observe(doc.body, {{ childList: true, subtree: true }});
          setTimeout(function () {{ observer.disconnect(); }}, 3000);
        }})();
        </script>
        """,
        height=0,
    )


def _queue_attention_finish(config: dict[str, Any], trial: ImageTrial, *, response: bool | None, response_mode: str, timed_out: bool) -> None:
    st.session_state.pending_attention_response = {
        "trial_idx": trial.trial_idx,
        "response": response,
        "response_mode": response_mode,
        "timed_out": timed_out,
    }
    st.session_state.experiment_state = "attention_finish"
    _persist_session(config)
    st.rerun()


def _render_attention_task_limited(config: dict[str, Any], manager: EegSessionManager, trial: ImageTrial) -> None:
    attention_key = f"attention_started_at_{trial.trial_idx}"
    handled_key = f"attention_handled_{trial.trial_idx}"
    timeout_label = f"attention_timeout_auto_{trial.trial_idx}"

    if st.session_state.get(f"attention_on_emitted_{trial.trial_idx}") is None:
        now = time.time()
        st.session_state[attention_key] = now
        manager.emit("attention_task_on", trial_idx=trial.trial_idx, task_type="has_person")
        st.session_state[f"attention_on_emitted_{trial.trial_idx}"] = True
        _persist_session(config)

    if st.session_state.get(handled_key):
        return

    started_at = float(st.session_state.get(attention_key, time.time()))
    limit = _phase_duration(config, "image_attention_sec", 2.0)
    remaining = max(0.0, limit - (time.time() - started_at))

    _render_attention_prompt()
    no_label = "\u5426"
    yes_label = "\u662f"
    left_col, right_col = st.columns(2, gap="large")
    with left_col:
        no_pressed = st.button(no_label, key=f"attention_no_{trial.trial_idx}", use_container_width=True)
    with right_col:
        yes_pressed = st.button(yes_label, key=f"attention_yes_{trial.trial_idx}", use_container_width=True)
    timeout_pressed = st.button(timeout_label, key=f"attention_timeout_{trial.trial_idx}")
    _schedule_attention_timeout_button(timeout_label, remaining)

    timed_out = timeout_pressed or remaining <= 0
    if no_pressed or yes_pressed:
        st.session_state[handled_key] = True
        _queue_attention_finish(config, trial, response=bool(yes_pressed), response_mode="mouse_click", timed_out=False)
    elif timed_out:
        st.session_state[handled_key] = True
        _queue_attention_finish(config, trial, response=None, response_mode="timeout", timed_out=True)


def _render_rating_b(*, trial_key: int | str, item_index: int, remaining: float) -> bool:
    st.markdown(
        """
        <style>
        [data-testid="stButton"] {
            position: fixed !important;
            left: -10000px !important;
            top: 0 !important;
            width: 0 !important;
            height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            opacity: 0 !important;
            pointer-events: none !important;
            overflow: hidden !important;
        }
        [data-testid="stMainBlockContainer"]:has(.rating-panel-b),
        .block-container:has(.rating-panel-b) {
            width: 100vw !important;
            height: 100dvh !important;
            max-width: 100vw !important;
            padding: 0 clamp(24px, 5vw, 96px) !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            overflow: hidden !important;
        }
        [data-testid="stVerticalBlock"]:has(.rating-panel-b) {
            width: min(1680px, calc(100vw - 96px)) !important;
            max-width: 1680px !important;
            min-height: min(520px, 72dvh) !important;
            margin: 0 auto !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 0 !important;
        }
        [data-testid="stVerticalBlock"]:has(.rating-panel-b) .rating-panel-b {
            width: 100% !important;
            margin: 0 auto clamp(14px, 2.1vh, 24px) !important;
            text-align: center !important;
        }
        [data-testid="stVerticalBlock"]:has(.rating-panel-b) [data-testid="stRadio"] {
            width: min(1680px, calc(100vw - 96px)) !important;
            max-width: 1680px !important;
            margin: 0 auto !important;
            align-self: center !important;
            position: relative !important;
            z-index: 1 !important;
        }
        [data-testid="stVerticalBlock"]:has(.rating-panel-b) [data-testid="stRadio"] [role="radiogroup"] {
            display: grid !important;
            grid-template-columns: repeat(5, minmax(0, 1fr)) !important;
            gap: clamp(12px, 2.2vw, 48px) !important;
            width: 100% !important;
            margin: 0 auto !important;
            justify-content: center !important;
            align-items: center !important;
        }
        [data-testid="stVerticalBlock"]:has(.rating-panel-b) [data-testid="stRadio"] [role="radiogroup"] label {
            height: clamp(48px, 6.4vh, 70px) !important;
            min-height: 0 !important;
            margin: 0 !important;
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
            padding: 0 14px !important;
            background: #111827 !important;
            position: relative !important;
            overflow: hidden !important;
        }
        [data-testid="stVerticalBlock"]:has(.rating-panel-b) [data-testid="stRadio"] [role="radiogroup"] p {
            margin: 0 !important;
            text-align: center !important;
            font-size: clamp(.72rem, 1.32vh, .92rem) !important;
            line-height: clamp(48px, 6.4vh, 70px) !important;
            white-space: nowrap !important;
            position: static !important;
            transform: none !important;
        }
        [data-testid="stVerticalBlock"]:has(.rating-panel-b) [data-testid="stRadio"] [role="radiogroup"] label > div:not(:has(p)) {
            position: relative !important;
            top: 50% !important;
            transform: translateY(-50%) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    dimension = RATING_DIMENSIONS[item_index]
    st.markdown(
        f"<div class='rating-panel rating-panel-b'><div class='rating-title'>\u7b2c {item_index + 1}/{len(RATING_DIMENSIONS)} \u9898 \u00b7 {escape(str(dimension['label']))}</div>",
        unsafe_allow_html=True,
    )
    _render_dimension(dimension, trial_key=trial_key, show_title=False)
    st.markdown("</div>", unsafe_allow_html=True)

    submitted = st.button("\u81ea\u52a8\u8df3\u8f6c", key=f"auto_jump_{trial_key}_{item_index}")
    _schedule_item_timeout(remaining)
    return bool(submitted)


def _collect_ratings(trial_key: int | str) -> dict[str, Any]:
    ratings: dict[str, Any] = {}
    for dimension in RATING_DIMENSIONS:
        key = str(dimension["key"])
        ratings[key] = min(5, max(1, int(st.session_state.get(_rating_key(trial_key, key), 3))))
    return ratings


def _trial_base(config: dict[str, Any], trial: ImageTrial) -> dict[str, Any]:
    return {
        "subject_id": config.get("subject_id"),
        "session_id": config.get("session_id"),
        "task_mode": config.get("task_mode"),
        "block_idx": trial.block_idx,
        "trial_idx": trial.trial_idx,
        "block_trial_idx": trial.block_trial_idx,
        "image_id": trial.asset.image_id,
        "image_file": trial.asset.rel_path,
        "emotion_category": trial.asset.category,
        "split": trial.asset.split,
        "repeat_idx": trial.repeat_idx,
        "trial_type": trial.trial_type,
        "eeg_session_dir": st.session_state.get("eeg_session_dir"),
    }


def _append_rating_result(config: dict[str, Any], trial: ImageTrial, *, timed_out: bool = False) -> None:
    result = _trial_base(config, trial)
    result.update(_collect_ratings(trial.trial_idx))
    result.update(
        {
            "timestamp": time.time(),
            "rating_timed_out": timed_out,
            "rating_confirm_click": config.get("task_mode") == "image_a",
        }
    )
    for dimension in RATING_DIMENSIONS:
        key = str(dimension["key"])
        result[f"{key}_onset"] = st.session_state.get(_item_meta_key(trial.trial_idx, key, "onset"))
        result[f"{key}_offset"] = st.session_state.get(_item_meta_key(trial.trial_idx, key, "offset"))
        result[f"{key}_rt_ms"] = st.session_state.get(_item_meta_key(trial.trial_idx, key, "rt_ms"))
    st.session_state.results.append(result)


def _append_trial_log(config: dict[str, Any], trial: ImageTrial, extra: dict[str, Any] | None = None) -> None:
    row = _trial_base(config, trial)
    row.update(
        {
            "attention_task_presented": trial.attention_task_presented,
            "attention_task_type": "has_person" if trial.attention_task_presented else "",
        }
    )
    if extra:
        row.update(extra)
    st.session_state.trial_log.append(row)

def _event_trial_idx(event: Any) -> int | None:
    payload = getattr(event, "payload", {}) or {}
    value = payload.get("trial_idx")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _events_by_trial(manager: EegSessionManager | None) -> dict[int, dict[str, Any]]:
    if manager is None:
        return {}
    by_trial: dict[int, dict[str, Any]] = {}
    for event in manager.recorder.events:
        trial_idx = _event_trial_idx(event)
        if trial_idx is None:
            continue
        row = by_trial.setdefault(trial_idx, {})
        name = str(event.name)
        t = float(event.relative_time_sec)
        if name == "fixation_on":
            row["fixation_onset"] = t
        elif name == "fixation_off":
            row["fixation_offset"] = t
        elif name == "image_on":
            row["image_onset"] = t
        elif name == "image_off":
            row["image_offset"] = t
        elif name == "blank_on":
            row["blank_onset"] = t
        elif name == "blank_off":
            row["blank_offset"] = t
        elif name == "rating_on":
            row["rating_onset"] = t
        elif name == "rating_off":
            row["rating_offset"] = t
        elif name == "iti_on":
            row["iti_onset"] = t
        elif name == "iti_off":
            row["iti_offset"] = t
        elif name == "rating_item_on":
            item = str((getattr(event, "payload", {}) or {}).get("item", ""))
            if item:
                row[f"{item}_onset"] = t
        elif name == "rating_item_off":
            payload = getattr(event, "payload", {}) or {}
            item = str(payload.get("item", ""))
            if item:
                row[f"{item}_offset"] = t
                row[f"{item}_timed_out"] = bool(payload.get("timed_out", False))
        elif name == "attention_task_on":
            row["attention_task_onset"] = t
        elif name == "attention_response":
            payload = getattr(event, "payload", {}) or {}
            row["attention_response_time"] = t
            row["attention_response"] = payload.get("response")
            row["attention_response_mode"] = payload.get("response_mode", row.get("attention_response_mode"))
            row["attention_timed_out"] = bool(payload.get("timed_out", False))
    return by_trial


def _rating_columns() -> list[str]:
    return [str(dimension["key"]) for dimension in RATING_DIMENSIONS]


def _rating_timing_columns() -> list[str]:
    columns: list[str] = []
    for dimension in RATING_DIMENSIONS:
        key = str(dimension["key"])
        columns.extend([f"{key}_onset", f"{key}_offset", f"{key}_rt_ms", f"{key}_timed_out"])
    return columns


def _ordered_trial_columns() -> list[str]:
    base = [
        "subject_id",
        "session_id",
        "task_mode",
        "block_idx",
        "trial_idx",
        "block_trial_idx",
        "image_id",
        "image_file",
        "emotion_category",
        "split",
        "repeat_idx",
        "trial_type",
        "fixation_onset",
        "fixation_offset",
        "image_onset",
        "image_offset",
        "blank_onset",
        "blank_offset",
        "rating_onset",
        "rating_offset",
        "rating_confirm_click",
        "rating_timed_out",
        *_rating_timing_columns(),
        "attention_task_presented",
        "attention_task_type",
        "attention_task_onset",
        "attention_response",
        "attention_response_mode",
        "attention_response_time",
        "attention_correct",
        "attention_timed_out",
        "reaction_time_ms",
        "iti_onset",
        "iti_offset",
        *_rating_columns(),
        "eeg_session_dir",
    ]
    return base


def _frame_with_order(rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=columns)
    extra = [col for col in df.columns if col not in columns]
    return df.reindex(columns=columns + extra)


def _merge_event_fields(rows: list[dict[str, Any]], manager: EegSessionManager | None) -> list[dict[str, Any]]:
    event_rows = _events_by_trial(manager)
    merged: list[dict[str, Any]] = []
    for row in rows:
        trial_idx = row.get("trial_idx")
        event_row = event_rows.get(int(trial_idx), {}) if trial_idx is not None else {}
        out = dict(row)
        for key, value in event_row.items():
            out[key] = value
        if out.get("attention_task_onset") is not None and out.get("attention_response_time") is not None:
            out.setdefault(
                "reaction_time_ms",
                int((float(out["attention_response_time"]) - float(out["attention_task_onset"])) * 1000),
            )
        merged.append(out)
    return merged


def _build_output_frames(manager: EegSessionManager | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    ratings_rows = _merge_event_fields(list(st.session_state.get("results", [])), manager)
    trial_rows = _merge_event_fields(list(st.session_state.get("trial_log", [])), manager)
    ratings_by_trial = {row.get("trial_idx"): row for row in ratings_rows}
    rating_keys = _rating_columns() + [
        "rating_confirm_click",
        "rating_timed_out",
        *_rating_timing_columns(),
    ]
    enriched_trial_rows: list[dict[str, Any]] = []
    for row in trial_rows:
        out = dict(row)
        rating_row = ratings_by_trial.get(row.get("trial_idx"), {})
        for key in rating_keys:
            if key in rating_row:
                out[key] = rating_row[key]
        enriched_trial_rows.append(out)
    ratings_df = _frame_with_order(ratings_rows, _ordered_trial_columns())
    trial_df = _frame_with_order(enriched_trial_rows, _ordered_trial_columns())
    return ratings_df, trial_df



def _should_take_intrablock_rest(trial: ImageTrial, *, block_size: int) -> bool:
    interval = 35
    return trial.block_trial_idx % interval == 0 and trial.block_trial_idx < block_size

def _finish_trial(config: dict[str, Any], manager: EegSessionManager, trial: ImageTrial, *, include_rating: bool = False, timed_out: bool = False, extra_log: dict[str, Any] | None = None) -> None:
    if include_rating:
        manager.rating_off(trial_idx=trial.trial_idx)
        _append_rating_result(config, trial, timed_out=timed_out)
    manager.iti_on(trial_idx=trial.trial_idx)
    _hide_attention_buttons()
    _render_iti_cover()
    time.sleep(_jitter(config, "image_rating_iti", 1.0, 1.5) if trial.trial_type == "rating" else _jitter(config, "image_denoise_iti", 0.8, 1.2))
    manager.iti_off(trial_idx=trial.trial_idx)
    manager.end_trial(trial_idx=trial.trial_idx, video_name=trial.asset.image_id)
    block_size = len(st.session_state.get("image_assets", [])) or int(_protocol_value(config, "image_unique_count", 105))
    ended_block = trial.block_trial_idx == block_size
    take_intrablock_rest = _should_take_intrablock_rest(trial, block_size=block_size)
    if ended_block:
        manager.emit("block_end", block_idx=trial.block_idx)
    _append_trial_log(config, trial, extra_log)
    st.session_state.current_trial += 1
    if st.session_state.current_trial >= len(st.session_state.image_trials):
        st.session_state.experiment_state = "finished"
    elif ended_block:
        st.session_state.experiment_state = "block_rest"
    elif take_intrablock_rest:
        st.session_state.experiment_state = "intrablock_rest"
    else:
        st.session_state.experiment_state = "trial_fixation"
    st.session_state.phase_started_at = None
    st.session_state.rating_started_at = None
    st.session_state.rating_item_index = 0
    st.session_state.rating_item_started_at = None
    _persist_session(config)
    st.rerun()


def _instruction_md(task_mode: str) -> str:
    rating_count = len(RATING_DIMENSIONS)
    mode_text = (
        f"同屏评分：{rating_count} 个题目会在同一页显示，完成后点击确认进入下一屏。"
        if task_mode == "image_a"
        else f"连续限时评分：{rating_count} 个题目逐一出现，每题限时 2-3 秒，超时自动进入下一题。"
    )
    return f"""
<div class="instruction-page">
<h2>图片观看与主观评分实验</h2>
<p>欢迎参加本次实验。你将佩戴脑电采集设备，同时观看一系列情绪图片。请在图片呈现期间注视屏幕中央，尽量保持头部和身体稳定，减少眨眼、说话和大幅动作。</p>
<p>每张图片第一次出现后，请根据刚才观看图片时的真实感受完成愉悦度、唤醒度和视觉感受评分。评分没有正确或错误答案，请按照第一感受作答。</p>
<p><strong>当前评分方式：</strong>{escape(mode_text)}</p>
<p>后续重复观看阶段通常不需要评分，只需保持注视；少数 trial 会出现简单注意力按键任务，请按提示尽快作答。</p>
</div>
"""





def _pin_attention_buttons(no_label: str, yes_label: str) -> None:
    components.html(
        f"""
        <script>
        (function () {{
          const labels = [{json.dumps(no_label, ensure_ascii=False)}, {json.dumps(yes_label, ensure_ascii=False)}];
          const doc = window.parent.document;

          function findButton(label) {{
            return Array.from(doc.querySelectorAll("button")).find(function (el) {{
              return el.textContent && el.textContent.trim() === label;
            }});
          }}

          function hideButtons() {{
            labels.map(findButton).forEach(function (button) {{
              if (!button) return;
              const wrapper = button.closest('[data-testid="stButton"]') || button.parentElement;
              if (!wrapper) return;
              Object.assign(wrapper.style, {{
                display: "none",
                visibility: "hidden",
                opacity: "0",
                pointerEvents: "none"
              }});
            }});
          }}

          function positionButtons() {{
            const buttons = labels.map(findButton);
            if (!buttons[0] || !buttons[1]) return false;
            buttons.forEach(function (button, index) {{
              const wrapper = button.closest('[data-testid="stButton"]') || button.parentElement;
              Object.assign(wrapper.style, {{
                position: "fixed",
                top: "68%",
                left: index === 0 ? "calc(50% - 150px)" : "calc(50% + 150px)",
                transform: "translate(-50%, -50%)",
                width: "180px",
                zIndex: "1000",
                display: "block",
                visibility: "visible",
                opacity: "1"
              }});
              Object.assign(button.style, {{
                width: "100%",
                minHeight: "3.2rem",
                fontSize: "1.1rem"
              }});
              if (!button.dataset.imageAttentionHideBound) {{
                button.dataset.imageAttentionHideBound = "1";
                button.addEventListener("click", function () {{ setTimeout(hideButtons, 0); }});
              }}
            }});
            return true;
          }}

          if (positionButtons()) return;
          const observer = new MutationObserver(function () {{
            if (positionButtons()) observer.disconnect();
          }});
          observer.observe(doc.body, {{ childList: true, subtree: true }});
          setTimeout(function () {{ observer.disconnect(); }}, 3000);
        }})();
        </script>
        """,
        height=0,
    )

def _render_block_rest(config: dict[str, Any], manager: EegSessionManager, next_trial: ImageTrial) -> None:
    block_idx = int(next_trial.block_idx)
    st.markdown(
        f"""
        <div class='phase-page'>
          <div>
            <div class='phase-symbol'>休息</div>
            <div class='phase-hint'>第 {block_idx - 1} 轮任务已结束。请根据需要休息，准备好后开始下一轮。</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    button_label = f"开始第{block_idx}轮任务"
    if st.button(button_label, type="primary", use_container_width=True, key=f"start_block_{block_idx}"):
        manager.emit("block_start", block_idx=block_idx, started_by="subject_button")
        st.session_state.block_start_emitted = block_idx
        st.session_state.experiment_state = "trial_fixation"
        st.session_state.phase_started_at = None
        _persist_session(config)
        st.rerun()
    _pin_start_button(button_label)

def render_image_experiment_popup(config: dict[str, Any], *, task_mode: str, get_eeg_manager, start_eeg_session, stop_eeg_session) -> None:
    bootstrap_image_popup_session(config)
    st.session_state.runtime_config = config
    _inject_styles()
    state = st.session_state.experiment_state
    trials: list[ImageTrial] = st.session_state.image_trials

    if state in {"idle", "instructions", "placeholder"}:
        start_clicked = st.button("我已理解，开始实验", type="primary", use_container_width=True, key="image_start_experiment")
        _pin_start_button()
        st.markdown(_instruction_md(task_mode), unsafe_allow_html=True)
        if start_clicked:
            try:
                manager = start_eeg_session(config)
            except Exception as exc:  # noqa: BLE001
                st.error(f"启动 EEG session 失败: {exc}")
                return
            protocol = VideoProtocolConfig.from_config(config)
            if protocol.baseline_sec > 0:
                st.session_state.experiment_state = "baseline"
            else:
                st.session_state.experiment_state = "trial_fixation"
            st.session_state.eeg_session_dir = str(manager.session_dir) if manager.session_dir else None
            _persist_session(config)
            st.rerun()
        return

    manager = _ensure_manager(config, get_eeg_manager=get_eeg_manager, start_eeg_session=start_eeg_session)
    protocol = VideoProtocolConfig.from_config(config)

    if state == "baseline":
        _render_phase_banner("baseline")
        manager.run_baseline(protocol.baseline_sec)
        st.session_state.experiment_state = "trial_fixation"
        _persist_session(config)
        st.rerun()

    if st.session_state.current_trial >= len(trials):
        state = "finished"
        st.session_state.experiment_state = "finished"

    if state == "block_rest":
        next_trial = trials[int(st.session_state.current_trial)]
        _render_block_rest(config, manager, next_trial)
        return

    if state == "intrablock_rest":
        _hide_block_start_buttons()
        _hide_attention_buttons()
        _render_phase_banner("resting")
        time.sleep(_phase_duration(config, "image_intrablock_rest_sec", 30.0))
        st.session_state.experiment_state = "trial_fixation"
        st.session_state.phase_started_at = None
        _persist_session(config)
        st.rerun()

    _hide_block_start_buttons()
    if state != "attention_or_iti":
        _hide_attention_buttons()

    if state == "trial_fixation":
        trial = trials[int(st.session_state.current_trial)]
        if trial.block_trial_idx == 1 and st.session_state.get("block_start_emitted") != trial.block_idx:
            manager.emit("block_start", block_idx=trial.block_idx, started_by="auto")
            st.session_state.block_start_emitted = trial.block_idx
        manager.begin_trial(trial_idx=trial.trial_idx, video_name=trial.asset.image_id)
        manager.fixation_on(trial_idx=trial.trial_idx, video_name=trial.asset.image_id)
        _render_phase_banner("fixation")
        time.sleep(_jitter(config, "image_fixation", 0.5, 0.8))
        manager.fixation_off(trial_idx=trial.trial_idx)
        st.session_state.experiment_state = "image"
        _persist_session(config)
        st.rerun()

    elif state == "image":
        trial = trials[int(st.session_state.current_trial)]
        manager.emit("image_on", trial_idx=trial.trial_idx, image_id=trial.asset.image_id)
        _render_image(config, trial.asset)
        time.sleep(_jitter(config, "image_present", 1.0, 1.5))
        manager.emit("image_off", trial_idx=trial.trial_idx, image_id=trial.asset.image_id)
        st.session_state.experiment_state = "blank" if trial.trial_type == "rating" else "attention_or_iti"
        st.session_state.phase_started_at = None
        _persist_session(config)
        st.rerun()

    elif state == "blank":
        trial = trials[int(st.session_state.current_trial)]
        manager.blank_on(trial_idx=trial.trial_idx)
        _render_phase_banner("blank")
        time.sleep(_phase_duration(config, "image_blank_sec", 0.5))
        manager.blank_off(trial_idx=trial.trial_idx)
        manager.rating_on(trial_idx=trial.trial_idx, video_name=trial.asset.image_id)
        st.session_state.rating_started_at = time.time()
        st.session_state.experiment_state = "rating_a" if task_mode == "image_a" else "rating_b"
        _persist_session(config)
        st.rerun()

    elif state == "rating_a":
        trial = trials[int(st.session_state.current_trial)]
        if _render_rating_a(trial_key=trial.trial_idx):
            _finish_trial(config, manager, trial, include_rating=True, timed_out=False)

    elif state == "rating_b":
        trial = trials[int(st.session_state.current_trial)]
        item_index = int(st.session_state.rating_item_index)
        dimension = RATING_DIMENSIONS[item_index]
        key = str(dimension["key"])
        if st.session_state.rating_item_started_at is None:
            now = time.time()
            st.session_state.rating_item_started_at = now
            st.session_state[_item_meta_key(trial.trial_idx, key, "onset")] = now
            manager.emit("rating_item_on", trial_idx=trial.trial_idx, item=key)
        elapsed = time.time() - float(st.session_state.rating_item_started_at)
        limit = _jitter(config, "image_rating_item", 2.0, 3.0)
        remaining = max(0.0, limit - elapsed)
        advanced = remaining <= 0 or _render_rating_b(trial_key=trial.trial_idx, item_index=item_index, remaining=remaining)
        if advanced:
            now = time.time()
            st.session_state[_item_meta_key(trial.trial_idx, key, "offset")] = now
            st.session_state[_item_meta_key(trial.trial_idx, key, "rt_ms")] = int((now - float(st.session_state.rating_item_started_at)) * 1000)
            manager.emit("rating_item_off", trial_idx=trial.trial_idx, item=key, timed_out=remaining <= 0)
            if item_index >= len(RATING_DIMENSIONS) - 1:
                _finish_trial(config, manager, trial, include_rating=True, timed_out=False)
            else:
                st.session_state.rating_item_index = item_index + 1
                st.session_state.rating_item_started_at = None
                _persist_session(config)
                st.rerun()

    elif state == "attention_finish":
        trial = trials[int(st.session_state.current_trial)]
        pending = dict(st.session_state.get("pending_attention_response") or {})
        if int(pending.get("trial_idx", trial.trial_idx)) != trial.trial_idx:
            pending = {"response": None, "response_mode": "timeout", "timed_out": True}
        response = pending.get("response")
        response_mode = str(pending.get("response_mode", "timeout"))
        timed_out = bool(pending.get("timed_out", response_mode == "timeout"))
        manager.emit(
            "attention_response",
            trial_idx=trial.trial_idx,
            response=response,
            response_mode=response_mode,
            timed_out=timed_out,
        )
        correct = None if response is None or trial.asset.has_person is None else bool(response) == bool(trial.asset.has_person)
        extra = {
            "attention_response": response,
            "attention_response_mode": response_mode,
            "attention_correct": correct,
            "attention_timed_out": timed_out,
        }
        st.session_state.pending_attention_response = None
        _finish_trial(config, manager, trial, extra_log=extra)

    elif state == "attention_or_iti":
        trial = trials[int(st.session_state.current_trial)]
        if trial.attention_task_presented:
            _render_attention_task_limited(config, manager, trial)
        else:
            _finish_trial(config, manager, trial)

    elif state == "finished":
        _render_phase_banner("finished")
        manager_for_export = get_eeg_manager(config)
        ratings_df, trial_log_df = _build_output_frames(manager_for_export)
        playlist_payload = _serialize_trials(trials)
        session_dir = stop_eeg_session(
            config,
            extra_metadata={
                "task_mode": task_mode,
                "image_trials": len(trials),
                "image_unique_count": len(st.session_state.get("image_assets", [])),
                "image_repeats": int(_protocol_value(config, "image_repeats", 5)),
                "playlist_seed": st.session_state.get("playlist_seed"),
                "playlist_metadata": st.session_state.get("playlist_metadata", {}),
                "output_files": [
                    "events.json",
                    "metadata.json",
                    "behavioral_ratings.csv",
                    "trial_log.csv",
                    "image_playlist.json",
                ],
            },
        )
        if session_dir is not None:
            session_dir = Path(session_dir)
            ratings_df.to_csv(session_dir / "behavioral_ratings.csv", index=False)
            trial_log_df.to_csv(session_dir / "trial_log.csv", index=False)
            with (session_dir / "image_playlist.json").open("w", encoding="utf-8") as handle:
                json.dump(playlist_payload, handle, ensure_ascii=False, indent=2)
            ratings_dir = Path(str(config.get("storage", {}).get("ratings_dir", "ratings_storage")))
            ratings_dir.mkdir(parents=True, exist_ok=True)
            ratings_df.to_csv(
                ratings_dir / f"ratings_{config.get('subject_id')}_session_{config.get('session_id')}_{task_mode}.csv",
                index=False,
            )
            st.success(f"数据已保存。EEG: `{session_dir}`")
        else:
            st.success("实验完成。")
        save_session_store(config, {**load_session_store(config), "popup_open": False})
        if st.button("关闭窗口并返回设置", type="primary", use_container_width=True):
            _close_popup_window()



def _practice_text(key: str) -> str:
    texts = {
        "title": "\u56fe\u7247\u5b9e\u9a8c\u7ec3\u4e60\u8bd5\u6b21",
        "subtitle": "\u7ec3\u4e60\u4ec5\u7528\u4e8e\u719f\u6089\u6d41\u7a0b\uff0c\u4e0d\u8fdb\u5165\u6b63\u5f0f\u5b9e\u9a8c\u6570\u636e\uff0c\u4e5f\u4e0d\u4f1a\u542f\u52a8 EEG \u91c7\u96c6\u3002",
        "next": "\u4e0b\u4e00\u9875",
        "prev": "\u4e0a\u4e00\u9875",
        "close": "\u7ed3\u675f\u7ec3\u4e60\u5e76\u5173\u95ed\u7a97\u53e3",
    }
    return texts[key]


def _practice_asset(config: dict[str, Any]) -> ImageAsset:
    assets = _scan_image_assets(config)
    if assets:
        return assets[0]
    return _placeholder_assets(1)[0]


def _practice_image_html(config: dict[str, Any], asset: ImageAsset) -> str:
    root = _image_root(config)
    path = root / asset.rel_path if asset.rel_path else root / "__missing__"
    if not asset.is_placeholder and path.exists():
        suffix = path.suffix.lower().lstrip(".") or "jpeg"
        mime = "jpeg" if suffix == "jpg" else suffix
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"<img class='practice-image' src='data:image/{mime};base64,{encoded}' alt='{escape(asset.image_id)}'>"
    return f"<div class='practice-placeholder'>\u56fe\u7247\u5448\u73b0<br>{escape(asset.image_id)}</div>"


def _render_practice_shell(title: str, body: str, *, image_html: str = "") -> None:
    st.markdown(
        f"""
        <style>
        [data-testid="stMainBlockContainer"], .block-container {{
            width: 100vw !important;
            max-width: 100vw !important;
            min-height: 100dvh !important;
            padding: clamp(24px, 4vh, 56px) clamp(24px, 6vw, 96px) !important;
            background: #000 !important;
            color: #fff !important;
        }}
        .practice-page {{
            min-height: calc(100dvh - 120px);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: clamp(20px, 4vh, 36px);
            text-align: center;
        }}
        .practice-title {{font-size: clamp(2rem, 5vh, 3.5rem); font-weight: 800; line-height: 1.15;}}
        .practice-body {{max-width: 980px; color: #dbeafe; font-size: clamp(1.05rem, 2.6vh, 1.45rem); line-height: 1.75; text-align: left;}}
        .practice-body p {{margin: 0 0 0.8rem;}}
        .practice-body ul {{margin: 0.2rem 0 0; padding-left: 1.4rem;}}
        .practice-body li {{margin: 0.35rem 0;}}
        .practice-symbol {{font-size: clamp(5rem, 18vh, 9rem); font-weight: 800; line-height: 1;}}
        .practice-image {{max-width: min(76vw, 920px); max-height: 52dvh; object-fit: contain; display: block;}}
        .practice-placeholder {{width: min(76vw, 920px); height: 46dvh; border: 1px solid #334155; display:flex; align-items:center; justify-content:center; color:#94a3b8; font-size:1.5rem;}}
        .practice-nav {{position: fixed; left: 50%; bottom: 32px; transform: translateX(-50%); width: min(720px, calc(100vw - 48px));}}
        .practice-nav [data-testid="stHorizontalBlock"] {{gap: 18px;}}
        .practice-nav button {{min-height: 3rem !important; border-radius: 8px !important;}}
        </style>
        <div class='practice-page'>
          {image_html}
          <div class='practice-title'>{escape(title)}</div>
          <div class='practice-body'>{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_image_practice_popup(config: dict[str, Any], *, task_mode: str) -> None:
    _inject_styles()
    if "image_practice_step" not in st.session_state:
        st.session_state.image_practice_step = 0
    step = int(st.session_state.image_practice_step)
    asset = _practice_asset(config)
    rating_mode = (
        "\u56fe\u7247\u8303\u5f0f\u4e00\uff1a\u540c\u4e00\u9875\u5b8c\u6210\u6240\u6709\u8bc4\u5206\uff0c\u7136\u540e\u70b9\u51fb\u786e\u8ba4\u8fdb\u5165\u4e0b\u4e00\u5c4f\u3002"
        if task_mode == "image_a"
        else "\u56fe\u7247\u8303\u5f0f\u4e8c\uff1a\u8bc4\u5206\u9898\u9010\u4e2a\u5448\u73b0\uff0c\u6bcf\u9898\u9650\u65f6 2-3 \u79d2\uff0c\u8bf7\u5c3d\u5feb\u70b9\u9009\u3002"
    )
    pages = [
        (
            _practice_text("title"),
            "<p>" + _practice_text("subtitle") + "</p>"
            "<ul><li>\u8fd9\u91cc\u53ea\u6f14\u793a 1 \u4e2a trial \u7684\u9875\u9762\u987a\u5e8f\u548c\u64cd\u4f5c\u8981\u6c42\u3002</li>"
            "<li>\u8bf7\u4f7f\u7528\u9875\u9762\u4e0b\u65b9\u6309\u94ae\u7ffb\u9875\u3002</li></ul>",
            "",
        ),
        (
            "\u6ce8\u89c6\u70b9",
            "<p>\u6b63\u5f0f trial \u5f00\u59cb\u65f6\uff0c\u5c4f\u5e55\u4e2d\u592e\u4f1a\u51fa\u73b0 <strong>+</strong>\u3002</p>"
            "<ul><li>\u8bf7\u628a\u89c6\u7ebf\u653e\u5728\u5c4f\u5e55\u4e2d\u592e\u3002</li><li>\u5c3d\u91cf\u4fdd\u6301\u5934\u90e8\u548c\u8eab\u4f53\u7a33\u5b9a\uff0c\u51cf\u5c11\u7728\u773c\u548c\u8bf4\u8bdd\u3002</li></ul>",
            "<div class='practice-symbol'>+</div>",
        ),
        (
            "\u56fe\u7247\u5448\u73b0",
            "<p>\u6ce8\u89c6\u70b9\u540e\u4f1a\u77ed\u65f6\u95f4\u5448\u73b0\u4e00\u5f20\u56fe\u7247\u3002</p>"
            "<ul><li>\u8bf7\u4fdd\u6301\u6ce8\u89c6\uff0c\u4e0d\u9700\u8981\u5728\u56fe\u7247\u9875\u505a\u4efb\u4f55\u64cd\u4f5c\u3002</li><li>\u8bf7\u6309\u7b2c\u4e00\u611f\u53d7\u8bb0\u4f4f\u81ea\u5df1\u7684\u60c5\u7eea\u548c\u89c6\u89c9\u4f53\u9a8c\u3002</li></ul>",
            _practice_image_html(config, asset),
        ),
        (
            "\u7a7a\u5c4f\u7f13\u51b2",
            "<p>\u56fe\u7247\u7ed3\u675f\u540e\u4f1a\u6709\u4e00\u4e2a\u77ed\u6682\u7a7a\u5c4f\u3002</p>"
            "<ul><li>\u8bf7\u7ee7\u7eed\u6ce8\u89c6\u5c4f\u5e55\u4e2d\u592e\u3002</li><li>\u4e0d\u8981\u5728\u7a7a\u5c4f\u671f\u95f4\u63d0\u524d\u79fb\u52a8\u6216\u601d\u8003\u5176\u4ed6\u56fe\u7247\u3002</li></ul>",
            "",
        ),
        (
            "\u4e3b\u89c2\u8bc4\u5206",
            "<p>" + rating_mode + "</p>"
            "<ul><li><strong>Valence / \u6109\u60a6\u5ea6</strong>\uff1a1=\u975e\u5e38\u6d88\u6781\uff0c3=\u4e2d\u6027\uff0c5=\u975e\u5e38\u79ef\u6781\u3002</li>"
            "<li><strong>Arousal / \u5524\u9192\u5ea6</strong>\uff1a1=\u975e\u5e38\u5e73\u9759\uff0c3=\u4e2d\u7b49\uff0c5=\u975e\u5e38\u5174\u594b\u6216\u7d27\u5f20\u3002</li>"
            "<li><strong>Interest / \u5174\u8da3\u5ea6</strong>\uff1a1=\u975e\u5e38\u65e0\u8da3\uff0c3=\u4e2d\u6027\uff0c5=\u975e\u5e38\u6709\u8da3\u3002</li>"
            "<li><strong>Visual Preference / \u89c6\u89c9\u611f\u53d7</strong>\uff1a1=\u975e\u5e38\u4e0d\u559c\u6b22\uff0c3=\u4e2d\u6027\uff0c5=\u975e\u5e38\u559c\u6b22\u3002</li></ul>",
            "",
        ),
        (
            "\u6ce8\u610f\u529b\u4efb\u52a1",
            "<p>\u5728\u91cd\u590d\u89c2\u770b\u9636\u6bb5\uff0c\u5c11\u6570 trial \u4f1a\u51fa\u73b0\u7b80\u5355\u6ce8\u610f\u529b\u4efb\u52a1\u3002</p>"
            "<ul><li>\u9898\u76ee\uff1a\u56fe\u7247\u4e2d\u662f\u5426\u6709\u4eba\u7269\uff1f</li><li>\u8bf7\u7528\u9f20\u6807\u70b9\u51fb\u201c\u662f\u201d\u6216\u201c\u5426\u201d\u3002</li><li>\u6b63\u5f0f\u5b9e\u9a8c\u4e2d\u8bf7\u5728 2 \u79d2\u5185\u5c3d\u5feb\u4f5c\u7b54\u3002</li></ul>",
            "<div class='practice-symbol'>?</div>",
        ),
        (
            "ITI / trial \u95f4\u9694",
            "<p>\u6bcf\u4e2a trial \u7ed3\u675f\u540e\u4f1a\u8fdb\u5165\u77ed\u6682\u9ed1\u5c4f\u95f4\u9694\u3002</p>"
            "<ul><li>\u8bf7\u7ee7\u7eed\u4fdd\u6301\u6ce8\u89c6\u548c\u653e\u677e\u3002</li><li>\u95f4\u9694\u7ed3\u675f\u540e\u4f1a\u81ea\u52a8\u8fdb\u5165\u4e0b\u4e00\u4e2a trial\u3002</li></ul>",
            "",
        ),
        (
            "\u7ec3\u4e60\u5b8c\u6210",
            "<p>\u4f60\u5df2\u7ecf\u4e86\u89e3\u4e86\u4e00\u4e2a trial \u7684\u9875\u9762\u987a\u5e8f\u548c\u4f5c\u7b54\u8981\u6c42\u3002</p>"
            "<p>\u8fd9\u4e2a\u7ec3\u4e60\u4e0d\u4f1a\u5199\u5165\u6b63\u5f0f\u5b9e\u9a8c\u6570\u636e\uff0c\u4e5f\u4e0d\u4f1a\u5f71\u54cd\u6b63\u5f0f\u5b9e\u9a8c\u7684\u64ad\u653e\u5217\u8868\u3002</p>",
            "<div class='practice-symbol'>\u2713</div>",
        ),
    ]
    step = max(0, min(step, len(pages) - 1))
    title, body, image_html = pages[step]
    _render_practice_shell(title, body, image_html=image_html)
    st.markdown("<div class='practice-nav'>", unsafe_allow_html=True)
    prev_col, next_col = st.columns(2)
    with prev_col:
        if st.button(_practice_text("prev"), use_container_width=True, disabled=step <= 0):
            st.session_state.image_practice_step = max(0, step - 1)
            st.rerun()
    with next_col:
        if step >= len(pages) - 1:
            if st.button(_practice_text("close"), type="primary", use_container_width=True):
                _close_popup_window()
        elif st.button(_practice_text("next"), type="primary", use_container_width=True):
            st.session_state.image_practice_step = min(len(pages) - 1, step + 1)
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_image_placeholder_popup(config: dict[str, Any], *, task_mode: str) -> None:
    render_image_experiment_popup(
        config,
        task_mode=task_mode,
        get_eeg_manager=lambda _config: None,
        start_eeg_session=lambda _config: (_ for _ in ()).throw(RuntimeError("图片实验需要 GUI 传入 EEG session 启停函数。")),
        stop_eeg_session=lambda _config, extra_metadata=None: None,
    )

