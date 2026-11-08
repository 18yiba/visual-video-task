"""Read-only selection of separated v3 EMOTIV roots with legacy isolation."""
import json
from pathlib import Path


def v3_emotiv_root(config, project, subject):
    storage = config.get('storage', {})
    original = Path(storage.get('records_dir', 'data/sourcedata/v3'))
    if not original.is_absolute():
        original = Path(project) / original
    original = original.resolve()
    scope = bool(config.get('protocol', {}).get('emotion_only'))
    transport = config.get('device', {}).get('emotiv_transport', 'serial')
    if transport not in {'cortex', 'serial'}:
        raise ValueError('未知 EMOTIV 采集方式')
    # Names intentionally follow the requested spellings exactly.
    suffix = '_cortex' if transport == 'cortex' else '_emotviePRO'
    if scope and transport == 'serial':
        suffix = '_emotivePRO'
    base_name = original.name.removesuffix('_emotion_only') if scope else original.name
    for existing_suffix in ('_cortex', '_emotviePRO', '_emotivePRO'):
        if base_name.endswith(existing_suffix):
            base_name = base_name[:-len(existing_suffix)]
            break
    legacy = original.with_name(base_name + ('_emotion_only' if scope else ''))
    target = original.with_name(base_name + suffix + ('_emotion_only' if scope else ''))
    if not subject:
        return target
    if (any(c in str(subject) for c in '<>:"/\\|?*') or str(subject) in {'.', '..'}
            or str(subject).endswith(('.', ' ')) or any(ord(c) < 32 for c in str(subject))):
        raise ValueError('无效被试编号')
    old_subject, new_subject = legacy / str(subject), target / str(subject)
    old_states = list(old_subject.glob('session_*/session_state.json'))
    new_states = list(new_subject.glob('session_*/session_state.json'))
    if new_subject.exists() and any(new_subject.iterdir()) and not new_states:
        raise RuntimeError(f'新被试目录存在但缺少可识别进度，请核对：{new_subject}')
    if not old_states:
        if old_subject.exists() and any(old_subject.iterdir()):
            raise RuntimeError(f'旧被试目录存在但缺少可识别进度，请核对：{old_subject}')
        return target
    # Do not infer the acquisition device from a directory or a video count.
    modes = set()
    for state in old_states:
        metadata = list(state.parent.glob('*/metadata*.json'))
        if not metadata:
            raise RuntimeError(f'旧记录缺少采集 metadata，无法确定设备：{state.parent}')
        for path in metadata:
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise RuntimeError(f'旧采集 metadata 无法读取：{path}') from exc
            mode = record.get('eeg_recording_mode')
            device = record.get('device_type')
            if mode == 'emotivpro_external':
                modes.add('serial')
            elif device == 'emotiv_cortex' and mode == 'local_continuous_eeg':
                modes.add('cortex')
            else:
                raise RuntimeError(f'旧记录采集方式不明确：{path}')
    if len(modes) != 1:
        raise RuntimeError(f'旧目录混有多种采集方式，不能自动选择：{old_subject}')
    if transport not in modes:
        return target
    if new_states:
        raise RuntimeError(f'同一被试在新旧目录均有进度，不能自动选择：\n{old_subject}\n{new_subject}')
    return legacy
