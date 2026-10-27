"""Configure the approved DVC prefix; does not upload assets or read credentials."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.project_metadata import load_project_metadata


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', help='Local AWS profile; enables local authenticated upload mode')
    args = parser.parse_args(argv)
    try:
        name = load_project_metadata(ROOT / 'metadata.toml').unique_name
        if not (ROOT / '.dvc/config').is_file():
            raise ValueError('Missing shared .dvc/config')
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    def dvc(*arguments):
        subprocess.run([sys.executable, '-m', 'dvc', *arguments], cwd=ROOT, check=True)

    dvc('remote', 'add', '--force', '--default', 'nas', f's3://oi-task-assets/{name}/dvc')
    for key, value in (('endpointurl', 'http://truenas-s658v2.omni-intel.cn:9000'),
                       ('region', 'us-east-1'), ('ssl_verify', 'true'), ('allow_anonymous_login', 'true')):
        dvc('remote', 'modify', 'nas', key, value)
    if args.profile:
        dvc('remote', 'modify', '--local', 'nas', 'profile', args.profile)
        dvc('remote', 'modify', '--local', 'nas', 'allow_anonymous_login', 'false')
    print(f'Configured {name}; shared access remains anonymous read-only. No assets uploaded.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
