"""Unified launcher's new-data layout with read-only legacy subject discovery."""
from pathlib import Path

LEGACY_ROOTS={
    'legacy17':['data/video_question_complete_runs'],
    'legacy34':['data/video_question_complete_runs/protocol_34sessions'],
    'legacy2779':['data/video_question_runs'],
    'emotion-v1':['data/video_emotion_eeg_runs/protocol_emotion_v1'],
    'emotion-v2':['data/video_emotion_eeg_runs/protocol_emotion_v2'],
}

def recording_root(config, project_dir, subject_id=None):
    project=Path(project_dir).resolve()
    configured=Path(config.get('storage',{}).get('records_dir','data/sourcedata'))
    configured=(project/configured).resolve()
    key=config.get('_unified_protocol')
    if not key:return configured
    if key not in LEGACY_ROOTS:raise ValueError('Unknown recording protocol')
    source_root=(project/Path(config.get('storage',{}).get('source_data_root','data/sourcedata'))).resolve()
    if config.get('demo_mode'):
        return source_root/'demo'/key
    subject=str(subject_id if subject_id is not None else config.get('subject_id','S001')).strip()
    if not subject or subject in {'.','..'} or any(c in subject for c in '/\\:*?"<>|'):
        raise ValueError('被试编号不能包含路径分隔符或Windows文件名非法字符')
    unified=source_root/key
    candidates=list(dict.fromkeys([unified.resolve(),(project/'data/sourcedata'/key).resolve(),configured]+[(project/p).resolve() for p in LEGACY_ROOTS[key]]))
    # Find progress only at the subject root for this protocol; never scan other subjects.
    existing=[p for p in candidates if any((p/subject).glob('session_*/session_state.json'))
              or any((p/subject).glob('run_*/session_*/session_state.json'))]
    if len(existing)>1:
        raise RuntimeError('同一被试在多个保存位置有进度，不能自动选择或合并：'+ '\n'.join(map(str,existing)))
    return existing[0] if existing else unified
