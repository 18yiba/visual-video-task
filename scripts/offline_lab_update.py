"""Run an additive offline update using the existing lab environment and materials."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT.parent


def configure():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('旧环境不是 Python 3.12。请保留旧程序，将检查报告带回联网电脑准备离线环境包。')
    manifest_path = ROOT / 'OFFLINE_FILES.json'
    if not manifest_path.is_file():
        raise RuntimeError('请使用完整离线更新包运行本脚本。')
    for row in json.loads(manifest_path.read_text(encoding='utf-8')):
        path = ROOT / row['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError('更新文件缺失或损坏，请重新完整解压：' + row['path'])
    sys.path.insert(0, str(ROOT))
    sys.path.insert(1, str(ROOT / 'scripts'))
    import yaml
    from video_eeg.experiment import video_runner as base
    from video_eeg.utils.video_library import load_video_library
    if base.PROJECT_ROOT.resolve() != ROOT.resolve():
        raise RuntimeError('导入的不是更新包代码，停止启动。')
    old_path = OLD / 'video_eeg/config/video_config.yaml'
    if not old_path.is_file():
        raise RuntimeError('放置位置不对：更新文件夹应放在原主程序目录内，与原 video_eeg 文件夹并列。')
    old = yaml.safe_load(old_path.read_text(encoding='utf-8-sig'))
    if not isinstance(old, dict) or not isinstance(old.get('protocol'), dict):
        raise RuntimeError('旧配置格式不兼容，请带回检查报告，不要覆盖原配置。')
    if old.get('hardware_dummy_mode', False):
        raise RuntimeError('旧正式配置启用了模拟 EEG，请先由主试核对原设备配置；未修改任何旧文件。')
    library = load_video_library({**old, '_project_dir': str(OLD)})
    original_loader = base.load_config

    def local_config(path):
        config = original_loader(path)
        for key in ('device', 'device_type', 'sfreq', 'eeg_sampling_rate_hz', 'buffer_sec'):
            if key in old:
                config[key] = copy.deepcopy(old[key])
        config['protocol']['video_library_dir'] = str(library.root)
        demo = Path(path).name == 'video_demo_config.yaml'
        config['hardware_dummy_mode'] = demo
        config['subject_id'] = 'DEMO_OFFLINE' if demo else 'NEW34_001'
        config['storage']['records_dir'] = str(OLD / ('data/offline_upgrade_demo' if demo else
            'data/video_question_complete_runs/protocol_34sessions'))
        return config

    base.load_config = local_config
    config = local_config(ROOT / 'video_eeg/config/video_config.yaml')
    manifest = base.SessionManifest.load(ROOT / config['protocol']['session_manifest_path'], session_count=34)
    sizes = {Path(r['path']).name: r['bytes'] for r in
             json.loads((ROOT / 'video_eeg/config/materials_manifest.json').read_text(encoding='utf-8'))['files']}
    problems = []
    for entry in manifest.entries:
        p = library.root / entry.video_path
        if not p.is_file():
            problems.append('缺少 ' + entry.video_path)
        elif p.stat().st_size != sizes[entry.video_path]:
            problems.append('大小不匹配 ' + entry.video_path)
    if problems:
        (ROOT / '缺失或不匹配的视频.txt').write_text('\n'.join(problems), encoding='utf-8-sig')
        raise RuntimeError(f'视频库有 {len(problems)} 个问题；详见更新文件夹内“缺失或不匹配的视频.txt”。实际目录：{library.root}')
    from video_eeg.experiment.ready_question_runner import load_questions
    from video_eeg.utils.session_protocol import build_video_question_schedule
    questions = load_questions(ROOT / config['protocol']['question_bank_path'])
    for sid in range(1, 35):
        assert len(build_video_question_schedule(manifest.session_assets(sid), questions, task_count=18, random_seed=sid)) == 18
    print(f'旧程序保留：{OLD}\n复用视频：{library.root}\n复用解释器：{sys.executable}')
    print(f'新版正式数据：{config["storage"]["records_dir"]}')
    print('34 组 / 每组 18 抽查 / 7949 段正式视频文件名和大小检查通过。')
    return base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['check', 'demo', 'formal'])
    args = parser.parse_args()
    for name in ('.psychopy_appdata', '.tmp', 'logs'):
        (ROOT / name).mkdir(exist_ok=True)
    os.environ.update(APPDATA=str(ROOT / '.psychopy_appdata'), TEMP=str(ROOT / '.tmp'), TMP=str(ROOT / '.tmp'))
    base = configure()
    from check_video_eeg_env import check_modules, REQUIRED_MODULES
    if check_modules([pair for pair in REQUIRED_MODULES if pair[0] != 'pytest']):
        raise RuntimeError('现有环境缺少新版运行依赖。请把检查报告带回联网电脑；旧环境未重装或修改。')
    if args.mode == 'check':
        print('OFFLINE CHECK PASSED：可以先运行 02_Demo，再用 03_正式34组开始新实验。')
        return 0
    return base.main(['--demo'] if args.mode == 'demo' else ['--real-eeg'])


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'离线更新检查/启动失败：{exc}', flush=True)
        raise SystemExit(1)
