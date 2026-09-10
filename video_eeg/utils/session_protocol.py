"""Pure video-EEG session planning and checkpoint primitives.

This module deliberately has no PsychoPy or EEG-device dependency.  It is the
single source for fixed session membership, duration-aware attention targets,
arithmetic questions, and atomic subject/session state persistence.
"""

from __future__ import annotations

import csv
import bisect
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import random
import time
from typing import Any, Iterable

from video_eeg.utils.video_library import MANIFEST_FILENAME, VideoAsset, VideoLibrary, probe_video_duration


SESSION_MANIFEST_VERSION = "video-eeg-session-manifest-v2-duration-diversity"
PARTITION_ALGORITHM_VERSION = "duration-bucket-round-robin-v1"
SPLIT_PARTITION_ALGORITHM_VERSION = "legacy-session-halves-duration-bucket-v1"
FORMAL_MAX_VIDEO_DURATION_SEC = 60.0
SESSION_STATE_VERSION = 1
SESSION_COUNT = 17
DEFAULT_DURATION_BUCKET_NAMES = ("very_short", "short", "medium", "long", "very_long")


@dataclass(frozen=True, slots=True)
class SessionManifestEntry:
    session_id: int
    video_id: str
    video_path: str
    video_duration_sec: float
    duration_bucket: str = ""

    def to_asset(self) -> VideoAsset:
        return VideoAsset(
            asset_id=self.video_id,
            rel_path=self.video_path,
            duration_sec=self.video_duration_sec,
            duration_status="valid",
        )


@dataclass(slots=True)
class SessionManifest:
    version: str
    entries: list[SessionManifestEntry]
    source_library: str = ""
    generated_at: str = ""
    source_video_count: int = 0
    excluded_video_count: int = 0
    partition_algorithm_version: str = PARTITION_ALGORITHM_VERSION
    duration_bucket_definition: list[dict[str, Any]] = field(default_factory=list)
    random_seed: int = 17

    def session_entries(self, session_id: int) -> list[SessionManifestEntry]:
        return [entry for entry in self.entries if entry.session_id == int(session_id)]

    def session_assets(self, session_id: int) -> list[VideoAsset]:
        return [entry.to_asset() for entry in self.session_entries(session_id)]

    def session_duration_sec(self, session_id: int) -> float:
        return sum(entry.video_duration_sec for entry in self.session_entries(session_id))

    @property
    def video_ids(self) -> list[str]:
        return [entry.video_id for entry in self.entries]

    @property
    def content_hash(self) -> str:
        canonical = [
            {
                "session_id": item.session_id,
                "video_id": item.video_id,
                "video_path": item.video_path,
                "video_duration_sec": item.video_duration_sec,
                "duration_bucket": item.duration_bucket,
            }
            for item in self.entries
        ]
        return hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def validate(self, *, session_count: int = SESSION_COUNT) -> None:
        if self.version != SESSION_MANIFEST_VERSION:
            raise ValueError(f"Unsupported session manifest version: {self.version!r}")
        expected = set(range(1, int(session_count) + 1))
        actual = {entry.session_id for entry in self.entries}
        if actual != expected:
            raise ValueError(f"Session manifest must contain sessions 1..{session_count}, got {sorted(actual)}")
        ids = [entry.video_id for entry in self.entries]
        paths = [entry.video_path for entry in self.entries]
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            raise ValueError("Session manifest contains duplicate video IDs or paths")
        if not self.entries:
            raise ValueError("Session manifest is empty")
        if any(not math.isfinite(item.video_duration_sec) or item.video_duration_sec <= 0 for item in self.entries):
            raise ValueError("Session manifest contains missing or invalid video durations")
        if any(item.video_duration_sec > FORMAL_MAX_VIDEO_DURATION_SEC + 1e-6 for item in self.entries):
            raise ValueError("Session manifest contains a video longer than the formal 60-second limit")
        if self.source_video_count and self.source_video_count != len(self.entries) + int(self.excluded_video_count):
            raise ValueError("Session manifest source/exclusion counts are inconsistent")
        if self.partition_algorithm_version not in {PARTITION_ALGORITHM_VERSION, SPLIT_PARTITION_ALGORITHM_VERSION}:
            raise ValueError(f"Unsupported partition algorithm: {self.partition_algorithm_version!r}")
        if self.duration_bucket_definition and any(not entry.duration_bucket for entry in self.entries):
            raise ValueError("Session manifest is missing duration bucket labels")
        if any(not self.session_entries(session_id) for session_id in expected):
            raise ValueError("Every session must contain at least one video")

    @classmethod
    def load(cls, path: Path, *, session_count: int = SESSION_COUNT) -> "SessionManifest":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"manifest_version", "session_id", "video_id", "video_path", "video_duration_sec"}
            if not required.issubset(set(reader.fieldnames or ())):
                raise ValueError(f"Session manifest is missing required columns: {sorted(required)}")
            first = None
            entries = [
                SessionManifestEntry(
                    session_id=int(row["session_id"]),
                    video_id=str(row["video_id"]),
                    video_path=str(row["video_path"]),
                    video_duration_sec=float(row["video_duration_sec"]),
                    duration_bucket=str(row.get("duration_bucket") or ""),
                )
                for row in reader
            ]
        # Read the small header metadata separately; every generated row carries
        # the same version so a normal CSV reader remains interoperable.
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            first = next(csv.DictReader(handle), None)
        version = str((first or {}).get("manifest_version") or "")
        bucket_definition: list[dict[str, Any]] = []
        if (first or {}).get("duration_bucket_definition"):
            try:
                bucket_definition = json.loads(str(first["duration_bucket_definition"]))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Invalid duration_bucket_definition in session manifest") from exc
        manifest = cls(
            version=version,
            entries=entries,
            source_library=str((first or {}).get("source_library") or ""),
            generated_at=str((first or {}).get("generated_at") or ""),
            source_video_count=int((first or {}).get("source_video_count") or 0),
            excluded_video_count=int((first or {}).get("excluded_video_count") or 0),
            partition_algorithm_version=str((first or {}).get("partition_algorithm_version") or ""),
            duration_bucket_definition=bucket_definition,
            random_seed=int((first or {}).get("random_seed") or 17),
        )
        manifest.validate(session_count=session_count)
        return manifest

    def write_atomic(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(path.name + ".tmp")
        fields = [
            "manifest_version", "generated_at", "source_library", "source_video_count",
            "excluded_video_count", "partition_algorithm_version", "duration_bucket_definition",
            "random_seed", "session_id", "video_id", "video_path", "video_duration_sec", "duration_bucket",
        ]
        with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for entry in self.entries:
                writer.writerow(
                    {
                        "manifest_version": self.version,
                        "generated_at": self.generated_at,
                        "source_library": self.source_library,
                        "source_video_count": self.source_video_count,
                        "excluded_video_count": self.excluded_video_count,
                        "partition_algorithm_version": self.partition_algorithm_version,
                        "duration_bucket_definition": json.dumps(self.duration_bucket_definition, ensure_ascii=False, separators=(",", ":")),
                        "random_seed": self.random_seed,
                        "session_id": entry.session_id,
                        "video_id": entry.video_id,
                        "video_path": entry.video_path,
                        "video_duration_sec": f"{entry.video_duration_sec:.6f}",
                        "duration_bucket": entry.duration_bucket,
                    }
                )
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
        return path


def catalog_with_durations(library: VideoLibrary) -> tuple[list[VideoAsset], list[str]]:
    """Load the formal catalog and probe missing durations without resampling."""

    assets: list[VideoAsset]
    source_manifest = library.root / MANIFEST_FILENAME
    if source_manifest.is_file():
        with source_manifest.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        raw_assets = payload.get("assets") if isinstance(payload, dict) else None
        if isinstance(raw_assets, list):
            assets = [VideoAsset.from_mapping(item) for item in raw_assets if isinstance(item, dict)]
        else:
            assets = library.list_assets()
    else:
        assets = library.list_assets()

    warnings: list[str] = []
    enriched: list[VideoAsset] = []
    for asset in assets:
        duration = asset.duration_sec
        status = asset.duration_status
        if duration is None or duration <= 0:
            duration, status = probe_video_duration(library.resolve(asset))
        if duration is None or duration <= 0:
            warnings.append(f"duration unavailable: {asset.rel_path}")
            continue
        enriched.append(
            VideoAsset(
                asset_id=asset.asset_id,
                rel_path=asset.rel_path,
                duration_sec=float(duration),
                category=asset.category,
                duration_status=status,
            )
        )
    return enriched, warnings


def split_formal_duration_exclusions(
    assets: Iterable[VideoAsset],
    *,
    maximum_duration_sec: float = FORMAL_MAX_VIDEO_DURATION_SEC,
) -> tuple[list[VideoAsset], list[VideoAsset]]:
    """Separate formal-eligible assets from the legacy >60-second exclusions."""

    eligible: list[VideoAsset] = []
    excluded: list[VideoAsset] = []
    for asset in assets:
        if asset.duration_sec is None or float(asset.duration_sec) <= 0:
            continue
        if float(asset.duration_sec) > float(maximum_duration_sec) + 1e-6:
            excluded.append(asset)
        else:
            eligible.append(asset)
    return eligible, excluded


def build_duration_bucket_assignments(
    assets: Iterable[VideoAsset], *, bucket_count: int = 5
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Assign deterministic rank-quantile duration buckets.

    Rank quantiles remain well-defined when many videos share the same exact
    duration; the persisted cut points are descriptive while rank_start/end
    are the authoritative definition used for reproducibility.
    """

    catalog = list(assets)
    if bucket_count < 1:
        raise ValueError("bucket_count must be positive")
    ordered = sorted(catalog, key=lambda item: (float(item.duration_sec or 0.0), item.asset_id, item.rel_path))
    names = list(DEFAULT_DURATION_BUCKET_NAMES) if bucket_count == 5 else [f"bucket_{index + 1}" for index in range(bucket_count)]
    assignments: dict[str, str] = {}
    definitions: list[dict[str, Any]] = []
    for bucket_index, name in enumerate(names):
        start = len(ordered) * bucket_index // bucket_count
        end = len(ordered) * (bucket_index + 1) // bucket_count
        members = ordered[start:end]
        for asset in members:
            assignments[asset.asset_id] = name
        durations = [float(item.duration_sec or 0.0) for item in members]
        definitions.append({
            "name": name,
            "rank_start": start,
            "rank_end_exclusive": end,
            "quantile_start": bucket_index / bucket_count,
            "quantile_end": (bucket_index + 1) / bucket_count,
            "lower_duration_sec": min(durations) if durations else None,
            "upper_duration_sec": max(durations) if durations else None,
        })
    if len(assignments) != len(catalog):
        raise ValueError("Duration bucket assignment did not cover every unique asset")
    return assignments, definitions


def build_duration_balanced_manifest(
    assets: Iterable[VideoAsset],
    *,
    session_count: int = SESSION_COUNT,
    random_seed: int = 17,
    source_library: str = "",
    source_video_count: int | None = None,
    excluded_video_count: int = 0,
    maximum_duration_sec: float = FORMAL_MAX_VIDEO_DURATION_SEC,
    bucket_count: int = 5,
) -> SessionManifest:
    """Assign each asset once using duration and duration-bucket balancing."""

    catalog = list(assets)
    if len(catalog) < int(session_count):
        raise ValueError(f"Need at least {session_count} videos to make sessions; got {len(catalog)}")
    if any(asset.duration_sec is None or asset.duration_sec <= 0 for asset in catalog):
        raise ValueError("All videos need a positive real duration before partitioning")
    if any(float(asset.duration_sec or 0.0) > float(maximum_duration_sec) + 1e-6 for asset in catalog):
        raise ValueError("Formal partition cannot contain videos longer than 60 seconds")
    if len({asset.asset_id for asset in catalog}) != len(catalog):
        raise ValueError("Video IDs must be unique before partitioning")
    bucket_by_id, bucket_definitions = build_duration_bucket_assignments(catalog, bucket_count=bucket_count)
    rng = random.Random(int(random_seed))
    stable_catalog = sorted(catalog, key=lambda asset: (asset.asset_id, asset.rel_path))
    tie_order = {asset.asset_id: index for index, asset in enumerate(rng.sample(stable_catalog, len(stable_catalog)))}
    grouped: dict[str, list[VideoAsset]] = {definition["name"]: [] for definition in bucket_definitions}
    for asset in catalog:
        grouped[bucket_by_id[asset.asset_id]].append(asset)
    insufficient = {
        bucket_name: len(members)
        for bucket_name, members in grouped.items()
        if len(members) < int(session_count)
    }
    if insufficient:
        raise ValueError(
            "Each duration bucket needs at least one video per session; "
            f"insufficient buckets: {insufficient}"
        )
    bins: list[list[VideoAsset]] = [[] for _ in range(int(session_count))]
    totals = [0.0 for _ in bins]
    bucket_counts = [{name: 0 for name in grouped} for _ in bins]
    for bucket_name in grouped:
        members = sorted(grouped[bucket_name], key=lambda asset: (-float(asset.duration_sec or 0.0), tie_order[asset.asset_id]))
        for asset in members:
            target = min(
                range(len(bins)),
                key=lambda index: (bucket_counts[index][bucket_name], totals[index], index),
            )
            bins[target].append(asset)
            totals[target] += float(asset.duration_sec or 0.0)
            bucket_counts[target][bucket_name] += 1

    entries: list[SessionManifestEntry] = []
    for session_id, bucket in enumerate(bins, start=1):
        for asset in sorted(bucket, key=lambda item: (item.asset_id, item.rel_path)):
            entries.append(
                SessionManifestEntry(
                    session_id=session_id,
                    video_id=asset.asset_id,
                    video_path=asset.rel_path,
                    video_duration_sec=float(asset.duration_sec or 0.0),
                    duration_bucket=bucket_by_id[asset.asset_id],
                )
            )
    manifest = SessionManifest(
        version=SESSION_MANIFEST_VERSION,
        entries=entries,
        source_library=str(source_library),
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        source_video_count=int(source_video_count if source_video_count is not None else len(catalog) + int(excluded_video_count)),
        excluded_video_count=int(excluded_video_count),
        partition_algorithm_version=PARTITION_ALGORITHM_VERSION,
        duration_bucket_definition=bucket_definitions,
        random_seed=int(random_seed),
    )
    manifest.validate(session_count=session_count)
    return manifest


def split_manifest_sessions(manifest: SessionManifest, *, random_seed: int = 20260910) -> SessionManifest:
    """Split each legacy Session into two duration-diverse balanced halves.

    Membership across legacy Sessions is preserved. Playback order is separately
    randomized and checkpointed by SessionState.new, never by CSV row order.
    """
    session_ids = sorted({e.session_id for e in manifest.entries})
    manifest.validate(session_count=len(session_ids))
    rng = random.Random(random_seed)
    entries = []
    bucket_names = [b['name'] for b in manifest.duration_bucket_definition]
    if not bucket_names:
        raise ValueError('Splitting requires the original duration bucket definitions')
    for old_id in session_ids:
        totals = [0.0, 0.0]
        for name in bucket_names:
            members = [e for e in manifest.session_entries(old_id) if e.duration_bucket == name]
            if len(members) < 2:
                raise ValueError(f'Legacy Session {old_id} cannot supply both halves with {name} videos')
            rng.shuffle(members)
            members.sort(key=lambda e: e.video_duration_sec, reverse=True)
            counts = [0, 0]
            for entry in members:
                target = min(range(2), key=lambda i: (counts[i], totals[i], i))
                entries.append(SessionManifestEntry(old_id * 2 - 1 + target, entry.video_id,
                    entry.video_path, entry.video_duration_sec, entry.duration_bucket))
                counts[target] += 1
                totals[target] += entry.video_duration_sec
    result = SessionManifest(version=manifest.version,
        entries=sorted(entries, key=lambda e: (e.session_id, e.video_id)),
        source_library=manifest.source_library,
        generated_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        source_video_count=manifest.source_video_count, excluded_video_count=manifest.excluded_video_count,
        partition_algorithm_version=SPLIT_PARTITION_ALGORITHM_VERSION,
        duration_bucket_definition=manifest.duration_bucket_definition, random_seed=random_seed)
    result.validate(session_count=len(session_ids) * 2)
    return result


@dataclass(frozen=True, slots=True)
class AttentionCheckpoint:
    attention_id: int
    scheduled_net_time_sec: float
    after_video_number: int

    def to_mapping(self) -> dict[str, Any]:
        return {
            "attention_id": self.attention_id,
            "scheduled_net_time_sec": self.scheduled_net_time_sec,
            "after_video_number": self.after_video_number,
        }


def build_attention_schedule(
    assets: Iterable[VideoAsset],
    *,
    task_count: int = 18,
    random_seed: int = 17,
) -> list[AttentionCheckpoint]:
    """Create fixed, duration-aware boundary checkpoints for one session."""

    items = list(assets)
    if task_count < 0 or task_count > max(len(items) - 1, 0):
        raise ValueError("task_count must fit strictly inside the session video boundaries")
    total = sum(float(item.duration_sec or 0.0) for item in items)
    if task_count == 0:
        return []
    if total <= 0:
        raise ValueError("Attention schedule requires positive session duration")
    rng = random.Random(int(random_seed))
    cumulative: list[float] = []
    running = 0.0
    for item in items:
        running += float(item.duration_sec or 0.0)
        cumulative.append(running)
    checkpoints: list[AttentionCheckpoint] = []
    used_boundaries: set[int] = set()
    interval = total / (task_count + 1)
    for attention_id in range(1, task_count + 1):
        # Keep one checkpoint near each evenly spaced location, with bounded
        # jitter so adjacent checkpoints cannot cross.  The seed is persisted
        # through SessionState, making resume deterministic without making all
        # subjects/sessions share the same schedule.
        target = interval * (attention_id + rng.uniform(-0.30, 0.30))
        if attention_id == 1 and len(items) > task_count + 1:
            # A real session has ample video boundaries.  Do not make the
            # first attention task mechanically follow video 1.
            target = max(target, cumulative[0] + 1e-6)
        boundary = min(len(items) - 1, max(1, bisect.bisect_left(cumulative, target) + 1))
        while boundary in used_boundaries and boundary < len(items) - 1:
            boundary += 1
        used_boundaries.add(boundary)
        checkpoints.append(
            AttentionCheckpoint(
                attention_id=attention_id,
                scheduled_net_time_sec=target,
                after_video_number=boundary,
            )
        )
    return checkpoints


def make_arithmetic_question(attention_id: int, *, random_seed: int = 17) -> dict[str, Any]:
    """Generate a persisted 0..100 addition/subtraction truth statement."""

    rng = random.Random(int(random_seed) + int(attention_id) * 9176)
    operator = "+" if rng.random() < 0.5 else "-"
    if operator == "+":
        operand_a = rng.randint(0, 100)
        operand_b = rng.randint(0, 100 - operand_a)
        true_result = operand_a + operand_b
    else:
        operand_a = rng.randint(0, 100)
        operand_b = rng.randint(0, operand_a)
        true_result = operand_a - operand_b
    statement_truth = int(attention_id) % 2 == 0
    if statement_truth:
        displayed_result = true_result
    else:
        candidates = [delta for delta in (-3, -2, -1, 1, 2, 3) if 0 <= true_result + delta <= 100]
        displayed_result = true_result + (rng.choice(candidates) if candidates else (1 if true_result == 0 else -1))
    question = f"判断：{operand_a} {operator} {operand_b} = {displayed_result} 是否正确？"
    return {
        "question_text": question,
        "operator": operator,
        "operand_a": operand_a,
        "operand_b": operand_b,
        "true_result": true_result,
        "displayed_result": displayed_result,
        "statement_truth": statement_truth,
    }


def build_video_question_schedule(assets, questions, *, task_count=18, random_seed=17):
    """Select distinct eligible videos across the shuffled session; persist bindings."""
    candidates = []
    elapsed = 0.0
    for number, asset in enumerate(assets, 1):
        elapsed += float(asset.duration_sec or 0.0)
        if asset.rel_path in questions:
            candidates.append((number, elapsed, asset))
    if task_count < 0 or len(candidates) < task_count:
        raise ValueError(f'Session needs {task_count} video questions, only {len(candidates)} eligible videos')
    rng = random.Random(random_seed)
    schedule = []
    for index in range(task_count):
        # One random video per ordered stratum prevents duplicate questions and
        # spreads the checks over the session, including sparse question banks.
        start = len(candidates) * index // task_count
        end = len(candidates) * (index + 1) // task_count
        number, elapsed, asset = rng.choice(candidates[start:end])
        q = questions[asset.rel_path]
        schedule.append(dict(attention_id=index + 1, task_type='video_mcq',
                             after_video_number=number, scheduled_net_time_sec=elapsed,
                             video_id=asset.asset_id, video_file=asset.rel_path,
                             question_text=q['question'], options=dict(q['options']),
                             correct_answer=q['answer']))
    return schedule


def choose_rest_threshold_minutes(rng: random.Random, minimum: int = 30, maximum: int = 45) -> int:
    minimum, maximum = int(minimum), int(maximum)
    if minimum < 0 or maximum < minimum:
        raise ValueError("rest threshold range is invalid")
    return rng.randint(minimum, maximum)


def choose_rest_threshold_seconds(rng: random.Random, minimum_minutes: float, maximum_minutes: float) -> float:
    if minimum_minutes < 0 or maximum_minutes < minimum_minutes:
        raise ValueError("rest threshold range is invalid")
    if float(minimum_minutes).is_integer() and float(maximum_minutes).is_integer() and minimum_minutes >= 1:
        return float(choose_rest_threshold_minutes(rng, int(minimum_minutes), int(maximum_minutes)) * 60)
    return rng.uniform(float(minimum_minutes) * 60.0, float(maximum_minutes) * 60.0)


@dataclass(slots=True)
class SessionState:
    subject_id: str
    session_id: int
    manifest_version: str
    manifest_hash: str
    video_ids: list[str]
    queue_video_ids: list[str]
    attention_task_type: str = "arithmetic"
    question_bank_sha256: str = ""
    question_bank_sha256: str = ""
    completed_video_ids: list[str] = field(default_factory=list)
    current_video_id: str | None = None
    random_seed: int = 17
    queue_seed: int = 17
    completed_net_video_duration_sec: float = 0.0
    continuous_net_video_duration_sec: float = 0.0
    next_rest_threshold_min: float = 30.0
    attention_schedule: list[dict[str, Any]] = field(default_factory=list)
    completed_attention_ids: list[int] = field(default_factory=list)
    attention_attempts: list[dict[str, Any]] = field(default_factory=list)
    video_attempts: list[dict[str, Any]] = field(default_factory=list)
    rest_events: list[dict[str, Any]] = field(default_factory=list)
    rest_index: int = 0
    session_start_timestamp: str | None = None
    latest_resume_timestamp: str | None = None
    last_exit_reason: str = "new"
    session_completed: bool = False
    updated_at: float = 0.0

    @property
    def remaining_video_ids(self) -> list[str]:
        completed = set(self.completed_video_ids)
        return [video_id for video_id in self.video_ids if video_id not in completed]

    @property
    def completed_attention_count(self) -> int:
        return len(set(self.completed_attention_ids))

    def commit_completed_video(self, video_id: str, duration_sec: float) -> None:
        """Commit completion only after a natural EOF."""

        video_id = str(video_id)
        self.queue_video_ids = [item for item in self.queue_video_ids if item != video_id]
        if video_id not in self.completed_video_ids:
            self.completed_video_ids.append(video_id)
            self.completed_net_video_duration_sec += float(duration_sec)
            self.continuous_net_video_duration_sec += float(duration_sec)
        self.current_video_id = None

    def requeue_skipped_video(self, video_id: str) -> None:
        """S interrupts an attempt but leaves the video in remaining."""

        video_id = str(video_id)
        self.queue_video_ids = [item for item in self.queue_video_ids if item != video_id]
        if video_id not in self.completed_video_ids:
            self.queue_video_ids.append(video_id)
        self.current_video_id = None

    def preserve_aborted_video(self, video_id: str) -> None:
        """Keep an interrupted video at the head for deterministic resume."""

        video_id = str(video_id)
        self.queue_video_ids = [item for item in self.queue_video_ids if item != video_id]
        if video_id not in self.completed_video_ids:
            self.queue_video_ids.insert(0, video_id)
        self.current_video_id = video_id

    def to_mapping(self) -> dict[str, Any]:
        payload = {"state_version": SESSION_STATE_VERSION}
        payload.update({name: getattr(self, name) for name in self.__dataclass_fields__})
        payload["remaining_video_ids"] = self.remaining_video_ids
        payload["completed_attention_count"] = self.completed_attention_count
        return payload

    @classmethod
    def new(
        cls,
        *,
        subject_id: str,
        session_id: int,
        manifest: SessionManifest,
        assets: list[VideoAsset],
        random_seed: int,
        attention_task_count: int,
        rest_min_minutes: float,
        rest_max_minutes: float,
        demo_mode: bool = False,
        questions: dict | None = None,
    ) -> "SessionState":
        subject_seed = sum((index + 1) * ord(char) for index, char in enumerate(str(subject_id)))
        queue_seed = int(random_seed) + int(session_id) * 1009 + (0 if demo_mode else subject_seed)
        queue = [asset.asset_id for asset in assets]
        rng = random.Random(queue_seed)
        rng.shuffle(queue)
        asset_by_id = {asset.asset_id: asset for asset in assets}
        ordered_assets = [asset_by_id[video_id] for video_id in queue]
        attention_seed = int(random_seed) + int(session_id) * 7919 + (0 if demo_mode else subject_seed * 31)
        schedule = [
            {**item.to_mapping(), **make_arithmetic_question(item.attention_id, random_seed=attention_seed)}
            for item in build_attention_schedule(ordered_assets, task_count=attention_task_count if questions is None else 0, random_seed=attention_seed)
        ]
        if questions is not None:
            schedule = build_video_question_schedule(ordered_assets, questions,
                task_count=attention_task_count, random_seed=attention_seed)
        threshold_sec = choose_rest_threshold_seconds(rng, rest_min_minutes, rest_max_minutes)
        return cls(
            subject_id=str(subject_id),
            session_id=int(session_id),
            manifest_version=manifest.version,
            manifest_hash=manifest.content_hash,
            video_ids=[asset.asset_id for asset in assets],
            queue_video_ids=queue,
            attention_task_type='video_mcq' if questions is not None else 'arithmetic',
            random_seed=int(random_seed),
            queue_seed=queue_seed,
            next_rest_threshold_min=threshold_sec / 60.0,
            attention_schedule=schedule,
            session_start_timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            latest_resume_timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            last_exit_reason="new",
            updated_at=time.time(),
        )

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "SessionState":
        if int(payload.get("state_version", 0)) not in {0, SESSION_STATE_VERSION}:
            raise ValueError(f"Unsupported session state version: {payload.get('state_version')}")
        fields = {name for name in cls.__dataclass_fields__}
        values = {name: payload[name] for name in fields if name in payload}
        state = cls(**values)
        state.video_ids = [str(item) for item in state.video_ids]
        state.queue_video_ids = [str(item) for item in state.queue_video_ids]
        state.completed_video_ids = [str(item) for item in state.completed_video_ids]
        state.completed_attention_ids = [int(item) for item in state.completed_attention_ids]
        known = set(state.video_ids)
        if not set(state.completed_video_ids).issubset(known) or not set(state.queue_video_ids).issubset(known):
            raise ValueError("Session state contains a video not present in its manifest")
        missing = [item for item in state.video_ids if item not in state.completed_video_ids and item not in state.queue_video_ids]
        state.queue_video_ids.extend(missing)
        return state


def session_state_path(records_dir: Path, subject_id: str, session_id: int) -> Path:
    return Path(records_dir) / str(subject_id) / f"session_{int(session_id):02d}" / "session_state.json"


def load_state(path: Path) -> SessionState | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return SessionState.from_mapping(json.load(handle))


def save_state_atomic(path: Path, state: SessionState, *, last_exit_reason: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if last_exit_reason is not None:
        state.last_exit_reason = str(last_exit_reason)
    state.updated_at = time.time()
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        json.dump(state.to_mapping(), handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temp_path.replace(path)
    return path


def duration_progress(completed_sec: float, assigned_sec: float) -> float:
    if assigned_sec <= 0:
        return 0.0
    return max(0.0, min(100.0, float(completed_sec) / float(assigned_sec) * 100.0))
