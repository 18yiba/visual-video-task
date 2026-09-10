"""Fixed video library: catalog, path resolution, and playlist building."""

from __future__ import annotations

import json
import random
import re
import struct
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

VideoLibraryMode = Literal["auto", "local", "manifest"]

MANIFEST_FILENAME = "manifest.json"
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}


@dataclass(slots=True)
class VideoAsset:
    """One entry in the fixed video library."""

    asset_id: str
    rel_path: str
    duration_sec: float | None = None
    category: str | None = None
    duration_status: str = "duration_unknown"

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> VideoAsset:
        asset_id = str(payload.get("id") or payload.get("asset_id") or payload.get("rel_path") or payload["file"])
        rel_path = str(payload.get("file") or payload.get("rel_path") or asset_id)
        duration = payload.get("duration_sec")
        category = payload.get("category") or _category_from_name(Path(rel_path).stem)
        return cls(
            asset_id=asset_id,
            rel_path=rel_path,
            duration_sec=None if duration is None else float(duration),
            category=None if category is None else str(category),
            duration_status=str(payload.get("duration_status") or ("valid" if duration is not None else "duration_unknown")),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "rel_path": self.rel_path,
            "duration_sec": self.duration_sec,
            "category": self.category,
            "video_file": self.rel_path,
            "duration_status": self.duration_status,
        }


@dataclass(slots=True)
class VideoLibrary:
    """Resolved video library rooted at a fixed directory."""

    root: Path
    mode: VideoLibraryMode
    default_duration_sec: float

    def resolve(self, asset: VideoAsset) -> Path:
        """Return the absolute path for a library asset."""

        return (self.root / asset.rel_path).resolve()

    def is_available(self, asset: VideoAsset) -> bool:
        """True when the media file exists on disk."""

        return self.resolve(asset).is_file()

    def playback_duration(self, asset: VideoAsset) -> float:
        """Duration used when the file cannot be probed at runtime."""

        if asset.duration_sec is not None and asset.duration_sec > 0:
            return asset.duration_sec
        return self.default_duration_sec

    def list_assets(self) -> list[VideoAsset]:
        """Load the full catalog from manifest and/or directory scan."""

        manifest_path = self.root / MANIFEST_FILENAME
        manifest = _read_manifest(manifest_path) if manifest_path.is_file() else {}

        if self.mode == "local":
            scanned = _scan_directory(self.root)
            if scanned:
                return scanned
            if manifest:
                return _assets_from_manifest(manifest, self.root)
            return []

        if self.mode == "manifest":
            if not manifest:
                raise FileNotFoundError(
                    f"Manifest mode requires `{manifest_path}`. "
                    f"Create a catalog file under the video library directory."
                )
            return _assets_from_manifest(manifest, self.root)

        # auto: prefer manifest catalog, fall back to directory scan
        if manifest:
            assets = _assets_from_manifest(manifest, self.root)
            if assets:
                return assets
        return _scan_directory(self.root)

    def list_candidate_assets(self) -> list[VideoAsset]:
        """Load candidate media files without probing every duration.

        This is used by the demo path so startup does not spend minutes running
        ffmpeg over a large stimulus library before only selecting 10 videos.
        """

        manifest_path = self.root / MANIFEST_FILENAME
        manifest = _read_manifest(manifest_path) if manifest_path.is_file() else {}
        if self.mode in {"manifest", "auto"} and manifest:
            return _assets_from_manifest(manifest, self.root)
        return _scan_directory(self.root, probe_durations=False)


def load_video_library(config: dict[str, Any]) -> VideoLibrary:
    """Build a library handle from experiment config."""

    protocol = dict(config.get("protocol", {}))
    root_value = protocol.get("video_library_dir") or protocol.get("video_dir") or "stimuli/videos"
    root = Path(str(root_value))
    if not root.is_absolute():
        base_dir = Path(str(config.get("_project_dir") or config.get("_config_dir") or Path.cwd()))
        root = (base_dir / root).resolve()
    if not _contains_video_files(root):
        base_dir = Path(str(config.get("_project_dir") or config.get("_config_dir") or Path.cwd()))
        # GitHub checkouts can keep their materials inside the project. Only
        # the standard deployment path receives this fallback, not custom paths.
        if str(root_value).replace('\\', '/') == '../video_materials/formal_v1/videos':
            project_materials = base_dir / 'stimuli' / 'videos'
            if _contains_video_files(project_materials):
                root = project_materials.resolve()
        legacy_root = (base_dir / "video_library").resolve()
        if root.name == "videos" and _contains_video_files(legacy_root):
            root = legacy_root

    mode_raw = str(protocol.get("video_library_mode", "local")).strip().lower()
    if mode_raw not in {"auto", "local", "manifest"}:
        raise ValueError(f"Unsupported video_library_mode: {mode_raw!r}")

    return VideoLibrary(
        root=root,
        mode=mode_raw,  # type: ignore[arg-type]
        default_duration_sec=float(protocol.get("default_video_sec", 60.0)),
    )


def _contains_video_files(root: Path) -> bool:
    return root.is_dir() and any(
        path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        for path in root.rglob("*")
    )


def build_playlist(
    library: VideoLibrary,
    *,
    trials_per_session: int,
    random_seed: int,
) -> list[VideoAsset]:
    """Shuffle library assets and return one session playlist."""

    catalog = library.list_assets()
    if not catalog:
        raise RuntimeError(
            f"Video library at `{library.root}` is empty. "
            f"Add `{MANIFEST_FILENAME}` or place media files in the library folder."
        )
    if len(catalog) < trials_per_session:
        raise RuntimeError(
            f"Video library has {len(catalog)} assets but session requires {trials_per_session}. "
            f"Expand `{library.root / MANIFEST_FILENAME}` or reduce trials_per_session."
        )

    rng = random.Random(random_seed)
    pool = list(catalog)
    rng.shuffle(pool)
    return pool[:trials_per_session]



def build_fast_candidate_playlist(
    library: VideoLibrary,
    *,
    trials_per_session: int,
    random_seed: int,
) -> list[VideoAsset]:
    """Build a random non-repeating playlist without probing durations first."""

    candidates = library.list_candidate_assets()
    if not candidates:
        raise RuntimeError(
            f"Video library at `{library.root}` is empty. "
            f"Place media files in the library folder."
        )

    rng = random.Random(random_seed)
    pool = list(candidates)
    rng.shuffle(pool)
    if trials_per_session <= 0:
        return pool
    if len(pool) < trials_per_session:
        raise RuntimeError(
            f"Video library has {len(pool)} assets but session requires {trials_per_session}."
        )
    return pool[:trials_per_session]

def build_fast_valid_playlist(
    library: VideoLibrary,
    *,
    trials_per_session: int,
    random_seed: int,
) -> tuple[list[VideoAsset], int]:
    """Randomly find valid videos while probing only as many files as needed."""

    candidates = library.list_candidate_assets()
    if not candidates:
        raise RuntimeError(
            f"Video library at `{library.root}` is empty. "
            f"Place media files in the library folder."
        )
    if len(candidates) < trials_per_session:
        raise RuntimeError(
            f"Video library has {len(candidates)} assets but session requires {trials_per_session}."
        )

    rng = random.Random(random_seed)
    pool = list(candidates)
    rng.shuffle(pool)
    selected: list[VideoAsset] = []
    probed = 0
    for asset in pool:
        duration_sec, duration_status_value = probe_video_duration(library.resolve(asset))
        probed += 1
        if duration_status_value != "valid":
            continue
        selected.append(
            VideoAsset(
                asset_id=asset.asset_id,
                rel_path=asset.rel_path,
                duration_sec=duration_sec,
                category=asset.category,
                duration_status=duration_status_value,
            )
        )
        if len(selected) >= trials_per_session:
            return selected, probed
    raise RuntimeError(
        f"Only found {len(selected)} valid videos after checking {probed} candidates; "
        f"need {trials_per_session}. Valid videos must be 5-60 seconds."
    )


def build_balanced_playlist(
    library: VideoLibrary,
    *,
    trials_per_session: int,
    random_seed: int,
    exclude: VideoAsset | None = None,
) -> list[VideoAsset]:
    """Build a category-balanced playlist from filenames like ``ID_分类名.mp4``."""

    catalog = _categorized_assets(library)
    if exclude is not None:
        catalog = [asset for asset in catalog if asset.rel_path != exclude.rel_path]

    grouped: dict[str, list[VideoAsset]] = defaultdict(list)
    for asset in catalog:
        assert asset.category is not None
        grouped[asset.category].append(asset)

    categories = sorted(grouped)
    if not categories:
        raise RuntimeError("No categorized videos found for balanced playlist generation.")
    if trials_per_session % len(categories) != 0:
        raise RuntimeError(
            f"Balanced playlist requires trial count divisible by category count: "
            f"{trials_per_session} trials, {len(categories)} categories."
        )

    target_per_category = trials_per_session // len(categories)
    rng = random.Random(random_seed)
    selected: list[VideoAsset] = []
    for category in categories:
        pool = list(grouped[category])
        if len(pool) < target_per_category:
            raise RuntimeError(
                f"Category `{category}` has {len(pool)} videos but requires {target_per_category}."
            )
        rng.shuffle(pool)
        selected.extend(pool[:target_per_category])

    rng.shuffle(selected)
    return selected


def choose_practice_asset(library: VideoLibrary, *, random_seed: int) -> VideoAsset:
    """Choose one categorized asset for the untimed practice trial."""

    catalog = _categorized_assets(library)
    if not catalog:
        raise RuntimeError("No categorized videos found for the practice trial.")
    return random.Random(random_seed).choice(catalog)


def serialize_playlist(playlist: list[VideoAsset]) -> list[dict[str, Any]]:
    return [asset.to_mapping() for asset in playlist]


def deserialize_playlist(payload: list[Any]) -> list[VideoAsset]:
    assets: list[VideoAsset] = []
    for item in payload:
        if isinstance(item, VideoAsset):
            assets.append(item)
        elif isinstance(item, dict):
            assets.append(VideoAsset.from_mapping(item))
        elif isinstance(item, str):
            # Legacy playlists stored bare filenames.
            assets.append(
                VideoAsset(
                    asset_id=item,
                    rel_path=item,
                    duration_sec=None,
                    category=_category_from_name(Path(item).stem),
                )
            )
        else:
            raise TypeError(f"Unsupported playlist entry type: {type(item)!r}")
    return assets


def category_counts(assets: list[VideoAsset]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for asset in assets:
        category = asset.category or "(未分类)"
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def _read_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest must be a JSON object: {path}")
    return payload


def _assets_from_manifest(manifest: dict[str, Any], root: Path) -> list[VideoAsset]:
    if isinstance(manifest.get("assets"), list):
        return [VideoAsset.from_mapping(item) for item in manifest["assets"] if isinstance(item, dict)]

    virtual = manifest.get("virtual")
    if isinstance(virtual, dict):
        return _assets_from_virtual_spec(virtual)

    raise ValueError(
        f"Manifest at `{root / MANIFEST_FILENAME}` must contain an `assets` list "
        f"or a `virtual` block for test catalogs."
    )


def _assets_from_virtual_spec(spec: dict[str, Any]) -> list[VideoAsset]:
    count = int(spec.get("count", 0))
    if count <= 0:
        raise ValueError("virtual.count must be a positive integer.")

    id_prefix = str(spec.get("id_prefix", "asset"))
    file_suffix = str(spec.get("file_suffix", ".mp4"))
    subdir = str(spec.get("subdir", "")).strip().strip("/\\")
    duration_sec = spec.get("duration_sec")
    parsed_duration = None if duration_sec is None else float(duration_sec)
    pad = int(spec.get("index_pad", 3))

    assets: list[VideoAsset] = []
    for index in range(count):
        token = f"{index + 1:0{pad}d}"
        asset_id = f"{id_prefix}_{token}"
        filename = f"{id_prefix}_{token}{file_suffix}"
        rel_path = f"{subdir}/{filename}" if subdir else filename
        assets.append(
            VideoAsset(
                asset_id=asset_id,
                rel_path=rel_path,
                duration_sec=parsed_duration,
            )
        )
    return assets


def _scan_directory(root: Path, *, probe_durations: bool = True) -> list[VideoAsset]:
    if not root.is_dir():
        return []

    assets: list[VideoAsset] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == MANIFEST_FILENAME:
            continue
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        rel_path = path.relative_to(root).as_posix()
        stem = path.stem
        if probe_durations:
            duration_sec, duration_status_value = probe_video_duration(path)
        else:
            duration_sec, duration_status_value = None, "duration_unknown"
        assets.append(
            VideoAsset(
                asset_id=stem,
                rel_path=rel_path,
                duration_sec=duration_sec,
                category=_category_from_name(stem),
                duration_status=duration_status_value,
            )
        )
    return assets


def probe_video_duration(path: Path) -> tuple[float | None, str]:
    """Read duration through PsychoPy's bundled ffpyplayer when available."""

    duration: float | None = None
    try:
        from ffpyplayer.player import MediaPlayer

        player = MediaPlayer(str(path), autoexit=True)
        metadata = player.get_metadata() or {}
        duration = metadata.get("duration")
        if duration is None:
            duration = getattr(player, "duration", None)
        close = getattr(player, "close_player", None)
        if callable(close):
            close()
        if duration is not None:
            duration = float(duration)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        duration = None
    if duration is None:
        try:
            from imageio_ffmpeg import get_ffmpeg_exe

            result = subprocess.run(
                [get_ffmpeg_exe(), "-i", str(path)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
            if match:
                hours, minutes, seconds = match.groups()
                duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except (ImportError, OSError, subprocess.SubprocessError, ValueError):
            duration = None
    if duration is None and path.suffix.lower() == ".mp4":
        duration = _probe_mp4_mvhd_duration(path)
    if duration is None:
        return None, "duration_unknown"
    seconds = duration
    return seconds, duration_status(seconds)


def _probe_mp4_mvhd_duration(path: Path) -> float | None:
    """Read the ISO-BMFF movie header without decoding or resampling media.

    This is a dependency-free fallback for lab installation/manifest creation
    when ffpyplayer and ffmpeg are unavailable.  It only reads container
    metadata and never changes the source video.
    """

    try:
        with path.open("rb") as handle:
            file_size = path.stat().st_size
            offset = 0
            while offset + 8 <= file_size:
                handle.seek(offset)
                header = handle.read(8)
                if len(header) != 8:
                    return None
                size, box_type = struct.unpack(">I4s", header)
                header_size = 8
                if size == 1:
                    extended = handle.read(8)
                    if len(extended) != 8:
                        return None
                    size = struct.unpack(">Q", extended)[0]
                    header_size = 16
                elif size == 0:
                    size = file_size - offset
                if size < header_size or offset + size > file_size:
                    return None
                if box_type == b"moov":
                    handle.seek(offset + header_size)
                    payload = handle.read(size - header_size)
                    result = _find_mp4_movie_header(payload)
                    if result is not None:
                        return result
                offset += size
    except (OSError, OverflowError, struct.error, ValueError):
        return None
    return None


def _find_mp4_movie_header(payload: bytes) -> float | None:
    offset = 0
    while offset + 8 <= len(payload):
        size, box_type = struct.unpack(">I4s", payload[offset : offset + 8])
        header_size = 8
        if size == 1:
            if offset + 16 > len(payload):
                return None
            size = struct.unpack(">Q", payload[offset + 8 : offset + 16])[0]
            header_size = 16
        elif size == 0:
            size = len(payload) - offset
        if size < header_size or offset + size > len(payload):
            return None
        if box_type == b"mvhd":
            body = payload[offset + header_size : offset + size]
            if len(body) < 20:
                return None
            version = body[0]
            if version == 1:
                if len(body) < 32:
                    return None
                timescale = struct.unpack(">I", body[20:24])[0]
                duration = struct.unpack(">Q", body[24:32])[0]
            else:
                timescale = struct.unpack(">I", body[12:16])[0]
                duration = struct.unpack(">I", body[16:20])[0]
            if timescale <= 0:
                return None
            return float(duration) / float(timescale)
        offset += size
    return None


def duration_status(seconds: float) -> str:
    if seconds < 5.0:
        return "invalid_short"
    if seconds > 60.0:
        return "invalid_long"
    return "valid"


def _category_from_name(stem: str) -> str | None:
    """Parse category from filenames following ``视频ID_分类名``."""

    if "_" not in stem:
        return None
    video_id, category = stem.split("_", 1)
    if not video_id.isdigit() or not category.strip():
        return None
    return category.strip()


def _categorized_assets(library: VideoLibrary) -> list[VideoAsset]:
    catalog = library.list_assets()
    if not catalog:
        raise RuntimeError(
            f"Video library at `{library.root}` is empty. "
            f"Place videos named like `100025_科技商业.mp4` in the library folder."
        )

    invalid = [asset.rel_path for asset in catalog if not asset.category]
    if invalid:
        examples = ", ".join(invalid[:5])
        raise RuntimeError(
            "All videos used for balanced sampling must be named `视频ID_分类名.ext`. "
            f"Invalid examples: {examples}"
        )
    return catalog

