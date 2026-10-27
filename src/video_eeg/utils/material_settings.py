"""Machine-specific, read-only media roots; never change recording roots."""
from pathlib import Path
import json
import os
from functools import lru_cache

from video_eeg.paths import resolve_project_path


def settings_path(project):
    return Path(os.environ.get('VIDEO_EEG_MATERIAL_SETTINGS') or Path(project)/'materials.local.json')


def apply(config, project):
    if config.get('demo_mode') or config.get('hardware_dummy_mode'):
        return config
    path=settings_path(project)
    if not path.is_file():
        return config
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    if set(value)!={'ordinary_root','emotion_root'} or not all(isinstance(v,str) and v for v in value.values()):
        raise ValueError('materials.local.json必须只包含ordinary_root和emotion_root两个非空路径。')
    protocol=config.setdefault('protocol',{})
    protocol['video_library_dir']=value['ordinary_root']
    protocol['emotion_library_dir']=value['emotion_root']
    config['_material_roots_explicit']=True
    return config


def save(root, project):
    from video_eeg.utils.desktop_local import require_material_path
    from video_eeg.utils.desktop import save_json
    root=require_material_path(root)
    if root.name=='selected':root=root.parent.parent
    elif root.name in {'videos','emotion_video'}:root=root.parent
    ordinary=require_material_path(root/'videos')
    emotion=require_material_path(root/'emotion_video')
    for path in (ordinary,emotion/'selected'):
        if not path.is_dir():
            raise ValueError('视频目录不可访问，请在Windows中登录NAS并核对路径：'+str(path))
    # Only read the share; the configuration is saved locally.
    for directory in (ordinary,emotion/'selected'):
        with os.scandir(directory) as entries:
            next(entries,None)
    value=dict(ordinary_root=str(ordinary),emotion_root=str(emotion))
    save_json(settings_path(project),value)
    return value


def check(config):
    from video_eeg.utils.desktop_local import require_material_path
    protocol=config['protocol']
    for name,path in [('普通视频',protocol['video_library_dir']),
                      ('情绪视频',Path(protocol['emotion_library_dir'])/'selected')]:
        resolved=require_material_path(path)
        if not resolved.is_dir():
            raise ValueError(name+'目录不可访问，请核对NAS连接和Windows共享登录：'+str(resolved))


def verify_asset(path, expected):
    import hashlib
    if not expected:
        raise ValueError('材料缺少已核验SHA256，不能开始播放。')
    try:
        with Path(path).open('rb') as stream:
            actual=hashlib.file_digest(stream,'sha256').hexdigest()
    except OSError as exc:
        raise RuntimeError('视频读取失败，请检查NAS连接和共享登录；当前视频保留待重播：'+str(path)) from exc
    if actual!=expected:
        raise RuntimeError('视频SHA256与固定清单不一致，停止播放：'+str(path))


@lru_cache(maxsize=8)
def ordinary_hashes(project):
    path=resolve_project_path('video_eeg/config/materials_manifest.json', project_root=Path(project))
    value=json.loads(path.read_text(encoding='utf-8'))
    return {Path(row['path']).name:row['sha256'] for row in value['files']}


def verify_trial(config,row,path):
    # Ordinary session rows intentionally omit SHA; use the immutable base catalog.
    expected=row.get('sha256')
    if not expected and row.get('trial_type')=='ordinary':
        expected=ordinary_hashes(str(config['_project_dir'])).get(Path(path).name)
    verify_asset(path,expected)
