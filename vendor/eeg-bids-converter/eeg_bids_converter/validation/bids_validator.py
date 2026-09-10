from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..errors import ConverterError


def _parse_report(stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
    for text in (stdout, stderr):
        text = text.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return {"returncode": returncode, "stdout": stdout, "stderr": stderr}


def _counts(report: dict[str, Any]) -> tuple[int, int]:
    issues = report.get("issues", report)
    if not isinstance(issues, dict):
        return 0, 0
    combined = issues.get("issues")
    if isinstance(combined, list):
        errors = sum(str(item.get("severity", "")).lower() == "error" for item in combined)
        warnings = sum(str(item.get("severity", "")).lower() == "warning" for item in combined)
        return errors, warnings
    return len(issues.get("errors", []) or []), len(issues.get("warnings", []) or [])


def run_bids_validator(bids_root: Path, warnings_as_errors: bool = False) -> tuple[dict[str, Any], int, int]:
    scripts_dir = Path(sys.executable).resolve().parent
    local_candidates = [scripts_dir / "bids-validator-deno.exe", scripts_dir / "bids-validator-deno"]
    executable = next((str(path) for path in local_candidates if path.is_file()), None)
    executable = executable or shutil.which("bids-validator-deno") or shutil.which("bids-validator")
    if executable is None:
        raise ConverterError(
            "BIDS_VALIDATOR_NOT_FOUND",
            "Install the official bids-validator-deno executable or use --skip-validation",
        )
    commands = [
        [executable, str(bids_root), "--format", "json"],
        [executable, str(bids_root), "--json"],
        [executable, "--json", str(bids_root)],
    ]
    last: subprocess.CompletedProcess[str] | None = None
    for command in commands:
        last = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        report = _parse_report(last.stdout, last.stderr, last.returncode)
        if "issues" in report:
            break
    assert last is not None
    report_path = bids_root / "code" / "validation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    errors, warnings = _counts(report)
    if "issues" not in report or errors or (warnings_as_errors and warnings):
        raise ConverterError(
            "BIDS_VALIDATION_ERROR",
            f"Official validator failed: errors={errors}, warnings={warnings}, exit={last.returncode}",
        )
    return report, errors, warnings
