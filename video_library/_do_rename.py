"""One-shot rename: video files -> stim_001.ext, stim_002.ext, ..."""
from __future__ import annotations

import os
import re
from pathlib import Path

LIB = Path(__file__).resolve().parent
VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
SKIP = {"manifest.json", "README.md", "_rename.cmd", "_rename_stim.ps1", "_do_rename.py"}
STIM_RE = re.compile(r"^stim_(\d{3})(\.\w+)$", re.IGNORECASE)


def is_video(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in VIDEO_EXT and p.name not in SKIP


def already_stim(p: Path) -> bool:
    return bool(STIM_RE.match(p.name))


def main() -> None:
    all_files = sorted(os.listdir(LIB))
    print("=== ALL FILES ===")
    for name in all_files:
        print(name)

    videos = sorted(
        (LIB / n for n in all_files if is_video(LIB / n)),
        key=lambda p: p.name.lower(),
    )

    print(f"\n=== VIDEO COUNT: {len(videos)} ===")
    for v in videos:
        print(v.name)

    mapping: list[tuple[str, str]] = []

    if not videos:
        print("\n=== NO VIDEO FILES FOUND ===")
        return

    need_rename = [v for v in videos if not already_stim(v)]
    if not need_rename:
        print("\n=== NO RENAME NEEDED (all already stim_XXX) ===")
        for v in videos:
            mapping.append((v.name, v.name))
    else:
        # Phase 1: temp names to avoid collisions
        temps: list[tuple[Path, str, str]] = []
        for i, src in enumerate(need_rename, start=1):
            ext = src.suffix.lower()
            tmp = f"__tmp_{i:03d}{ext}"
            src.rename(LIB / tmp)
            temps.append((src, tmp, ext))

        # Phase 2: final stim names (keep original extension)
        for i, (src, tmp, ext) in enumerate(temps, start=1):
            new_name = f"stim_{i:03d}{ext}"
            (LIB / tmp).rename(LIB / new_name)
            mapping.append((src.name, new_name))

        # Already-correct stim files: report as skipped
        for v in videos:
            if already_stim(v) and v.name not in {m[1] for m in mapping}:
                mapping.append((v.name, v.name))

        mapping.sort(key=lambda x: x[1].lower())
        print("\n=== RENAME APPLIED ===")

    print("\n=== AFTER ===")
    for name in sorted(os.listdir(LIB)):
        print(name)

    print("\n=== MAPPING (before -> after) ===")
    if mapping:
        for old, new in mapping:
            tag = " (skipped)" if old == new else ""
            print(f"{old} -> {new}{tag}")
    else:
        print("(none)")


if __name__ == "__main__":
    main()
