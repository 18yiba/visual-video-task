"""Read-only validation shared by doctor, deployment tools and integration tests."""
from collections import Counter
from pathlib import Path

from .session_protocol import SessionManifest
from .video_library import VIDEO_EXTENSIONS


def inspect_session_files(manifest: SessionManifest, root: Path) -> dict:
    root = root.resolve()
    manifest.validate(session_count=17)
    paths = [entry.video_path for entry in manifest.entries]
    missing = [p for p in paths if not (root / p).is_file()]
    duplicates = [p for p, count in Counter(paths).items() if count > 1]
    physical = {p.relative_to(root).as_posix() for p in root.rglob('*')
                if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS}
    views = []
    for sid in range(1, 18):
        folder = root.parent / f'session_{sid:02d}'
        expected = {Path(e.video_path).name for e in manifest.session_entries(sid)}
        actual = {p.name for p in folder.iterdir()} if folder.is_dir() else set()
        valid = actual == expected and all(
            (folder / Path(e.video_path).name).is_file()
            and (root / e.video_path).is_file()
            and (folder / Path(e.video_path).name).samefile(root / e.video_path)
            for e in manifest.session_entries(sid)
        )
        views.append(valid)
    return dict(video_root=str(root), assigned=len(paths), sessions=17,
                missing=missing, duplicate_assignments=duplicates,
                physical_count=len(physical), unassigned=sorted(physical - set(paths)),
                valid_session_folders=sum(views))
