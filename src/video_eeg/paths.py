"""Canonical source paths and resolution for persisted legacy resource paths."""
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent if PACKAGE_ROOT.parent.name == 'src' else PACKAGE_ROOT.parent
CONFIG_DIR = PACKAGE_ROOT / 'config'


def resolve_project_path(value, *, project_root: Path | None = None) -> Path:
    """Resolve a saved project-relative path, including the old config prefix.

    Protocol YAML and session snapshots retain ``video_eeg/config/...`` strings
    for compatibility. The files now live under ``src/video_eeg/config``.
    Older external projects with the original path continue to resolve first.
    """
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path.resolve()
    root = Path(project_root or PROJECT_ROOT).resolve()
    candidate = (root / path).resolve()
    if candidate.exists():
        return candidate
    prefix = ('video_eeg', 'config')
    if path.parts[:2] == prefix:
        migrated = root / 'src' / 'video_eeg' / 'config'
        if root == PROJECT_ROOT or migrated.exists():
            return (migrated.joinpath(*path.parts[2:])).resolve()
    return candidate
