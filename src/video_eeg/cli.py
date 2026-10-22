"""Template-style entry for the existing v1/v2 launcher, with offline validation."""
from __future__ import annotations

import argparse
import json
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
    parser.add_argument('--protocol', choices=('v1', 'v2'))
    parser.add_argument('--mode', choices=('demo', 'formal'))
    args, extra = parser.parse_known_args(argv)
    if args.validate and (args.run or extra or args.protocol or args.mode):
        parser.error('--validate accepts only --config')
    if bool(args.protocol) != bool(args.mode):
        parser.error('--protocol and --mode must be specified together')
    # Configuration selection belongs to this entry point; avoid passing a second
    # configuration or acquisition switch into the protected protocol runner.
    if any(x.split('=', 1)[0] in {'--config', '--demo', '--dummy-eeg', '--real-eeg'} for x in extra):
        parser.error('Use --protocol and --mode to select protocol and acquisition mode')
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
        from launch_experiment import choose, launch
        if args.protocol:
            selected = (args.protocol, args.mode)
        elif args.run:
            selected = (config['launcher']['protocol'], config['launcher']['mode'])
        else:
            if extra:
                parser.error('Runner arguments require --run or --protocol with --mode')
            selected = choose(default_protocol=config['launcher']['protocol'], default_mode=config['launcher']['mode'])
        return launch(*selected, extra) if selected else 0
    except KeyboardInterrupt:
        return 130
    except ImportError as exc:
        print(f'实验环境缺少依赖：{exc}。请先运行 install_lab_env_uv.bat。', file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'启动失败：{exc}', file=sys.stderr)
        return 1
