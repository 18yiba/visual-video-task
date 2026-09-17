"""Persistent desktop settings and additive binding to an existing laboratory project."""
from pathlib import Path
import copy,json,os
import yaml

def save_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.writing')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temporary,path)

def legacy_config(project):
    project=Path(project).resolve()
    for name in ('video_config.yaml','video_legacy_17_config.yaml','video_ready_config.yaml'):
        path=project/'video_eeg/config'/name
        if not path.is_file():continue
        cfg=yaml.safe_load(path.read_text(encoding='utf-8-sig'))
        if int(cfg.get('protocol',{}).get('num_sessions',0))!=17:continue
        if cfg.get('hardware_dummy_mode'):raise ValueError('旧正式配置启用了模拟EEG，请先核对原配置。')
        for key in ('session_manifest_path','question_bank_path'):
            if key=='question_bank_path' and not cfg['protocol'].get(key):continue
            if not cfg['protocol'].get(key) or not (project/cfg['protocol'][key]).is_file():
                raise ValueError('原实验缺少文件：'+key)
        return path,cfg
    raise ValueError('请选择包含video_eeg的原17组v1程序目录；不能把其他协议当作v1继续。')

def assert_legacy_idle(project):
    import psutil
    root=str(Path(project).resolve()).lower()
    for proc in psutil.process_iter(['pid','name','cmdline']):
        try:
            if proc.pid==os.getpid():continue
            command=' '.join(proc.info.get('cmdline') or []).lower()
            experiment=any(name in command for name in ('video_runner','run_experiment','launch_experiment','offline_unified_bootstrap'))
            if not experiment:continue
            # BAT entry points often run a relative module after cd /d, leaving
            # the project path out of the command line entirely.
            working=str(Path(proc.cwd()).resolve()).lower()
            if root in command or working==root or working.startswith(root+os.sep):
                raise RuntimeError('原v1实验仍在运行。请正常保存结束本次采集后，再使用新入口；程序不会终止旧进程。')
        except (psutil.AccessDenied,psutil.NoSuchProcess):continue

def adapt_config(config, filename, settings, user_dir, project_dir):
    cfg=copy.deepcopy(config);demo='demo' in Path(filename).name;v1='emotion' not in Path(filename).name
    old=Path(settings['legacy_project']) if settings.get('legacy_project') else None
    if old:
        _,original=legacy_config(old)
        if v1:
            inherited=original
            if demo:
                path=old/'video_eeg/config/video_demo_config.yaml'
                if not path.is_file():raise ValueError('原v1缺少Demo配置。')
                inherited=yaml.safe_load(path.read_text(encoding='utf-8-sig'))
            cfg.update(copy.deepcopy(inherited))
            for key in ('question_bank_path','session_manifest_path','session_manifest','formal_exclusion_report_path'):
                if cfg['protocol'].get(key):cfg['protocol'][key]=str((old/cfg['protocol'][key]).resolve())
            cfg['_legacy_attention']=not bool(cfg['protocol'].get('question_bank_path'))
        for key in ('device','device_type','sfreq','eeg_sampling_rate_hz','buffer_sec'):
            if key in original:cfg[key]=copy.deepcopy(original[key])
        storage=cfg.setdefault('storage',{})
        storage['source_data_root']=str((old/original.get('storage',{}).get('source_data_root','data/sourcedata')).resolve())
        storage['records_dir']=str((old/original.get('storage',{}).get('records_dir','data/sourcedata')).resolve()) if v1 else str(old/'data/video_emotion_eeg_runs/protocol_emotion_v2')
    else:
        cfg['storage']={'source_data_root':str(Path(user_dir)/'data/sourcedata'),'records_dir':str(Path(user_dir)/'data/sourcedata')}
        overrides=Path(user_dir)/'device.local.yaml'
        if overrides.is_file():
            for key,value in (yaml.safe_load(overrides.read_text(encoding='utf-8-sig')) or {}).items():
                if key not in {'device','device_type','sfreq','eeg_sampling_rate_hz','buffer_sec'}:
                    raise ValueError('device.local.yaml含不支持的设置：'+key)
                cfg[key]=value
    if not demo:
        if settings.get('ordinary_root'):cfg['protocol']['video_library_dir']=settings['ordinary_root']
        if not v1 and settings.get('emotion_root'):cfg['protocol']['emotion_library_dir']=settings['emotion_root']
    cfg['demo_mode']=demo;cfg['hardware_dummy_mode']=demo
    return cfg
