"""Streamlit-free helpers for image EEG paradigms."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import random
import re
import secrets
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
RATING_VALUES = (1, 2, 3, 4, 5)
LABELING_SESSIONS = {1, 2}
DENOISE_SESSIONS = {3, 4, 5, 6, 7, 8, 9, 10}
VALID_IMAGE_SESSIONS = LABELING_SESSIONS | DENOISE_SESSIONS
TIMESTAMP_LABEL_PATTERN = re.compile(r"^\d{8}_[A-Za-z0-9_-]+$")

RATING_DIMENSIONS = [
    {
        "key": "valence",
        "label": "情绪效价",
        "prompt": "观看这张图片时，你的主观感受是？",
        "levels": ("非常不愉悦", "有些不愉悦", "无明显倾向", "有些愉悦", "非常愉悦"),
    },
    {
        "key": "arousal",
        "label": "唤醒程度",
        "prompt": "观看这张图片时，你内心的情绪波动强度是？",
        "levels": ("毫无波澜", "稍有触动", "中等反应", "较为强烈", "极其强烈"),
    },
    {
        "key": "interest",
        "label": "兴趣程度",
        "prompt": "这张图片在多大程度上吸引了你的注意力或使你产生兴趣？",
        "levels": ("毫无兴趣", "不太感兴趣", "中等吸引力", "比较感兴趣", "极感兴趣"),
    },
    {
        "key": "visual_preference",
        "label": "视觉偏好",
        "prompt": "单从视觉美感来看，你对这张图片的喜好程度是？",
        "levels": ("非常不喜欢", "不喜欢", "一般", "喜欢", "非常喜欢"),
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
            image_id=str(payload.get("image_id") or payload.get("asset_id") or payload.get("id") or "placeholder_image"),
            rel_path=str(payload.get("rel_path") or payload.get("image_file") or payload.get("file") or ""),
            category=str(payload.get("category") or payload.get("emotion_category") or "unknown"),
            split=str(payload.get("split") or "train"),
            has_person=_coerce_optional_bool(payload.get("has_person")),
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


def protocol_value(config: dict[str, Any], key: str, default: Any) -> Any:
    return dict(config.get("protocol", {})).get(key, default)


def image_root(config: dict[str, Any], *, base_dir: Path | None = None) -> Path:
    root = Path(str(protocol_value(config, "image_library_dir", "image_library")))
    if root.is_absolute() or base_dir is None:
        return root
    return base_dir / root


def image_path(config: dict[str, Any], asset: ImageAsset, *, base_dir: Path | None = None) -> Path:
    return image_root(config, base_dir=base_dir) / asset.rel_path


def session_type_for_id(session_id: int) -> str:
    session_id = int(session_id)
    if session_id in LABELING_SESSIONS:
        return "labeling"
    if session_id in DENOISE_SESSIONS:
        return "denoise"
    raise ValueError("Image_B session_id must be 1-10: 1-2 labeling, 3-10 denoise.")


def subject_image_set_path(records_dir: Path, subject_id: str, image_set_label: str = "") -> Path:
    root = records_dir / str(subject_id)
    if not image_set_label or image_set_label == "default":
        return root / "subject_image_set.json"
    return root / f"subject_image_set_{image_set_label}.json"


def scan_image_assets(config: dict[str, Any], *, base_dir: Path | None = None) -> list[ImageAsset]:
    root = image_root(config, base_dir=base_dir)
    assets = _load_manifest(root)
    if assets:
        return assets
    if not root.exists():
        return []

    found: list[ImageAsset] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            rel = path.relative_to(root).as_posix()
            category = path.parent.name if path.parent != root else _category_from_stem(path.stem)
            found.append(ImageAsset(image_id=path.stem, rel_path=rel, category=category))
    return found


def build_session_playlist(
    config: dict[str, Any],
    *,
    subject_id: str,
    session_id: int,
    records_dir: Path,
    base_dir: Path | None = None,
    image_count: int | None = None,
    random_seed: int | None = None,
) -> tuple[list[ImageTrial], list[ImageAsset], dict[str, Any]]:
    """Build the single-session Image_B playlist and maintain subject image set."""

    session_id = int(session_id)
    session_type = session_type_for_id(session_id)
    seed = int(random_seed if random_seed is not None else protocol_value(config, "random_seed", 17))
    target_images = int(
        image_count
        if image_count is not None
        else protocol_value(config, "images_per_experiment", protocol_value(config, "image_unique_count", 105))
    )
    if target_images <= 0:
        raise ValueError("Image count must be positive.")

    image_set_label = str(config.get("image_set_label", "default")).strip() or "default"
    set_path = subject_image_set_path(records_dir, subject_id, image_set_label)
    legacy_set_path = subject_image_set_path(records_dir, subject_id)
    nested_set_path = records_dir / str(subject_id) / image_set_label / "subject_image_set.json"
    if not set_path.exists() and nested_set_path.exists():
        set_path = nested_set_path
    if image_set_label == "default" and not set_path.exists() and legacy_set_path.exists():
        set_path = legacy_set_path
    scanned_assets = scan_image_assets(config, base_dir=base_dir)
    scanned_count = len(scanned_assets)
    if scanned_count == 0:
        raise RuntimeError(f"No image assets found under {image_root(config, base_dir=base_dir)}")
    if target_images > scanned_count:
        raise ValueError(f"Requested {target_images} images, but image library contains only {scanned_count}.")

    generated_subject_set = False
    if set_path.exists():
        assets = load_subject_image_set(set_path)
    elif session_id == 1:
        rng = random.Random(f"{seed}:{subject_id}:{image_set_label}")
        assets = list(scanned_assets)
        rng.shuffle(assets)
        assets = assets[:target_images]
        save_subject_image_set(
            set_path,
            assets,
            metadata={
                "subject_id": subject_id,
                "created_by_session_id": session_id,
                "image_count": len(assets),
                "random_seed": seed,
                "image_library_dir": str(image_root(config, base_dir=base_dir)),
            },
        )
        generated_subject_set = True
    else:
        raise RuntimeError(
            f"Subject image set not found: {set_path}. Run session 1 for subject {subject_id} first."
        )

    if not assets:
        raise RuntimeError(f"Subject image set is empty: {set_path}")
    if image_count is None and not generated_subject_set:
        # Once a subject set exists it is authoritative unless the operator
        # explicitly enters a non-zero override in the startup dialog.
        target_images = len(assets)
    if target_images > len(assets):
        raise ValueError(
            f"Requested {target_images} images for this experiment, but the subject image set contains only {len(assets)}."
        )

    session_assets = list(assets[:target_images])
    rng = random.Random(seed + session_id * 1009)
    rng.shuffle(session_assets)
    attention_probability = float(protocol_value(config, "attention_probability", 0.10))
    trials: list[ImageTrial] = []
    for idx, asset in enumerate(session_assets, start=1):
        trials.append(
            ImageTrial(
                block_idx=1,
                trial_idx=idx,
                block_trial_idx=idx,
                repeat_idx=session_id,
                trial_type="rating" if session_type == "labeling" else "eeg_denoise",
                asset=asset,
                attention_task_presented=(session_type == "denoise" and rng.random() < attention_probability),
            )
        )

    metadata = {
        "task_mode": str(config.get("task_mode", "image_b")),
        "image_set_label": image_set_label,
        "session_id": session_id,
        "session_type": session_type,
        "image_unique_count": len(session_assets),
        "requested_image_count": target_images,
        "scanned_image_count": scanned_count,
        "formal_trials": len(trials),
        "random_seed": seed,
        "subject_image_set_path": str(set_path),
        "generated_subject_image_set": generated_subject_set,
        "image_library_dir": str(image_root(config, base_dir=base_dir)),
    }
    return trials, session_assets, metadata


def build_image_playlist(
    config: dict[str, Any],
    *,
    random_seed: int | None = None,
    base_dir: Path | None = None,
) -> tuple[list[ImageTrial], list[ImageAsset], dict[str, Any]]:
    """Backward-compatible multi-repeat playlist used by older Streamlit code."""

    seed = int(random_seed if random_seed is not None else secrets.randbits(32))
    rng = random.Random(seed)
    target_images = int(protocol_value(config, "image_unique_count", 105))
    repeats = int(protocol_value(config, "image_repeats", 5))
    scanned_assets = scan_image_assets(config, base_dir=base_dir)
    scanned_count = len(scanned_assets)
    used_placeholder = scanned_count == 0
    assets = _placeholder_assets(target_images) if used_placeholder else list(scanned_assets[:target_images])

    trials: list[ImageTrial] = []
    trial_idx = 1
    attention_probability = float(protocol_value(config, "attention_probability", 0.10))
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
                    attention_task_presented=(block_idx > 1 and rng.random() < attention_probability),
                )
            )
            trial_idx += 1

    metadata = {
        "task_mode": str(config.get("task_mode", "image_b")),
        "image_unique_count": len(assets),
        "requested_image_count": target_images,
        "scanned_image_count": scanned_count,
        "formal_trials": len(trials),
        "image_repeats": repeats,
        "random_seed": seed,
        "used_placeholder": used_placeholder,
        "image_library_dir": str(image_root(config, base_dir=base_dir)),
    }
    return trials, assets, metadata


def save_subject_image_set(path: Path, assets: list[ImageAsset], *, metadata: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(
            {"metadata": metadata, "assets": [asset.to_mapping() for asset in assets]},
            handle,
            ensure_ascii=False,
            indent=2,
        )
    return path


def load_subject_image_set(path: Path) -> list[ImageAsset]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        items = payload.get("assets") or payload.get("images") or []
    else:
        items = payload
    if not isinstance(items, list):
        raise RuntimeError(f"Invalid subject image set: {path}")
    return [ImageAsset.from_mapping(dict(item)) for item in items if isinstance(item, dict)]


def serialize_trials(trials: list[ImageTrial]) -> list[dict[str, Any]]:
    return [trial.to_mapping() for trial in trials]


def deserialize_trials(payload: list[Any]) -> list[ImageTrial]:
    return [ImageTrial.from_mapping(dict(item)) for item in payload]


def trial_base(
    config: dict[str, Any],
    trial: ImageTrial,
    *,
    eeg_session_dir: str | None = None,
) -> dict[str, Any]:
    return {
        "subject_id": config.get("subject_id"),
        "session_id": config.get("session_id"),
        "session_type": config.get("session_type"),
        "timestamp_label": config.get("timestamp_label"),
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
        "eeg_session_dir": eeg_session_dir,
    }


def make_rating_row(
    config: dict[str, Any],
    trial: ImageTrial,
    *,
    ratings: dict[str, int | None],
    item_timings: dict[str, dict[str, Any]],
    timed_out: bool,
    eeg_session_dir: str | None = None,
) -> dict[str, Any]:
    row = trial_base(config, trial, eeg_session_dir=eeg_session_dir)
    row.update(ratings)
    row.update({"rating_timed_out": timed_out, "rating_confirm_click": False})
    for dimension in RATING_DIMENSIONS:
        key = str(dimension["key"])
        timing = item_timings.get(key, {})
        row[f"{key}_onset"] = timing.get("onset")
        row[f"{key}_offset"] = timing.get("offset")
        row[f"{key}_rt_ms"] = timing.get("rt_ms")
        row[f"{key}_timed_out"] = bool(timing.get("timed_out", False))
        row[f"{key}_no_keypress"] = bool(timing.get("no_keypress", False))
    return row


def make_trial_log_row(
    config: dict[str, Any],
    trial: ImageTrial,
    *,
    extra: dict[str, Any] | None = None,
    eeg_session_dir: str | None = None,
) -> dict[str, Any]:
    row = trial_base(config, trial, eeg_session_dir=eeg_session_dir)
    row.update(
        {
            "attention_task_presented": trial.attention_task_presented,
            "attention_task_type": "has_person" if trial.attention_task_presented else "",
        }
    )
    if extra:
        row.update(extra)
    return row


def build_output_rows(
    rating_rows: list[dict[str, Any]],
    trial_rows: list[dict[str, Any]],
    events: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    ratings_with_events = _merge_event_fields(rating_rows, events)
    trials_with_events = _merge_event_fields(trial_rows, events)
    ratings_by_trial = {row.get("trial_idx"): row for row in ratings_with_events}
    rating_keys = rating_columns() + ["rating_confirm_click", "rating_timed_out", *rating_timing_columns()]

    enriched_trials: list[dict[str, Any]] = []
    for row in trials_with_events:
        out = dict(row)
        rating_row = ratings_by_trial.get(row.get("trial_idx"), {})
        for key in rating_keys:
            if key in rating_row:
                out[key] = rating_row[key]
        enriched_trials.append(out)
    return ratings_with_events, enriched_trials, ordered_trial_columns()


def write_rows_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    extra: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns and key not in extra:
                extra.append(key)
    fieldnames = columns + extra
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_playlist_json(path: Path, trials: list[ImageTrial]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(serialize_trials(trials), handle, ensure_ascii=False, indent=2)
    return path


def rating_columns() -> list[str]:
    return [str(dimension["key"]) for dimension in RATING_DIMENSIONS]


def rating_timing_columns() -> list[str]:
    columns: list[str] = []
    for dimension in RATING_DIMENSIONS:
        key = str(dimension["key"])
        columns.extend([f"{key}_onset", f"{key}_offset", f"{key}_rt_ms", f"{key}_timed_out", f"{key}_no_keypress"])
    return columns


def ordered_trial_columns() -> list[str]:
    return [
        "subject_id",
        "session_id",
        "session_type",
        "timestamp_label",
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
        *rating_timing_columns(),
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
        *rating_columns(),
        "eeg_session_dir",
    ]


def _load_manifest(root: Path) -> list[ImageAsset]:
    json_manifest = root / "manifest.json"
    if json_manifest.exists() and json_manifest.stat().st_size > 0:
        with json_manifest.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            payload = payload.get("images") or payload.get("items") or payload.get("assets") or []
        if isinstance(payload, list):
            return [ImageAsset.from_mapping(dict(item)) for item in payload if isinstance(item, dict)]

    csv_manifest = root / "manifest.csv"
    if not csv_manifest.exists() or csv_manifest.stat().st_size == 0:
        return []
    with csv_manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [_asset_from_csv_row(row, idx) for idx, row in enumerate(reader)]


def _asset_from_csv_row(row: dict[str, Any], idx: int) -> ImageAsset:
    rel_path = str(row.get("rel_path") or row.get("image_file") or row.get("file") or row.get("path") or "").strip()
    return ImageAsset(
        image_id=str(row.get("image_id") or row.get("id") or Path(rel_path).stem or f"image_{idx + 1:03d}"),
        rel_path=rel_path,
        category=str(row.get("emotion_category") or row.get("category") or "unknown"),
        split=str(row.get("split") or "train"),
        has_person=_coerce_optional_bool(row.get("has_person")),
    )


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


def _category_from_stem(stem: str) -> str:
    return stem.split("-", 1)[0] if "-" in stem else "unknown"


def _coerce_optional_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "t", "yes", "y", "1"}:
        return True
    if text in {"false", "f", "no", "n", "0"}:
        return False
    return None


def _event_trial_idx(event: Any) -> int | None:
    payload = getattr(event, "payload", {}) or {}
    value = payload.get("trial_idx")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _events_by_trial(events: list[Any]) -> dict[int, dict[str, Any]]:
    by_trial: dict[int, dict[str, Any]] = {}
    for event in events:
        trial_idx = _event_trial_idx(event)
        if trial_idx is None:
            continue
        row = by_trial.setdefault(trial_idx, {})
        name = str(getattr(event, "name", ""))
        payload = getattr(event, "payload", {}) or {}
        t = float(getattr(event, "relative_time_sec", 0.0))
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
            item = str(payload.get("item_key") or payload.get("item") or "")
            if item:
                row[f"{item}_onset"] = t
        elif name == "rating_item_off":
            item = str(payload.get("item_key") or payload.get("item") or "")
            if item:
                row[f"{item}_offset"] = t
                row[f"{item}_timed_out"] = bool(payload.get("timed_out", False))
                row[f"{item}_no_keypress"] = bool(payload.get("no_keypress", False))
        elif name == "attention_task_on":
            row["attention_task_onset"] = t
        elif name == "attention_response":
            row["attention_response_time"] = t
            row["attention_response"] = payload.get("response")
            row["attention_response_mode"] = payload.get("response_mode", row.get("attention_response_mode"))
            row["attention_timed_out"] = bool(payload.get("timed_out", False))
    return by_trial


def _merge_event_fields(rows: list[dict[str, Any]], events: list[Any]) -> list[dict[str, Any]]:
    event_rows = _events_by_trial(events)
    merged: list[dict[str, Any]] = []
    for row in rows:
        trial_idx = row.get("trial_idx")
        event_row = event_rows.get(int(trial_idx), {}) if trial_idx is not None else {}
        out = dict(row)
        out.update(event_row)
        if out.get("attention_task_onset") is not None and out.get("attention_response_time") is not None:
            out.setdefault(
                "reaction_time_ms",
                int((float(out["attention_response_time"]) - float(out["attention_task_onset"])) * 1000),
            )
        merged.append(out)
    return merged
