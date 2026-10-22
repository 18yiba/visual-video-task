"""Authorized v2 removals layered over the immutable historical assignment.

Excluded trials are never recorded as completed. Historical attempts and answered
questions remain intact; only a pending question bound to a removed clip moves.
"""
from __future__ import annotations

import copy
import hashlib
import time
from pathlib import Path

REVISION = 'v2-remove-three-incomplete-20260919'
MANIFEST_SHA256 = 'cf59e1d8550d6945d61a68b55a8c9a52479ee0dfa3f3d3295d653ba0af476a23'
REMOVALS = {
    'original:vid_6076': (20, 'original/6076.mp4'),
    'original:vid_2693': (24, 'original/2693.mp4'),
    'original:vid_6241': (33, 'original/6241.mp4'),
}


def excluded_filenames(protocol):
    return {Path(path).name for _, path in REMOVALS.values()} if protocol == 'v2' else set()


def exclusion_ids(config, rows, manifest_hash):
    if config.get('demo_mode') or config.get('protocol', {}).get('kind') != 'emotion-v2':
        return []
    if manifest_hash != MANIFEST_SHA256:
        # Never silently apply this revision to another protocol or regrouping.
        if any(r['video_id'] in REMOVALS for r in rows):
            raise RuntimeError('排除清单对应另一份固定分组，请保留现场核对；未修改进度。')
        return []
    result = []
    for row in rows:
        if row['video_id'] in REMOVALS:
            sid, path = REMOVALS[row['video_id']]
            if (int(row['session_id']), row['video_path'], row['trial_type']) != (sid, path, 'ordinary'):
                raise RuntimeError('材料排除规则与固定分组不一致')
            result.append(row['video_id'])
    return result


def apply_to_state(state, excluded, rows, questions, state_path):
    """Plan first, preserve exact original bytes, then mutate in-memory state.

    The caller atomically saves the revised state. Retrying after a crash is safe.
    Already completed Sessions retain their original scientific record.
    """
    excluded = list(excluded)
    if not set(excluded).issubset(state.video_ids):
        raise RuntimeError('材料排除ID不属于本Session')
    if state.excluded_video_ids:
        if state.material_exclusion_revision != REVISION or set(state.excluded_video_ids) != set(excluded):
            raise RuntimeError('已有材料排除记录与本版不一致，请保留现场核对')
        if any(v in excluded for v in state.queue_video_ids):
            raise RuntimeError('已排除视频意外回到待播放队列')
        return
    if not excluded or state.session_completed:
        return

    queue = [v for v in state.queue_video_ids if v not in excluded]
    schedule = copy.deepcopy(state.attention_schedule)
    bound = {item['video_id'] for item in schedule}
    elapsed = state.completed_net_video_duration_sec
    candidates = []
    for video_id in queue:
        row = rows[video_id]
        elapsed += float(row['video_duration_sec'])
        if row['trial_type'] == 'ordinary' and row['video_path'] in questions and video_id not in bound:
            candidates.append((video_id, elapsed))
    rebindings = []
    for item in schedule:
        if item['video_id'] not in excluded or item['attention_id'] in state.completed_attention_ids:
            continue
        if not candidates:
            raise RuntimeError('本Session没有可承接未完成内容题的普通视频；未修改进度，请保留现场排查。')
        previous = copy.deepcopy(item)
        chosen = min(candidates, key=lambda pair: abs(pair[1] - float(item['planned_trigger_net_sec'])))
        candidates.remove(chosen)
        item.update(video_id=chosen[0], planned_trigger_net_sec=chosen[1],
                    replaced_video_id=previous['video_id'], material_exclusion_revision=REVISION)
        rebindings.append({'before': previous, 'after': copy.deepcopy(item)})

    backup = None
    path = Path(state_path)
    if path.is_file():
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        backup = path.with_name('session_state.before_' + REVISION + '.' + digest + '.json')
        if backup.exists():
            if backup.read_bytes() != raw:
                raise RuntimeError('排除前备份文件不一致；未修改进度')
        else:
            with backup.open('xb') as handle:
                handle.write(raw)
                handle.flush()
                __import__('os').fsync(handle.fileno())
    state.excluded_video_ids = excluded
    state.material_exclusion_revision = REVISION
    state.material_exclusion_history.append({
        'revision': REVISION, 'timestamp_unix_sec': time.time(),
        'reason': 'user_authorized_removal_of_incomplete_ordinary_material',
        'excluded_video_ids': excluded, 'attention_rebindings': rebindings,
        'state_backup': backup.name if backup else None,
        'historical_attempts_preserved': True,
    })
    state.queue_video_ids = queue
    state.attention_schedule = schedule
    if state.current_video_id in excluded:
        state.current_video_id = None
