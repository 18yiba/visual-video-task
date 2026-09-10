"""Export manifest views and create verified same-volume hardlinks (never copy/move)."""
import argparse
import csv
import json
import os
from pathlib import Path
import statistics
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from video_eeg.utils.session_protocol import SessionManifest
from video_eeg.utils.session_integrity import inspect_session_files


def write_csv(path, rows):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def materialize(manifest, root):
    if os.name == 'nt':
        import ctypes
        fs = ctypes.create_unicode_buffer(64)
        if not ctypes.windll.kernel32.GetVolumeInformationW(str(root.resolve().anchor), None, 0, None, None, None, fs, len(fs)):
            raise OSError('Cannot determine destination filesystem; no links created')
        if fs.value != 'NTFS':
            raise RuntimeError(f'Filesystem {fs.value} does not support this NTFS hardlink workflow. '
                               'Shared rating videos were not moved or copied. Deploy the bundle on NTFS first.')
    report = inspect_session_files(manifest, root)
    if report['missing'] or report['duplicate_assignments']:
        raise ValueError(report)
    # Check every destination before creating anything; unknown files are never removed.
    for sid in range(1, 18):
        folder = root.parent / f'session_{sid:02d}'
        expected = {Path(e.video_path).name: root / e.video_path for e in manifest.session_entries(sid)}
        if folder.exists():
            for p in folder.iterdir():
                if p.name not in expected or not p.is_file() or not p.samefile(expected[p.name]):
                    raise ValueError(f'Unknown/conflicting session file; preserved: {p}')
    # Capability probe in the actual destination filesystem, removed on success or failure.
    probe = root.parent / '.session_hardlink_probe'
    if probe.exists():
        raise ValueError(f'Existing probe preserved: {probe}')
    created_probe = False
    try:
        os.link(root / manifest.entries[0].video_path, probe)
        created_probe = True
        if not probe.samefile(root / manifest.entries[0].video_path):
            raise RuntimeError('Hardlink verification failed')
    finally:
        if created_probe and probe.exists():
            probe.unlink()
    for entry in manifest.entries:
        folder = root.parent / f'session_{entry.session_id:02d}'
        folder.mkdir(exist_ok=True)
        destination = folder / Path(entry.video_path).name
        if not destination.exists():
            os.link(root / entry.video_path, destination)
    report = inspect_session_files(manifest, root)
    if report['valid_session_folders'] != 17:
        raise RuntimeError(report)
    return report


def export_tables(manifest, root, manifest_path=None):
    summaries, mapping = [], []
    buckets = [b['name'] for b in manifest.duration_bucket_definition]
    for sid in range(1, 18):
        entries = manifest.session_entries(sid)
        ds = [e.video_duration_sec for e in entries]
        row = dict(session_id=sid, video_count=len(ds), total_duration_sec=sum(ds),
                   total_duration_min=sum(ds)/60, mean_duration_sec=statistics.mean(ds),
                   median_duration_sec=statistics.median(ds), min_duration_sec=min(ds), max_duration_sec=max(ds))
        for b in buckets:
            row[b + '_count'] = sum(e.duration_bucket == b for e in entries)
            row[b + '_duration_sec'] = sum(e.video_duration_sec for e in entries if e.duration_bucket == b)
        row['manifest_version'] = manifest.version
        summaries.append(row)
        for e in entries:
            mapping.append(dict(video_id=e.video_id, filename=Path(e.video_path).name,
                                duration_sec=e.video_duration_sec, duration_bucket=e.duration_bucket,
                                session_id=sid, source_path='videos/' + e.video_path,
                                session_view_path=f'session_{sid:02d}/' + Path(e.video_path).name,
                                view_exists=(root.parent / f'session_{sid:02d}' / Path(e.video_path).name).is_file(),
                                manifest_version=manifest.version))
    write_csv(root.parent / 'SESSION_SUMMARY.csv', summaries)
    write_csv(root.parent / 'SESSION_VIDEO_MAP.csv', mapping)
    # Reference only: keep the existing CSV/hash and checkpoint identities authoritative.
    write_csv(root.parent / 'SESSION_MANIFEST_REFERENCE.csv', [dict(
        manifest_path=Path(os.path.relpath(manifest_path or PROJECT / 'video_eeg/config/session_manifest.csv', root.parent)).as_posix(),
        manifest_hash=manifest.content_hash, manifest_version=manifest.version)])
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video-root', type=Path, default=PROJECT.parent / 'video_materials/formal_v1/videos')
    parser.add_argument('--manifest', type=Path, default=PROJECT / 'video_eeg/config/session_manifest.csv')
    parser.add_argument('--create-links', action='store_true')
    args = parser.parse_args()
    manifest = SessionManifest.load(args.manifest)
    if args.create_links:
        materialize(manifest, args.video_root)
    summaries = export_tables(manifest, args.video_root, args.manifest)
    print(json.dumps(dict(integrity=inspect_session_files(manifest, args.video_root), summaries=summaries), ensure_ascii=False))


if __name__ == '__main__':
    main()
