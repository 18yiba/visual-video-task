from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bids import BIDSLayout

from ..errors import ConverterError


def build_dataset_index(bids_root: Path) -> dict[str, Any]:
    try:
        layout = BIDSLayout(bids_root, validate=True)
        subjects = layout.get_subjects()
        sessions = layout.get_sessions()
        tasks = layout.get_tasks()
        runs = layout.get_runs()
        eeg = layout.get(datatype="eeg", suffix="eeg", extension=[".vhdr", ".edf", ".set", ".bdf"])
        events = layout.get(suffix="events", extension=".tsv")
        behavior = layout.get(datatype="beh", suffix="beh", extension=".tsv")
    except Exception as exc:
        raise ConverterError("PYBIDS_INDEX_ERROR", str(exc)) from exc
    index = {
        "subjects": len(subjects),
        "sessions": len(sessions),
        "tasks": len(tasks),
        "runs": len(runs),
        "eeg_recordings": len(eeg),
        "events_files": len(events),
        "behavior_files": len(behavior),
        "subject_labels": subjects,
        "session_labels": sessions,
        "task_labels": tasks,
    }
    index_path = bids_root / "code" / "dataset_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return index
