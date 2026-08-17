"""Local server for the jsPsych Image B behavioral rating session."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import random
import re
import shutil
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

WEB_DIR = Path(__file__).resolve().parent
PROJECT_DIR = WEB_DIR.parent
DIST_DIR = WEB_DIR / "dist"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tasks.image_core import (  # noqa: E402
    FORMAL_500_PROTOCOL,
    PILOT_105_PROTOCOL,
    RATING_DIMENSIONS,
    build_output_rows,
    build_session_playlist,
    default_image_set_label,
    make_rating_row,
    make_trial_log_row,
    ordered_trial_columns,
    protocol_value,
    serialize_trials,
    write_playlist_json,
    write_rows_csv,
)

SUBJECT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
SESSION_LOCK = threading.RLock()
SESSIONS: dict[str, dict[str, Any]] = {}


def load_config() -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    with (PROJECT_DIR / "config.yaml").open("r", encoding="utf-8-sig") as handle:
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
                parent[key.strip()] = parse_scalar(value)
    return root


def parse_scalar(value: str) -> Any:
    text = value.strip()
    if text in {"''", '""'}:
        return ""
    if (
        (text.startswith("'") and text.endswith("'"))
        or (text.startswith('"') and text.endswith('"'))
    ):
        return text[1:-1]
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text


def normalize_image_set_label(value: str | None) -> str:
    label = str(value or "default").strip() or "default"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", label):
        raise ValueError("图片集标签只能包含字母、数字、下划线或连字符。")
    return label


def unique_timestamp_label(
    records_dir: Path,
    *,
    subject_id: str,
    session_id: int,
    image_set_label: str,
) -> str:
    base = (
        f"{datetime.now():%Y%m%d_%H%M%S}_"
        f"{normalize_image_set_label(image_set_label)}"
    )
    candidate = base
    suffix = 2
    while (
        records_dir
        / subject_id
        / candidate
        / f"session_{int(session_id):02d}"
    ).exists():
        candidate = f"{base}_{suffix:02d}"
        suffix += 1
    return candidate


def find_resume_state(
    records_dir: Path,
    *,
    subject_id: str,
    session_id: int,
    trials: list[Any],
    image_set_label: str,
) -> dict[str, Any] | None:
    subject_root = records_dir / subject_id
    if not subject_root.exists() or not trials:
        return None
    expected = {trial.trial_idx: trial.asset.image_id for trial in trials}
    candidates = [
        *subject_root.rglob(".resume_manifest.json"),
        *subject_root.rglob("metadata.json"),
    ]
    visited: set[Path] = set()
    for metadata_path in sorted(
        candidates,
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ):
        session_dir = metadata_path.parent
        if session_dir in visited:
            continue
        visited.add(session_dir)
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if (
            str(metadata.get("task_mode", "")).lower() != "image_b"
            or normalize_image_set_label(
                str(metadata.get("image_set_label", "default"))
            )
            != image_set_label
            or int(metadata.get("session_id", -1)) != int(session_id)
            or bool(metadata.get("completed", False))
            or int(metadata.get("image_trials", len(trials))) != len(trials)
        ):
            continue
        rating_rows = read_rows(session_dir / "behavioral_ratings.csv")
        trial_rows = read_rows(session_dir / "trial_log.csv") or rating_rows
        by_index: dict[int, dict[str, Any]] = {}
        compatible = True
        for row in trial_rows:
            try:
                trial_idx = int(row.get("trial_idx", 0))
            except (TypeError, ValueError):
                compatible = False
                break
            if expected.get(trial_idx) != str(row.get("image_id", "")):
                compatible = False
                break
            by_index[trial_idx] = row
        if not compatible:
            continue
        completed = 0
        while completed + 1 in by_index:
            completed += 1
        if completed >= len(trials):
            continue
        return {
            "source_dir": session_dir,
            "completed_trial": completed,
            "next_trial": completed + 1,
            "timestamp_label": metadata.get("timestamp_label")
            or session_dir.parent.name,
        }
    return None


def write_subject_completion_status(
    records_dir: Path,
    *,
    subject_id: str,
    image_set_label: str,
    image_ids: list[str],
) -> Path:
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
        if (
            not bool(metadata.get("completed", False))
            or normalize_image_set_label(
                str(metadata.get("image_set_label", "default"))
            )
            != image_set_label
        ):
            continue
        session = int(metadata.get("session_id", -1))
        if session == 1 and str(metadata.get("session_type", "")) == "labeling":
            for row in read_rows(metadata_path.parent / "behavioral_ratings.csv"):
                image_id = str(row.get("image_id", ""))
                if image_id in status and all(
                    row.get(str(item["key"])) not in {None, ""}
                    for item in RATING_DIMENSIONS
                ):
                    status[image_id]["rating_completed"] = True
        elif session in {2, 3, 4, 5, 6}:
            for row in read_rows(metadata_path.parent / "trial_log.csv"):
                image_id = str(row.get("image_id", ""))
                marker_ok = str(
                    row.get("image_marker_send_success", "")
                ).strip().lower()
                if (
                    image_id in status
                    and row.get("image_onset") not in {None, ""}
                    and marker_ok in {"true", "1"}
                    and session not in status[image_id]["eeg_sessions"]
                ):
                    status[image_id]["eeg_sessions"].append(session)
    for item in status.values():
        item["eeg_sessions"].sort()
        item["eeg_view_count"] = len(item["eeg_sessions"])
        item["complete"] = bool(
            item["rating_completed"]
            and item["eeg_sessions"] == [2, 3, 4, 5, 6]
        )
    payload = {
        "subject_id": subject_id,
        "image_set_label": image_set_label,
        "required_rating_count_per_image": 1,
        "required_eeg_sessions": [2, 3, 4, 5, 6],
        "image_count": len(status),
        "images_with_rating": sum(
            bool(item["rating_completed"]) for item in status.values()
        ),
        "images_with_five_eeg_views": sum(
            item["eeg_sessions"] == [2, 3, 4, 5, 6]
            for item in status.values()
        ),
        "fully_complete_images": sum(
            bool(item["complete"]) for item in status.values()
        ),
        "images": status,
    }
    output = subject_root / f"subject_completion_status_{image_set_label}.json"
    temporary = output.with_name(f".{output.name}.{int(time.time() * 1_000_000)}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, output)
    return output


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def replace_trial_row(rows: list[dict[str, Any]], row: dict[str, Any]) -> list[dict[str, Any]]:
    trial_idx = int(row["trial_idx"])
    retained = [item for item in rows if int(item.get("trial_idx", 0)) != trial_idx]
    retained.append(row)
    return sorted(retained, key=lambda item: int(item["trial_idx"]))


def event_objects(payload: list[dict[str, Any]]) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            name=str(item.get("name", "")),
            relative_time_sec=float(item.get("relative_time_sec", 0.0)),
            payload=dict(item.get("payload") or {}),
        )
        for item in payload
    ]


def make_metadata(context: dict[str, Any], *, completed: bool) -> dict[str, Any]:
    config = context["config"]
    playlist = context["playlist_metadata"]
    return {
        "subject_id": config["subject_id"],
        "session_id": 1,
        "session_type": "labeling",
        "task_mode": "image_b",
        "collection_phase": "behavior_rating",
        "experiment_protocol": config["experiment_protocol"],
        "timestamp_label": config["timestamp_label"],
        "image_set_label": config["image_set_label"],
        "image_trials": len(context["trials"]),
        "image_unique_count": len(context["assets"]),
        "playlist_seed": playlist["random_seed"],
        "playlist_metadata": playlist,
        "subject_image_set_path": playlist["subject_image_set_path"],
        "jspsych_runner": True,
        "psychopy_runner": False,
        "eeg_recording_mode": "none",
        "device_type": "none",
        "external_markers_sent": False,
        "completed": completed,
        "termination_reason": context.get("termination_reason", "running"),
    }


def prepare_durations(
    config: dict[str, Any],
    trials: list[Any],
    *,
    resumed: bool,
) -> list[dict[str, Any]]:
    seed = int(protocol_value(config, "random_seed", 17)) + 1
    rng = random.Random(seed)
    if not resumed:
        rng.uniform(
            float(protocol_value(config, "image_present_min_sec", 1.0)),
            float(protocol_value(config, "image_present_max_sec", 1.5)),
        )

    def jitter(prefix: str, minimum: float, maximum: float) -> float:
        lower = float(protocol_value(config, f"{prefix}_min_sec", minimum))
        upper = float(protocol_value(config, f"{prefix}_max_sec", maximum))
        return max(0.0, lower) if upper <= lower else rng.uniform(lower, upper)

    prepared: list[dict[str, Any]] = []
    protocol = str(config["experiment_protocol"])
    for trial in trials:
        item = trial.to_mapping()
        item["image_url"] = f"/images/{protocol}/{trial.asset.rel_path}"
        item["fixation_sec"] = jitter("image_fixation", 0.5, 0.8)
        item["image_sec"] = jitter("image_present", 2.0, 3.0)
        item["blank_sec"] = float(protocol_value(config, "image_blank_sec", 0.5))
        item["iti_sec"] = jitter("image_rating_iti", 1.0, 1.5)
        prepared.append(item)
    return prepared


def start_session(payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    subject_id = str(payload.get("subject_id", "")).strip()
    if not SUBJECT_PATTERN.fullmatch(subject_id):
        raise ValueError("被试编号只能包含英文字母、数字、下划线和连字符。")
    configured_protocol = str(config.get("experiment_protocol", FORMAL_500_PROTOCOL))
    requested_protocol = str(payload.get("experiment_protocol") or configured_protocol)
    if bool(config.get("experiment_config_locked", True)):
        requested_protocol = configured_protocol
    if requested_protocol not in {FORMAL_500_PROTOCOL, PILOT_105_PROTOCOL}:
        raise ValueError("实验协议必须是 formal500 或 pilot105。")
    max_trials = max(0, int(payload.get("max_trials", 0)))
    config.update(
        {
            "subject_id": subject_id,
            "experiment_protocol": requested_protocol,
            "session_id": 1,
            "session_type": "labeling",
            "task_mode": "image_b",
            "collection_phase": "behavior_rating",
            "device_type": "none",
            "hardware_dummy_mode": False,
            "image_set_label": str(
                config.get("image_set_label")
                or default_image_set_label(requested_protocol)
            ),
        }
    )
    config["image_set_label"] = normalize_image_set_label(config["image_set_label"])
    records_dir = PROJECT_DIR / Path(
        str(config.get("storage", {}).get("records_dir", "records_storage"))
    )
    trials, assets, playlist_metadata = build_session_playlist(
        config,
        subject_id=subject_id,
        session_id=1,
        records_dir=records_dir,
        base_dir=PROJECT_DIR,
        image_count=max_trials or None,
    )
    resume = find_resume_state(
        records_dir,
        subject_id=subject_id,
        session_id=1,
        trials=trials,
        image_set_label=config["image_set_label"],
    )
    if resume:
        output_dir = Path(resume["source_dir"]).resolve()
        config["timestamp_label"] = str(resume["timestamp_label"])
        next_trial = int(resume["next_trial"])
    else:
        config["timestamp_label"] = unique_timestamp_label(
            records_dir,
            subject_id=subject_id,
            session_id=1,
            image_set_label=config["image_set_label"],
        )
        output_dir = (
            records_dir
            / subject_id
            / config["timestamp_label"]
            / "session_01"
        ).resolve()
        output_dir.mkdir(parents=True, exist_ok=False)
        next_trial = 1
    pending = [trial for trial in trials if trial.trial_idx >= next_trial]
    token = uuid4().hex
    context = {
        "token": token,
        "config": config,
        "trials": trials,
        "assets": assets,
        "playlist_metadata": playlist_metadata,
        "output_dir": output_dir,
        "termination_reason": "running",
    }
    SESSIONS[token] = context
    write_playlist_json(output_dir / "image_playlist.json", trials)
    atomic_json(output_dir / "metadata.json", make_metadata(context, completed=False))
    atomic_json(
        output_dir / ".resume_manifest.json",
        {
            **make_metadata(context, completed=False),
            "next_trial": next_trial,
        },
    )
    block_break = float(
        protocol_value(config, "image_rating_block_break_min_sec", 60.0)
    )
    return {
        "token": token,
        "subject_id": subject_id,
        "experiment_protocol": requested_protocol,
        "image_set_label": config["image_set_label"],
        "output_dir": str(output_dir),
        "resume": bool(resume),
        "next_trial": next_trial,
        "total_trials": len(trials),
        "block_size": int(playlist_metadata["block_size"]),
        "block_count": int(playlist_metadata["block_count"]),
        "block_break_sec": block_break,
        "trials": prepare_durations(config, pending, resumed=bool(resume)),
    }


def checkpoint(payload: dict[str, Any]) -> dict[str, Any]:
    token = str(payload.get("token", ""))
    context = SESSIONS.get(token)
    if context is None:
        raise ValueError("Session 已失效，请刷新页面后按断点恢复。")
    trial_idx = int(payload["trial_idx"])
    trial = next(
        (item for item in context["trials"] if item.trial_idx == trial_idx),
        None,
    )
    if trial is None:
        raise ValueError(f"未知 trial：{trial_idx}")
    ratings = {
        str(dimension["key"]): int(payload["ratings"][str(dimension["key"])])
        for dimension in RATING_DIMENSIONS
    }
    item_timings = {
        str(key): dict(value)
        for key, value in dict(payload.get("item_timings") or {}).items()
    }
    rating_row = make_rating_row(
        context["config"],
        trial,
        ratings=ratings,
        item_timings=item_timings,
        timed_out=False,
    )
    rating_row["rating_onset"] = payload.get("rating_onset")
    rating_row["rating_offset"] = payload.get("rating_offset")
    trial_row = make_trial_log_row(context["config"], trial)
    raw_events = [dict(item) for item in payload.get("events") or []]
    enriched_rating, enriched_trial, _ = build_output_rows(
        [rating_row],
        [trial_row],
        event_objects(raw_events),
    )
    output_dir = context["output_dir"]
    ratings = replace_trial_row(
        read_rows(output_dir / "behavioral_ratings.csv"),
        enriched_rating[0],
    )
    trials = replace_trial_row(
        read_rows(output_dir / "trial_log.csv"),
        enriched_trial[0],
    )
    write_rows_csv(
        output_dir / "behavioral_ratings.csv",
        ratings,
        list(enriched_rating[0].keys()),
    )
    write_rows_csv(
        output_dir / "trial_log.csv",
        trials,
        ordered_trial_columns(),
    )
    events_path = output_dir / "events.json"
    existing_events: list[dict[str, Any]] = []
    if events_path.exists():
        existing_events = json.loads(events_path.read_text(encoding="utf-8"))
    existing_events = [
        item
        for item in existing_events
        if int(dict(item.get("payload") or {}).get("trial_idx", -1)) != trial_idx
    ]
    existing_events.extend(raw_events)
    atomic_json(events_path, existing_events)
    atomic_json(
        output_dir / ".resume_manifest.json",
        {
            **make_metadata(context, completed=False),
            "next_trial": trial_idx + 1,
        },
    )
    return {"saved": True, "trial_idx": trial_idx}


def finish_session(payload: dict[str, Any]) -> dict[str, Any]:
    token = str(payload.get("token", ""))
    context = SESSIONS.get(token)
    if context is None:
        raise ValueError("Session 已失效。")
    output_dir = context["output_dir"]
    completed_rows = read_rows(output_dir / "trial_log.csv")
    if len(completed_rows) != len(context["trials"]):
        raise ValueError(
            f"保存行数不完整：{len(completed_rows)}/{len(context['trials'])}"
        )
    final_events = [dict(item) for item in payload.get("events") or []]
    if final_events:
        events_path = output_dir / "events.json"
        existing_events: list[dict[str, Any]] = []
        if events_path.exists():
            existing_events = json.loads(events_path.read_text(encoding="utf-8"))
        existing_events.extend(final_events)
        atomic_json(events_path, existing_events)
    context["termination_reason"] = "completed"
    atomic_json(output_dir / "metadata.json", make_metadata(context, completed=True))
    (output_dir / ".resume_manifest.json").unlink(missing_ok=True)
    write_subject_completion_status(
        PROJECT_DIR / Path(
            str(context["config"].get("storage", {}).get("records_dir", "records_storage"))
        ),
        subject_id=str(context["config"]["subject_id"]),
        image_set_label=str(context["config"]["image_set_label"]),
        image_ids=[asset.image_id for asset in context["assets"]],
    )
    SESSIONS.pop(token, None)
    return {"completed": True, "output_dir": str(output_dir)}


def abort_session(payload: dict[str, Any]) -> dict[str, Any]:
    token = str(payload.get("token", ""))
    context = SESSIONS.get(token)
    if context is None:
        return {"aborted": True}
    context["termination_reason"] = "operator_abort"
    atomic_json(
        context["output_dir"] / "metadata.json",
        make_metadata(context, completed=False),
    )
    SESSIONS.pop(token, None)
    return {"aborted": True}


class RatingHandler(SimpleHTTPRequestHandler):
    server_version = "RatingWeb/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[rating-web] {format % args}")

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 10_000_000:
            raise ValueError("请求正文为空或过大。")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求必须是 JSON 对象。")
        return payload

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            config = load_config()
            protocol = str(config.get("experiment_protocol", FORMAL_500_PROTOCOL))
            self.send_json(
                {
                    "subject_id": str(config.get("subject_id", "S001")),
                    "experiment_protocol": protocol,
                    "image_set_label": str(
                        config.get("image_set_label")
                        or default_image_set_label(protocol)
                    ),
                    "experiment_config_locked": bool(
                        config.get("experiment_config_locked", True)
                    ),
                }
            )
            return
        if parsed.path.startswith("/images/"):
            self.serve_image(parsed.path)
            return
        super().do_GET()

    def do_POST(self) -> None:
        routes = {
            "/api/start": start_session,
            "/api/checkpoint": checkpoint,
            "/api/finish": finish_session,
            "/api/abort": abort_session,
        }
        handler = routes.get(urlparse(self.path).path)
        if handler is None:
            self.send_json({"error": "接口不存在。"}, HTTPStatus.NOT_FOUND)
            return
        try:
            with SESSION_LOCK:
                result = handler(self.read_json())
            self.send_json(result)
        except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json(
                {"error": f"{type(exc).__name__}: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def serve_image(self, request_path: str) -> None:
        parts = unquote(request_path).split("/", 3)
        if len(parts) != 4 or parts[2] not in {
            FORMAL_500_PROTOCOL,
            PILOT_105_PROTOCOL,
        }:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        folder = "formal" if parts[2] == FORMAL_500_PROTOCOL else "pilot"
        root = (PROJECT_DIR / "image_library" / folder).resolve()
        target = (root / parts[3]).resolve()
        if root not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        with target.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)


def check() -> int:
    config = load_config()
    if not DIST_DIR.joinpath("index.html").exists():
        raise RuntimeError("缺少 dist/index.html，请先运行 npm run build。")
    protocol = str(config.get("experiment_protocol", FORMAL_500_PROTOCOL))
    folder = "formal" if protocol == FORMAL_500_PROTOCOL else "pilot"
    manifest = PROJECT_DIR / "image_library" / folder / "manifest.json"
    if not manifest.exists():
        raise RuntimeError(f"缺少图片清单：{manifest}")
    print("rating_web check: OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Image B jsPsych 行为评分 Web 服务。")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check()
    if not DIST_DIR.joinpath("index.html").exists():
        parser.error("缺少 dist/index.html，请先在 rating_web 中运行 npm run build。")
    server = ThreadingHTTPServer((args.host, args.port), RatingHandler)
    print(f"Image B rating web: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
