"""Fixed video library: catalog, path resolution, and playlist building."""

from __future__ import annotations

import json
import random
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
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "rel_path": self.rel_path,
            "duration_sec": self.duration_sec,
            "category": self.category,
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


def load_video_library(config: dict[str, Any]) -> VideoLibrary:
    """Build a library handle from experiment config."""

    protocol = dict(config.get("protocol", {}))
    root_value = (
        protocol.get("video_library_dir")
        or protocol.get("video_dir")
        or "video_library/selected_540_balanced_videos"
    )
    root = Path(str(root_value))
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()

    mode_raw = str(protocol.get("video_library_mode", "local")).strip().lower()
    if mode_raw not in {"auto", "local", "manifest"}:
        raise ValueError(f"Unsupported video_library_mode: {mode_raw!r}")

    return VideoLibrary(
        root=root,
        mode=mode_raw,  # type: ignore[arg-type]
        default_duration_sec=float(protocol.get("default_video_sec", 8.0)),
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


def _scan_directory(root: Path) -> list[VideoAsset]:
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
        assets.append(
            VideoAsset(
                asset_id=stem,
                rel_path=rel_path,
                duration_sec=None,
                category=_category_from_name(stem),
            )
        )
    return assets


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
