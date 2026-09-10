"""Reproduce 34 Sessions as two duration-balanced halves of each original Session."""
from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video_eeg.utils.session_protocol import SessionManifest, split_manifest_sessions


def main():
    config = ROOT / 'video_eeg/config'
    original = config / 'session_manifest.csv'
    legacy = SessionManifest.load(original, session_count=17)
    manifest = split_manifest_sessions(legacy)
    target = config / 'session_manifest_34.csv'
    if target.exists():
        if SessionManifest.load(target, session_count=34).content_hash != manifest.content_hash:
            raise ValueError('Existing 34-Session manifest differs; refusing to overwrite')
    else:
        manifest.write_atomic(target)
    rows = []
    for sid in range(1, 35):
        entries = manifest.session_entries(sid)
        buckets = Counter(e.duration_bucket for e in entries)
        rows.append(dict(session_id=sid, legacy_session_id=(sid+1)//2, videos=len(entries),
            net_video_minutes=round(sum(e.video_duration_sec for e in entries)/60, 6),
            min_video_seconds=min(e.video_duration_sec for e in entries),
            max_video_seconds=max(e.video_duration_sec for e in entries), **buckets))
    totals = [r['net_video_minutes'] for r in rows]
    report = dict(session_count=34, video_count=len(manifest.entries),
        total_video_hours=sum(e.video_duration_sec for e in manifest.entries)/3600,
        mean_net_minutes=sum(totals)/34, min_net_minutes=min(totals), max_net_minutes=max(totals),
        legacy_manifest_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
        manifest_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        manifest_content_hash=manifest.content_hash, sessions=rows)
    (config/'session_34_audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    with (config/'session_34_summary.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    print(json.dumps({k:v for k,v in report.items() if k != 'sessions'}), flush=True)


if __name__ == '__main__': main()
