"""Build a new, portable protocol without changing legacy membership or media.

Input is the FINAL ffprobe-validated extraction CSV, never the sampling plan.
Run with --verify-media to hash/probe every emotion file and probe ordinary files.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import random
import shutil
import statistics
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260912
CLASSES = ('positive', 'neutral', 'negative')

def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

def sha256(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def assign(rows, capacities, rng):
    """Equal cardinality first; longest-first allocation followed by sum swaps."""
    groups = [[] for _ in capacities]
    sums = [0.0] * len(groups)
    shuffled = list(rows)
    rng.shuffle(shuffled)
    for row in sorted(shuffled, key=lambda r: -r['video_duration_sec']):
        idx = min((i for i in range(len(groups)) if len(groups[i]) < capacities[i]),
                  key=lambda i: (sums[i], len(groups[i]), i))
        groups[idx].append(row)
        sums[idx] += row['video_duration_sec']
    for _ in range(3000):
        hi, lo = max(range(len(sums)), key=sums.__getitem__), min(range(len(sums)), key=sums.__getitem__)
        gap = sums[hi] - sums[lo]
        candidates = [(abs(gap - 2*(a['video_duration_sec']-b['video_duration_sec'])), x, y)
                      for x, a in enumerate(groups[hi]) for y, b in enumerate(groups[lo])
                      if 0 < a['video_duration_sec']-b['video_duration_sec'] < gap]
        if not candidates:
            break
        _, x, y = min(candidates)
        delta = groups[hi][x]['video_duration_sec']-groups[lo][y]['video_duration_sec']
        groups[hi][x], groups[lo][y] = groups[lo][y], groups[hi][x]
        sums[hi] -= delta
        sums[lo] += delta
    return groups

def build(ordinary, emotion, seed=SEED):
    assert len(ordinary) == 7949 and len(emotion) == 3138
    assert Counter(r['three_class_label'] for r in emotion) == dict.fromkeys(CLASSES, 1046)
    assert len({r['video_id'] for r in ordinary + emotion}) == 11087
    total = sum(r['video_duration_sec'] for r in ordinary + emotion)
    feasible = [s for s in range(1, 1047) if 85 <= total / s / 60 <= 95]
    session_count = min(feasible, key=lambda s: (abs(total / s / 60 - 90), s))
    comparison = [{'session_count': s, 'mean_net_minutes': total / s / 60,
                   'mean_within_85_95': 85 <= total / s / 60 <= 95,
                   'chosen': s == session_count} for s in sorted(set(feasible + [45, 46, 47]))]
    rng = random.Random(seed)
    q, rem = divmod(1046, session_count)
    capacities = [q + (i < rem) for i in range(session_count)]
    rng.shuffle(capacities)
    sessions = [[] for _ in capacities]
    for label in CLASSES:
        groups = assign([r for r in emotion if r['three_class_label'] == label], capacities, rng)
        for i, group in enumerate(groups):
            sessions[i].extend(group)
    sums = [sum(r['video_duration_sec'] for r in group) for group in sessions]
    # Ordinary materials are longest-first. Each session receives both long and short clips.
    shuffled = list(ordinary)
    rng.shuffle(shuffled)
    for row in sorted(shuffled, key=lambda r: -r['video_duration_sec']):
        i = min(range(session_count), key=lambda k: (sums[k], k))
        sessions[i].append(row)
        sums[i] += row['video_duration_sec']
    manifest, summary = [], []
    for i, group in enumerate(sessions, 1):
        counts = Counter(r['three_class_label'] for r in group if r['trial_type'] == 'emotion')
        assert len(set(counts.values())) == 1 and set(counts) == set(CLASSES)
        duration = sum(r['video_duration_sec'] for r in group)
        assert 85 <= duration/60 <= 95
        summary.append(dict(session_id=i, ordinary_count=sum(r['trial_type']=='ordinary' for r in group),
                            **{f'{c}_count': counts[c] for c in CLASSES},
                            **{f'{c}_duration_sec': sum(r['video_duration_sec'] for r in group if r['three_class_label']==c) for c in CLASSES},
                            emotion_duration_sec=sum(r['video_duration_sec'] for r in group if r['trial_type']=='emotion'),
                            total_net_sec=duration, total_net_minutes=duration/60,
                            ordinary_duration_bins=';'.join(sorted({r['duration_bucket'] for r in group if r['trial_type']=='ordinary'}))))
        manifest.extend(dict(protocol_version='emotion-v1', random_seed=seed, session_id=i, **r)
                        for r in sorted(group, key=lambda r: r['video_id']))
    return manifest, summary, comparison

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ordinary-manifest', type=Path, default=ROOT/'video_eeg/config/session_manifest_34.csv')
    p.add_argument('--ordinary-root', type=Path, required=True)
    p.add_argument('--emotion-root', type=Path, required=True)
    p.add_argument('--output', type=Path, default=ROOT/'video_eeg/config')
    p.add_argument('--verify-media', action='store_true')
    p.add_argument('--ffprobe', default=shutil.which('ffprobe'))
    p.add_argument('--verification-cache', type=Path)
    a = p.parse_args()
    original = read_csv(a.ordinary_manifest)
    final = read_csv(a.emotion_root/'metadata/selected_videos.csv')
    ordinary = [dict(video_id='original:'+r['video_id'], video_path='original/'+r['video_path'],
                     video_duration_sec=float(r['video_duration_sec']), trial_type='ordinary',
                     original_label='', three_class_label='', sha256='', duration_bucket=r['duration_bucket'],
                     original_id=r['video_id'], replacement_reason='', has_audio='') for r in original]
    emotion = []
    files = {}
    for row in ordinary:
        files[row['video_id']] = a.ordinary_root / row['video_path'].removeprefix('original/')
    for r in final:
        # Resolve the final filename portably instead of trusting the original machine's drive.
        rel = Path(r['three_class_label']) / r['original_label'].lower() / Path(r['local_path']).name
        row = dict(video_id='emotion:'+r['file_name'], video_path='emotion/'+rel.as_posix(),
                   video_duration_sec=float(r['duration_ffprobe']), trial_type='emotion',
                   original_label=r['original_label'], three_class_label=r['three_class_label'],
                   sha256=r['sha256'], duration_bucket=r['duration_bin'], original_id=r['file_name'],
                   replacement_reason=('replacement_for:'+r.get('replacement_for','')) if r.get('replacement_used')=='True' else '',
                   has_audio=r['has_audio'])
        files[row['video_id']] = a.emotion_root/'selected'/rel
        emotion.append(row)
    assert len({r['sha256'] for r in emotion}) == 3138
    for key, path in files.items():
        if not path.is_file():
            raise FileNotFoundError(f'{key}: {path}')
    cache = json.loads(a.verification_cache.read_text()) if a.verification_cache and a.verification_cache.exists() else {}
    if a.verify_media:
        if not a.ffprobe:
            raise RuntimeError('Supply --ffprobe with the ffprobe executable path')
        def verify(row):
            path = files[row['video_id']]
            stat = path.stat()
            key = str(path.resolve())
            signature = [stat.st_size, stat.st_mtime_ns, row['sha256']]
            result = cache.get(key)
            if not result or result['signature'] != signature:
                probe = json.loads(subprocess.check_output([a.ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], timeout=45))
                assert any(s['codec_type']=='video' for s in probe['streams']), key
                duration = float(probe['format']['duration'])
                if row['trial_type']=='emotion':
                    assert sha256(path)==row['sha256'], key
                result = dict(signature=signature, duration=duration, ffprobe_valid=True)
            assert result['duration'] > 0, key
            if row['trial_type']=='emotion':
                assert 5 <= result['duration'] <= 60, key
                assert abs(result['duration']-row['video_duration_sec']) < 0.1, key
            row['video_duration_sec'] = result['duration']
            return key, result
        with ThreadPoolExecutor(max_workers=8) as pool:
            for count, (key, result) in enumerate(pool.map(verify, ordinary+emotion), 1):
                cache[key] = result
                if count % 500 == 0:
                    print(f'Validated {count}/11087', flush=True)
                    if a.verification_cache:
                        a.verification_cache.parent.mkdir(parents=True, exist_ok=True)
                        a.verification_cache.write_text(json.dumps(cache), encoding='utf-8')
        if a.verification_cache:
            a.verification_cache.write_text(json.dumps(cache), encoding='utf-8')
    manifest, summary, comparison = build(ordinary, emotion)
    write_csv(a.output/'session_manifest_emotion_v1.csv', manifest)
    write_csv(a.output/'emotion_trial_manifest_v1.csv', [r for r in manifest if r['trial_type']=='emotion'])
    write_csv(a.output/'emotion_session_balance_v1.csv', summary)
    write_csv(a.output/'emotion_session_count_comparison_v1.csv', comparison)
    audit = dict(protocol='emotion-v1', seed=SEED, ordinary_count=len(ordinary), emotion_count=len(emotion),
                 total_count=len(manifest), session_count=len(summary), total_net_hours=sum(r['total_net_sec'] for r in summary)/3600,
                 min_session_minutes=min(r['total_net_minutes'] for r in summary), max_session_minutes=max(r['total_net_minutes'] for r in summary),
                 emotion_counts=dict(Counter(r['three_class_label'] for r in emotion)),
                 original_label_counts=dict(Counter(r['original_label'] for r in emotion)),
                 legacy_manifest_sha256=sha256(a.ordinary_manifest), final_emotion_csv_sha256=sha256(a.emotion_root/'metadata/selected_videos.csv'),
                 new_manifest_sha256=sha256(a.output/'session_manifest_emotion_v1.csv'),
                 media_verified=a.verify_media, unique_usage='PASS', every_session_class_balance='PASS', session_duration_85_95='PASS')
    (a.output/'emotion_global_usage_audit_v1.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(audit, indent=2))
    print('SESSION COUNT COMPARISON', comparison)

if __name__=='__main__':
    main()
