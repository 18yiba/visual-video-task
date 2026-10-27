"""Unified source entry for paradigm, phase and device selection."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tomllib

from video_eeg.paths import PROJECT_ROOT


def load_settings(path: Path) -> dict:
    with path.open('rb') as handle:
        config = tomllib.load(handle)
    if set(config) != {'schema_version', 'launcher'}:
        raise ValueError('TOML requires only schema_version and [launcher]')
    if type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise ValueError('Unsupported launcher schema_version; expected integer 1')
    settings = config['launcher']
    if not isinstance(settings, dict) or set(settings) != {'protocol', 'mode'}:
        raise ValueError('[launcher] requires only protocol and mode')
    if settings['protocol'] not in ('v1', 'v2'):
        raise ValueError('launcher.protocol must be v1 or v2')
    if settings['mode'] not in ('demo', 'formal'):
        raise ValueError('launcher.mode must be demo or formal')
    return config


def validate_layout(root: Path) -> dict:
    layout = json.loads((root/'scripts/repository_layout.json').read_text(encoding='utf-8'))
    required = layout['template_layout']['required_files']
    missing = [name for name in required if not (root/name).is_file()]
    if missing:
        raise ValueError('Missing project files: ' + ', '.join(missing))
    if set(layout['public_versions']) != {'v1', 'v2'}:
        raise ValueError('The public protocol selector must contain exactly v1 and v2')
    return {'layout': 'OK', 'public_versions': ['v1', 'v2'],
            'protocol_resources': 'video_eeg/config', 'hardware_tested': False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config/config.toml'))
    parser.add_argument('--validate', action='store_true', help='Check configuration and source layout without hardware or writes')
    parser.add_argument('--run', action='store_true', help='Run the configured v1/v2 protocol and mode')
    parser.add_argument('--paradigm', '--protocol', dest='paradigm', choices=('v1', 'v2', 'v3'),
                        help='Select a paradigm (legacy alias: --protocol)')
    parser.add_argument('--mode', choices=('demo', 'formal'))
    parser.add_argument('--phase', choices=('acquisition', 'behavior-rating'),
                        help='v3 phase; v1/v2 include their rating steps in the protocol')
    parser.add_argument('--device', choices=('brainco', 'emotivpro', 'neuracle'),
                        help='EEG device; v3 accepts emotivpro or neuracle')
    args, extra = parser.parse_known_args(argv)
    if args.validate and (args.run or extra or args.paradigm or args.mode or args.phase or args.device):
        parser.error('--validate accepts only --config')
    if args.paradigm in ('v1', 'v2') and bool(args.paradigm) != bool(args.mode):
        parser.error('--paradigm and --mode must be specified together')
    if args.paradigm == 'v3' and args.mode:
        parser.error('--mode applies only to v1/v2')
    if args.phase and args.paradigm != 'v3':
        parser.error('--phase is a v3 route option')
    if args.phase and not args.device:
        parser.error('--phase requires --device for v3')
    # Configuration selection belongs to this entry point; avoid passing a second
    # configuration or acquisition switch into the protected protocol runner.
    if any(x.split('=', 1)[0] in {'--config', '--demo', '--dummy-eeg', '--real-eeg'} for x in extra):
        parser.error('Use --paradigm and --mode to select a paradigm and acquisition mode')
    try:
        path = args.config.expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT/path
        config = load_settings(path)
        report = validate_layout(PROJECT_ROOT)
        if args.validate:
            print(json.dumps({'config': str(path.resolve()), **report}, ensure_ascii=False))
            return 0
        sys.path.insert(0, str(PROJECT_ROOT/'scripts'))
        if args.paradigm == 'v3':
            if args.mode:
                parser.error('v3 has no Demo/Formal mode')
            if args.phase and args.device:
                from launch_emotion_v3 import launch_direct
                return launch_direct(args.phase, args.device, extra)
            # Older BAT invocations passed runner flags directly and did not
            # name a phase. Preserve that contract as v3 EEG acquisition.
            if extra and args.device:
                from launch_emotion_v3 import launch_direct
                return launch_direct('acquisition', args.device, extra)
            if args.phase:
                parser.error('Specify --device with --phase for a direct v3 route')
            from launch_emotion_v3 import main as launch_v3
            if args.device:
                old_backend = os.environ.get('VIDEO_EEG_BACKEND')
                os.environ['VIDEO_EEG_BACKEND'] = args.device
                try:
                    return launch_v3([])
                finally:
                    if old_backend is None:
                        os.environ.pop('VIDEO_EEG_BACKEND', None)
                    else:
                        os.environ['VIDEO_EEG_BACKEND'] = old_backend
            return launch_v3([])
        from launch_experiment import choose, launch
        if args.paradigm:
            selected = (args.paradigm, args.mode)
        elif args.run:
            selected = (config['launcher']['protocol'], config['launcher']['mode'])
        else:
            if extra:
                parser.error('Runner arguments require --run or --paradigm with --mode')
            selected = choose(default_protocol=config['launcher']['protocol'], default_mode=config['launcher']['mode'])
        if args.device:
            extra = ['--device-type', args.device, *extra]
        return launch(*selected, extra) if selected else 0
    except KeyboardInterrupt:
        return 130
    except ImportError as exc:
        print(f'实验环境缺少依赖：{exc}。请先运行 install_lab_env_uv.bat。', file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'启动失败：{exc}', file=sys.stderr)
        return 1
