"""Portable emotion manifests and reproducible within-session presentation order."""
from __future__ import annotations
import csv
import hashlib
import json
import os
import random
from pathlib import Path
from video_eeg.utils.video_library import VideoAsset, load_video_library

CLASSES = ('positive', 'neutral', 'negative')
RATING_PAGES = (
    ('valence', '请评价刚才这段视频带给你的主观情绪感受。',
     '1 非常不愉快       5 中性       9 非常愉快'),
    ('arousal', '请评价刚才这段视频引起的情绪唤醒程度。',
     '1 非常平静／几乎没有被激活\n5 中等\n9 非常激动／强烈被激活'),
)

def parse_rating(key, maximum=9):
    name = str(getattr(key, 'name', key)).lower()
    if name.startswith('num_'):
        name = name[4:]
    return int(name) if name in '123456789' and len(name)==1 and int(name)<=maximum else None

def presentation_order(rows, seed, subject_id, session_id):
    digest = hashlib.sha256(f'{seed}|{subject_id}|{session_id}'.encode()).digest()
    rng = random.Random(int.from_bytes(digest, 'big'))
    ordinary = [r for r in rows if r['trial_type']=='ordinary']
    rng.shuffle(ordinary)
    grouped = {label: [r for r in rows if r['three_class_label']==label] for label in CLASSES}
    for group in grouped.values():
        rng.shuffle(group)
    emotion = []
    while any(grouped.values()):
        labels = [c for c in CLASSES if grouped[c]]
        rng.shuffle(labels)
        emotion.extend(grouped[c].pop() for c in labels)
    # One emotion at each evenly spaced point of ordinary net duration.
    total = sum(float(r['video_duration_sec']) for r in ordinary)
    targets = [(i+.5)*total/max(1, len(emotion)) for i in range(len(emotion))]
    order, elapsed, j = [], 0., 0
    for row in ordinary:
        while j<len(emotion) and targets[j] <= elapsed:
            order.append(emotion[j]['video_id']); j += 1
        order.append(row['video_id'])
        elapsed += float(row['video_duration_sec'])
    order.extend(r['video_id'] for r in emotion[j:])
    assert len(order)==len(rows) and len(set(order))==len(rows)
    return order

class EmotionLibrary:
    def __init__(self, rows, roots):
        self.rows = {r['video_id']: r for r in rows}
        self.roots = roots
        self.root = roots['original']
    def resolve(self, asset):
        prefix, rel = asset.rel_path.split('/', 1)
        root = self.roots[prefix].resolve()
        path = (root/rel).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Unsafe manifest path')
        return path
    def is_available(self, asset):
        return self.resolve(asset).is_file()

def ensure_practice(root):
    """Synthetic clips exercise UI only; their class assignment is not an annotation."""
    import cv2
    import numpy as np
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, label in enumerate(('',)+CLASSES):
        name = f'practice_{i}.mp4'
        path = root/name
        if not path.is_file():
            temporary = root/f'practice_{i}.tmp.mp4'
            writer = cv2.VideoWriter(str(temporary), cv2.VideoWriter_fourcc(*'mp4v'), 24, (640, 360))
            if not writer.isOpened():
                raise RuntimeError('Unable to generate emotion practice materials')
            try:
                for frame in range(120):
                    canvas = np.zeros((360,640,3), dtype=np.uint8)
                    cv2.circle(canvas, (60+frame*4,180), 40, (100,180,230), -1)
                    cv2.putText(canvas, 'PRACTICE', (20,40), cv2.FONT_HERSHEY_SIMPLEX, .8, (230,230,230), 1)
                    writer.write(canvas)
            finally:
                writer.release()
            temporary.replace(path)
        rows.append(dict(video_id=f'practice:{i}', video_path='practice/'+name, video_duration_sec=5.,
                         trial_type='emotion' if label else 'ordinary', three_class_label=label,
                         original_label='synthetic_practice' if label else '', sha256='', replacement_reason=''))
    return rows

def prepare(config, demo=False):
    root = Path(config['_project_dir'])
    protocol = config['protocol']
    roots = {'original': load_video_library(config).root}
    # Machine-specific file is deliberately excluded from source publication.
    settings_path = root/'emotion_library.local.json'
    settings = json.loads(settings_path.read_text(encoding='utf-8-sig')) if settings_path.exists() else {}
    emotion_root = os.environ.get('VIDEO_EEG_EMOTION_ROOT') or settings.get('emotion_root') or protocol.get('emotion_library_dir', '../video_materials/formal_v1/emotion_video')
    roots['emotion'] = (root/Path(emotion_root)/'selected').resolve()
    if demo:
        roots['practice'] = root/'stimuli/emotion_demo'
        rows = ensure_practice(roots['practice'])
        config['practice_materials'] = True
        digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    else:
        path = root/protocol['session_manifest']
        with path.open(encoding='utf-8-sig', newline='') as f:
            all_rows = list(csv.DictReader(f))
        rows = [r for r in all_rows if int(r['session_id'])==int(config['session_id'])]
        if not rows:
            raise RuntimeError('No assigned videos for this emotion Session')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        config['session_manifest_path'] = str(path)
        from video_eeg.utils.material_exclusions import exclusion_ids, REVISION
        config['excluded_video_ids'] = exclusion_ids(config, rows, digest)
        if config['excluded_video_ids']:
            config['material_exclusion_revision'] = REVISION
    config['session_manifest_hash'] = digest
    library = EmotionLibrary(rows, roots)
    playlist = [VideoAsset(r['video_id'], r['video_path'], float(r['video_duration_sec']), r['trial_type'], 'valid') for r in rows]
    return library, playlist
