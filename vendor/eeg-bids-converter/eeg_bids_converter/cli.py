from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from colorama import Fore, Style, just_fix_windows_console

from .adapters import NumpyEEGAdapter
from .bids import BIDSWriter
from .config import ConverterConfig, load_config
from .conversion import sync_stimuli
from .conversion.events import build_events
from .discovery import discover_records
from .errors import ConverterError
from .models import RecordingRecord
from .provenance import Manifest
from .validation import build_dataset_index, run_bids_validator


LOG = logging.getLogger("eeg_bids_converter")
USE_COLOR = False


class _LevelColorFormatter(logging.Formatter):
    COLORS = {
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        color = self.COLORS.get(record.levelno)
        return f"{color}{message}{Style.RESET_ALL}" if USE_COLOR and color else message


def _emit(label: str, message: str, color: str = "") -> None:
    prefix = f"[{label}]"
    if USE_COLOR and color:
        prefix = f"{color}{prefix}{Style.RESET_ALL}"
    print(f"{prefix} {message}")


def _normalize_subject(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits.zfill(3)


def _normalize_selector(value: str) -> str:
    return value.strip().replace("\\", "/").strip("/").lower()


def _source_session_selectors(record: RecordingRecord) -> set[str]:
    values: set[str] = {
        record.session,
        f"ses-{record.session}",
        record.timestamp_label,
        record.source_record_id,
        record.source_path.name,
        record.source_path.parent.name,
        f"{record.source_path.parent.name}/{record.source_path.name}",
    }
    if record.source_session_id is not None:
        raw = str(record.source_session_id)
        values.update({raw, f"session_{raw}", f"session-{raw}"})
        if raw.isdigit():
            values.update({raw.zfill(2), f"session_{raw.zfill(2)}", f"session-{raw.zfill(2)}"})
    for key in ("session_stamp", "timestamp_label"):
        if record.metadata.get(key):
            values.add(str(record.metadata[key]))
    return {_normalize_selector(value) for value in values if value}


def _filter_records(records: list[RecordingRecord], args: argparse.Namespace) -> list[RecordingRecord]:
    result = records
    if args.subject:
        subjects = {_normalize_subject(value) for value in args.subject}
        result = [record for record in result if record.subject in subjects]
    if args.task:
        tasks = {value.removeprefix("task-") for value in args.task}
        result = [record for record in result if record.task in tasks]
    if args.session:
        sessions = {_normalize_selector(value) for value in args.session}
        result = [record for record in result if sessions & _source_session_selectors(record)]
    if getattr(args, "eeg_only", False):
        result = [record for record in result if record.has_eeg]
    return result


def _check_entity_collisions(records: list[RecordingRecord]) -> None:
    seen: dict[tuple[str, str, str], str] = {}
    for record in records:
        key = record.subject, record.session, record.task
        previous = seen.get(key)
        if previous is not None and previous != record.source_record_id:
            raise ConverterError(
                "BIDS_ENTITY_COLLISION",
                f"{previous!r} and {record.source_record_id!r} both map to sub-{key[0]} ses-{key[1]} task-{key[2]}",
            )
        seen[key] = record.source_record_id


def _print_warning_summary(records: list[RecordingRecord]) -> None:
    warning_counts = Counter(
        warning.split(":", 1)[0]
        for record in records
        for warning in record.warnings
    )
    for code, count in sorted(warning_counts.items()):
        _emit("WARNING", f"{code}: {count} recording(s)", Fore.YELLOW)


def _print_scan(
    records: list[RecordingRecord],
    errors: list[ConverterError],
    statuses: Counter[str],
    show_mapping: bool,
) -> None:
    print(f"Found recordings: {len(records)}")
    print(f"Subjects: {len({record.subject for record in records})}")
    print(f"Tasks: {len({record.task for record in records})}")
    print(f"Sessions: {len({(record.subject, record.session) for record in records})}")
    print(f"EEG recordings: {sum(record.has_eeg for record in records)}")
    print(f"Behavior-only recordings: {sum(not record.has_eeg for record in records)}")
    for name in ("READY", "READY_INCOMPLETE", "WARNING", "ERROR"):
        print(f"{name}: {statuses[name]}")
    _print_warning_summary(records)
    for error in errors:
        _emit("ERROR", str(error), Fore.RED)
    if errors:
        _emit("FAILED", f"Source validation failed with {len(errors)} error(s)", Fore.RED)
    else:
        _emit("PASS", "Source validation passed", Fore.GREEN)
    if show_mapping:
        print("\nMAPPING PREVIEW")
        for record in records:
            flags = ",".join(record.warnings) or "READY"
            modality = "eeg" if record.has_eeg else "beh"
            print(
                f"  {record.source_record_id} -> "
                f"sub-{record.subject}/ses-{record.session}/{modality}/"
                f"sub-{record.subject}_ses-{record.session}_task-{record.task}_{modality} [{flags}]"
            )


def _scan_and_validate(
    source: Path,
    cfg: ConverterConfig,
    args: argparse.Namespace,
) -> tuple[list[RecordingRecord], NumpyEEGAdapter, list[ConverterError], Counter[str]]:
    summary = discover_records(source, cfg)
    records = _filter_records(summary.records, args)
    errors = list(summary.errors)
    statuses: Counter[str] = Counter()
    if not records:
        errors.append(
            ConverterError(
                "NO_RECORDINGS_MATCHED",
                "No source recordings matched the supplied source/subject/task/session selectors",
            )
        )
        statuses["ERROR"] += 1
        return records, NumpyEEGAdapter(source, cfg), errors, statuses
    try:
        _check_entity_collisions(records)
    except ConverterError as exc:
        errors.append(exc)
    adapter = NumpyEEGAdapter(source, cfg)
    valid_records: list[RecordingRecord] = []
    for record in records:
        try:
            if record.has_eeg:
                adapter.validate(record)
                build_events(record, adapter.profile(record), cfg)
            elif record.trial_log is None:
                raise ConverterError("MISSING_BEHAVIOR", "No EEG or trial log", record.source_record_id)
            if record.is_incomplete:
                statuses["READY_INCOMPLETE"] += 1
            elif record.warnings:
                statuses["WARNING"] += 1
            else:
                statuses["READY"] += 1
            valid_records.append(record)
        except ConverterError as exc:
            statuses["ERROR"] += 1
            errors.append(exc)
            if args.strict:
                break
    return valid_records, adapter, errors, statuses


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eeg-bids-converter")
    parser.add_argument("--source", type=Path, required=True, help="Source dataset root")
    parser.add_argument("--output", type=Path, help="BIDS output root; required unless --dry-run")
    parser.add_argument("--config", type=Path, help="YAML configuration")
    parser.add_argument("--dry-run", action="store_true", help="Scan and validate source without writing")
    parser.add_argument("--strict", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--eeg-only", action="store_true", help="Convert only recordings that contain EEG")
    parser.add_argument(
        "--replace-stimuli",
        action="store_true",
        help="Explicitly replace same-name stimuli whose SHA256 has changed",
    )
    parser.add_argument(
        "--prune-stimuli",
        action="store_true",
        help="Delete unreferenced managed image/video files; cannot be combined with record selectors",
    )
    parser.add_argument("--subject", action="append", help="Filter subject; repeatable")
    parser.add_argument("--task", action="append", help="Filter task; repeatable")
    parser.add_argument(
        "--session",
        action="append",
        help="Filter by source session name, timestamp folder, or source record ID; repeatable",
    )
    parser.add_argument("--show-mapping", action="store_true", help="Print every source-to-BIDS mapping")
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--warnings-as-errors", action="store_true")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="WARNING")
    parser.add_argument("--no-color", action="store_true", help="Disable colored terminal status labels")
    return parser


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    cfg.strict = args.strict
    if args.prune_stimuli and any((args.subject, args.task, args.session)):
        raise ConverterError(
            "INVALID_OPTIONS",
            "--prune-stimuli cannot be combined with --subject, --task, or --session",
        )
    records, adapter, errors, statuses = _scan_and_validate(args.source, cfg, args)
    if args.dry_run:
        _print_scan(records, errors, statuses, args.show_mapping)
        if errors or (args.warnings_as_errors and any(record.warnings for record in records)):
            return 1
        return 0
    if args.output is None:
        raise ConverterError("OUTPUT_REQUIRED", "--output is required unless --dry-run")
    if args.prune_stimuli and errors:
        _print_scan(records, errors, statuses, args.show_mapping)
        _emit("FAILED", "Stimuli pruning requires a source scan with no errors", Fore.RED)
        return 1
    if errors and args.strict:
        _print_scan(records, errors, statuses, args.show_mapping)
        return 1
    _emit(
        "SCAN",
        f"{len(records)} recording(s), {len({record.subject for record in records})} subject(s), "
        f"EEG={sum(record.has_eeg for record in records)}, behavior-only={sum(not record.has_eeg for record in records)}",
    )
    _print_warning_summary(records)
    writer = BIDSWriter(args.output, cfg, adapter)
    writer.initialize_dataset()
    writer.update_participants(records)
    stimuli_results, stimuli_summary = sync_stimuli(
        records,
        writer.root,
        replace=args.replace_stimuli,
        prune=args.prune_stimuli,
    )
    _emit(
        "STIMULI",
        f"files={stimuli_summary.files}, copied={stimuli_summary.copied}, "
        f"replaced={stimuli_summary.replaced}, pruned={stimuli_summary.pruned}, SHA256=verified",
        Fore.GREEN,
    )
    manifest = Manifest(writer.root)
    successful = manifest.successful_ids()
    conversion_errors: list[ConverterError] = []
    converted_count = 0
    skipped_count = 0
    for record in records:
        if record.source_record_id in successful and not args.overwrite:
            LOG.info("SKIP source_record_id=%s already converted", record.source_record_id)
            skipped_count += 1
            continue
        LOG.info("CONVERT source_record_id=%s", record.source_record_id)
        try:
            stimuli_count, stimuli_hash = stimuli_results[record.source_record_id]
            target, profile = writer.write_record(record, overwrite=args.overwrite)
            status = "INCOMPLETE_SUCCESS" if record.is_incomplete else "SUCCESS"
            manifest.upsert(record, target, profile, stimuli_count, stimuli_hash, status)
            converted_count += 1
            LOG.info("DONE source_record_id=%s target=%s", record.source_record_id, target)
        except ConverterError as exc:
            conversion_errors.append(exc)
            LOG.error("%s", exc)
            manifest.upsert(record, None, None, 0, "", "ERROR", "NOT_RUN")
            if args.strict:
                break
    if conversion_errors:
        _emit("FAILED", f"Conversion failed with {len(conversion_errors)} error(s)", Fore.RED)
        return 1
    _emit("PASS", f"Conversion complete: converted={converted_count}, skipped={skipped_count}", Fore.GREEN)
    # MNE-BIDS may augment dataset_description.json (for example with
    # placeholder authors). Restore the explicitly configured dataset-level
    # metadata so first and repeated conversions are deterministic.
    writer.initialize_dataset()
    if args.skip_validation:
        manifest.set_validation_status("SKIPPED")
    else:
        try:
            _, validation_errors, validation_warnings = run_bids_validator(
                writer.root, warnings_as_errors=args.warnings_as_errors
            )
            _emit("PASS", f"BIDS validation: errors={validation_errors}", Fore.GREEN)
            if validation_warnings:
                _emit("WARNING", f"BIDS validation warnings={validation_warnings}", Fore.YELLOW)
            manifest.set_validation_status("SUCCESS")
        except ConverterError as exc:
            LOG.error("%s", exc)
            manifest.set_validation_status("ERROR")
            return 2
    try:
        index = build_dataset_index(writer.root)
        _emit(
            "PASS",
            f"PyBIDS index: subjects={index['subjects']}, sessions={index['sessions']}, "
            f"EEG={index['eeg_recordings']}, behavior={index['behavior_files']}",
            Fore.GREEN,
        )
    except ConverterError as exc:
        LOG.error("%s", exc)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    global USE_COLOR
    parser = build_parser()
    args = parser.parse_args(argv)
    just_fix_windows_console()
    USE_COLOR = not args.no_color and sys.stdout.isatty()
    handler = logging.StreamHandler()
    handler.setFormatter(_LevelColorFormatter("[%(levelname)s] %(message)s"))
    logging.basicConfig(level=getattr(logging, args.log_level), handlers=[handler])
    try:
        return run(args)
    except ConverterError as exc:
        LOG.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        LOG.error("Interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
