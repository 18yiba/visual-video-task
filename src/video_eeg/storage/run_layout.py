"""Naming and collision-safe reservation for date-numbered acquisition runs."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re


def reserve_run(session_dir: Path, *, now: datetime | None = None) -> Path:
    """Reserve a new run below the existing fixed Session without touching old runs."""
    session_dir = Path(session_dir)
    if not session_dir.is_dir():
        raise FileNotFoundError(f'Fixed Session directory does not exist: {session_dir}')
    date = (now or datetime.now()).strftime('%y%m%d')
    for number in range(1, 100):
        candidate = session_dir / f'run-{date}{number:02d}'
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f'No available run number for {date} in {session_dir}')


def file_prefix(subject: str, session: int, task: str, run: int) -> str:
    """Build a safe, unambiguous file prefix; identities are never normalized."""
    if not re.fullmatch(r'[A-Za-z0-9]+', subject):
        raise ValueError('Subject ID must contain only ASCII letters and digits for the new layout')
    if not re.fullmatch(r'[A-Za-z0-9]+', task):
        raise ValueError('Task name must contain only ASCII letters and digits')
    if type(session) is not int or session < 1 or type(run) is not int or not 1 <= run <= 99:
        raise ValueError('Session and run must be positive integers; run must be at most 99')
    return f'sub-{subject}_ses-{session:02d}_task-{task}_run-{run:02d}'


def resolve_run(session_dir: Path, run_name: str) -> Path:
    """Resolve only an explicitly named run within the current fixed Session."""
    if not re.fullmatch(r'run-\d{8}', run_name):
        raise ValueError('Invalid dated run name')
    root = Path(session_dir).resolve()
    candidate = root / run_name
    if candidate.is_symlink() or candidate.resolve().parent != root:
        raise ValueError('Run path is a link or escapes the fixed Session')
    return candidate
