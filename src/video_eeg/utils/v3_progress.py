"""Read-only v3 progress from authoritative state and saved EEG parts."""
import csv
import hashlib
from pathlib import Path
from video_eeg.paths import resolve_project_path

from video_eeg.experiment.emotion_v3_runner import eeg_saved
from video_eeg.utils.session_protocol import load_state
from video_eeg.utils.material_exclusions import exclusion_ids


def valid_subject(value):
    value = value.strip()
    if not value or value in {'.', '..'} or any(c in value for c in '<>:"/\\|?*') or value.endswith(('.', ' ')):
        raise ValueError('被试编号不能为空，不能包含路径或 Windows 文件名禁用字符。')
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{p}{i}' for p in ('COM', 'LPT') for i in range(1, 10)}
    if value.split('.')[0].upper() in reserved or any(ord(c) < 32 for c in value):
        raise ValueError('被试编号不是有效的 Windows 文件夹名称。')
    return value


def inspect_progress(config, subject, project_dir, *, seed=20260912):
    subject = valid_subject(subject)
    root = Path(project_dir)
    records = root / config['storage']['records_dir'] / subject
    demo = bool(config.get('demo_mode'))
    if demo:
        records /= f'run_{seed}'
        groups = {1: [dict(video_id=f'practice:{i}', trial_type='ordinary' if i == 0 else 'emotion') for i in range(4)]}
    else:
        manifest = resolve_project_path(config['protocol']['session_manifest'], project_root=root)
        with manifest.open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
        excluded = set(exclusion_ids(config, rows, hashlib.sha256(manifest.read_bytes()).hexdigest()))
        groups = {sid: [r for r in rows if int(r['session_id']) == sid and r['video_id'] not in excluded]
                  for sid in range(1, int(config['protocol']['num_sessions']) + 1)}
    emotion_only = config['protocol'].get('emotion_only', False) if 'protocol' in config else False
    if emotion_only:
        groups = {sid: [r for r in rows if r['trial_type'] == 'emotion'] for sid, rows in groups.items()}
    result = []
    for sid, rows in groups.items():
        ids = {r['video_id'] for r in rows}
        emotion = {r['video_id'] for r in rows if r['trial_type'] == 'emotion'}
        path = records / f'session_{sid:02d}' / 'session_state.json'
        state = load_state(path)
        completed, eligible, rated = set(), set(), set()
        if state is not None:
            task_type = 'emotion_v3_emotion_only_7' if emotion_only else 'emotion_v3_separate_eeg_ratings_7'
            if state.subject_id != subject or state.session_id != sid or state.attention_task_type != task_type:
                raise ValueError(f'Session {sid} 的身份或协议不匹配，请核对原记录。')
            if set(state.active_video_ids) != ids:
                raise ValueError(f'Session {sid} 的固定成员与当前配置不匹配，请核对原记录。')
            completed = ids.intersection(state.active_completed_video_ids)
            for attempt in state.video_attempts:
                if attempt.get('video_id') in emotion and eeg_saved(attempt):
                    eligible.add(attempt['video_id'])
                    if attempt['emotion_rating'].get('completed'):
                        rated.add(attempt['video_id'])
        result.append(dict(session=sid, videos_total=len(ids), videos_completed=len(completed),
            emotion_total=len(emotion), emotion_eeg_saved=len(eligible), ratings_completed=len(rated),
            eeg_complete=bool(state and state.session_completed and len(completed) == len(ids)),
            ratings_complete=len(rated) == len(emotion), path=str(path.parent)))
    return result
