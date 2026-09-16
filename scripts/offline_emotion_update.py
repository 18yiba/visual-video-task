"""Additive offline emotion upgrade: reuse parent environment/config, never old state."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import sys

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent

def configure():
    if sys.version_info[:2]!=(3,12):
        raise RuntimeError('需要现有 Python 3.12 环境；不要重装旧环境，请带回检查报告。')
    for row in json.loads((ROOT/'OFFLINE_FILES.json').read_text(encoding='utf-8')):
        path=ROOT/row['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise RuntimeError('更新包文件缺失/变化，请完整解压：'+row['path'])
    sys.path.insert(0,str(ROOT));sys.path.insert(1,str(ROOT/'scripts'))
    import yaml
    from video_eeg.experiment import video_runner as base
    from video_eeg.utils.video_library import load_video_library
    if base.PROJECT_ROOT.resolve()!=ROOT:
        raise RuntimeError('导入代码路径错误，未启动。')
    override=ROOT/'OLD_CONFIG.txt'
    if override.exists():
        old_path=(OLD/override.read_text(encoding='utf-8-sig').strip()).resolve()
    else:
        name='video_legacy_17_config.yaml' if (OLD/'video_eeg/config/video_legacy_17_config.yaml').is_file() else ('video_ready_config.yaml' if (OLD/'run_complete_formal.bat').exists() else 'video_config.yaml')
        old_path=OLD/'video_eeg/config'/name
    if not old_path.is_file():
        raise RuntimeError('应把整个更新文件夹放进旧程序目录；找不到 '+str(old_path))
    old=yaml.safe_load(old_path.read_text(encoding='utf-8-sig'))
    if not isinstance(old,dict) or not isinstance(old.get('protocol'),dict):
        raise RuntimeError('旧配置格式不支持，请带回报告，不要覆盖旧配置。')
    if old.get('hardware_dummy_mode',False):
        raise RuntimeError('检测到旧正式配置启用了模拟 EEG，请主试核对实际使用的正式配置。')
    library=load_video_library({**old,'_project_dir':str(OLD)})
    original_loader=base.load_config
    def local_config(path):
        cfg=original_loader(path)
        for key in ('device','device_type','sfreq','eeg_sampling_rate_hz','buffer_sec'):
            if key in old:cfg[key]=copy.deepcopy(old[key])
        demo=Path(path).name=='video_emotion_demo_config.yaml'
        cfg['hardware_dummy_mode']=demo
        cfg['demo_mode']=demo
        cfg['protocol']['video_library_dir']=str(library.root)
        cfg['protocol']['emotion_library_dir']=str(ROOT/'emotion_video')
        cfg['subject_id']='DEMO_EMOTION' if demo else 'NEW_EMOTION_001'
        cfg['storage']['records_dir']=str(OLD/'data/video_emotion_eeg_runs'/('offline_demo_v2' if demo else 'protocol_emotion_v2'))
        return cfg
    base.load_config=local_config
    print(f'旧程序（保留）：{OLD}\n读取的旧设备配置：{old_path}\n复用解释器：{sys.executable}\n普通视频：{library.root}',flush=True)
    print(f'新正式数据：{OLD / "data/video_emotion_eeg_runs/protocol_emotion_v2"}',flush=True)
    return base

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['check','demo','formal'])
    args=p.parse_args()
    for name in ('.psychopy_appdata','.tmp','logs'):(ROOT/name).mkdir(exist_ok=True)
    os.environ.update(APPDATA=str(ROOT/'.psychopy_appdata'),TEMP=str(ROOT/'.tmp'),TMP=str(ROOT/'.tmp'))
    base=configure()
    from check_video_eeg_env import check_modules,REQUIRED_MODULES
    if check_modules([pair for pair in REQUIRED_MODULES if pair[0]!='pytest']):
        raise RuntimeError('旧环境缺少所需依赖；请带回报告准备匹配的离线依赖包。未修改旧环境。')
    if args.mode=='check':
        import audit_emotion_materials
        sys.argv=[sys.argv[0]]
        code=audit_emotion_materials.main()
        if code:return code
        print('OFFLINE EMOTION CHECK PASSED：请继续 Demo 和真实设备测试。',flush=True)
        return 0
    from video_eeg.experiment import emotion_runner
    return emotion_runner.main(['--demo'] if args.mode=='demo' else ['--real-eeg'])

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f'离线检查/启动失败：{exc}\n旧程序和旧数据未被替换。',flush=True)
        raise SystemExit(1)
