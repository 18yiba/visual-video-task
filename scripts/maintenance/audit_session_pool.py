"""Fresh OpenCV header/first-frame audit; does not claim full-file decoding."""
from concurrent.futures import ThreadPoolExecutor
import json
import csv
from pathlib import Path
import statistics
import sys
import time

import cv2
import numpy as np
PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
from video_eeg.experiment.video_runner import load_config
from video_eeg.utils.session_protocol import SessionManifest
from video_eeg.utils.video_library import VIDEO_EXTENSIONS, _probe_mp4_mvhd_duration, load_video_library


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def inspect(path):
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        ok, frame = cap.read()
        video_duration = frames/fps if fps > 0 else 0.0
        duration = _probe_mp4_mvhd_duration(path) or video_duration
        return dict(filename=path.name, duration_sec=duration, bytes=path.stat().st_size,
                    first_frame_ok=bool(ok and frame is not None), fps=fps,
                    frame_count=frames, over_60=duration > 60.000001, video_track_duration_sec=video_duration)
    finally:
        cap.release()


def main():
    config = load_config(PROJECT / 'video_eeg/config/video_config.yaml')
    config['_project_dir'] = str(PROJECT)
    root = load_video_library(config).root
    files = sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
    if '--refresh-container-durations' in sys.argv:
        with (root.parent / 'VIDEO_POOL_AUDIT.csv').open(encoding='utf-8-sig') as handle:
            previous = {r['filename']: r for r in csv.DictReader(handle)}
        rows = []
        for p in files:
            row = previous[p.name]
            assert p.stat().st_size == int(row['bytes'])
            row['video_track_duration_sec'] = float(row.get('video_track_duration_sec', row['duration_sec']))
            row['duration_sec'] = _probe_mp4_mvhd_duration(p)
            assert row['duration_sec'] is not None
            row['first_frame_ok'] = row['first_frame_ok'] == 'True'
            row['over_60'] = row['duration_sec'] > 60.000001
            rows.append(row)
    else:
        with ThreadPoolExecutor(max_workers=4) as executor:
            rows = list(executor.map(inspect, files))
    write_csv(root.parent / 'VIDEO_POOL_AUDIT.csv', rows)
    manifest = SessionManifest.load(PROJECT / config['protocol']['session_manifest_path'], session_count=config['protocol']['num_sessions'])
    eligible = {r['filename'] for r in rows if r['first_frame_ok'] and 0 < r['duration_sec'] <= 60.000001}
    assigned = {e.video_path for e in manifest.entries}
    ds = [r['duration_sec'] for r in rows]
    report = dict(generated_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'), method='MP4 mvhd container duration; OpenCV video-track duration + first decoded frame; NOT full decode',
                  count=len(rows), total_hours=sum(ds)/3600, mean=statistics.mean(ds),
                  percentiles=dict(zip(['min','P10','P25','median','P75','P90','max'], np.percentile(ds,[0,10,25,50,75,90,100]).tolist())),
                  over_60=[r for r in rows if r['over_60']], unreadable=[r for r in rows if not r['first_frame_ok']],
                  duplicate_names=len(files)-len({p.name.casefold() for p in files}), non_mp4=[p.name for p in files if p.suffix.lower() != '.mp4'],
                  eligible=len(eligible), unassigned=sorted(eligible-assigned), ineligible_assigned=sorted(assigned-eligible),
                  max_duration_difference_from_manifest=max(abs(e.video_duration_sec-next(r['duration_sec'] for r in rows if r['filename']==e.video_path)) for e in manifest.entries))
    (root.parent / 'VIDEO_POOL_AUDIT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
