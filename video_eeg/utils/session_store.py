"""Persist experiment session state across browser popup windows."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DEFAULT_SESSION_PATH = Path("records_storage/.experiment_session.json")


def session_path(config: dict[str, Any]) -> Path:
    records_dir = Path(str(config.get("storage", {}).get("records_dir", "records_storage")))
    return records_dir / ".experiment_session.json"


def load(config: dict[str, Any]) -> dict[str, Any]:
    path = session_path(config)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save(config: dict[str, Any], payload: dict[str, Any]) -> Path:
    path = session_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    data["updated_at"] = time.time()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    return path


def clear(config: dict[str, Any]) -> None:
    path = session_path(config)
    if path.exists():
        path.unlink()


def reset_for_popup(
    config: dict[str, Any],
    playlist: list[Any],
    *,
    practice_asset: Any | None = None,
    playlist_seed: int | None = None,
    playlist_metadata: dict[str, Any] | None = None,
) -> None:
    """Reset persisted state so each popup open starts a fresh session."""

    payload = {
        "playlist": playlist,
        "practice_asset": practice_asset,
        "playlist_seed": playlist_seed,
        "playlist_metadata": playlist_metadata or {},
        "current_trial": 0,
        "results": [],
        "experiment_state": "instructions",
        "practice_completed": False,
        "baseline_done": False,
        "eeg_session_dir": None,
        "phase_log": [],
        "popup_open": True,
    }
    save(config, payload)
