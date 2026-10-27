"""Deployment identity only; never rewrites acquisition identities or snapshots."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import argparse
import json
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ProjectMetadata:
    full_name: str
    unique_name: str
    description: str


def load_project_metadata(path: Path | None = None) -> ProjectMetadata:
    with (path or ROOT / 'metadata.toml').open('rb') as handle:
        data = tomllib.load(handle)
    if set(data) != {'full_name', 'unique_name', 'description'}:
        raise ValueError('metadata.toml requires exactly full_name, unique_name, description')
    if any(not isinstance(value, str) or not value.strip() or value != value.strip()
           for value in data.values()):
        raise ValueError('Metadata values must be nonempty strings without surrounding whitespace')
    name = data['unique_name']
    if not re.fullmatch(r'[A-Z]{1,6}-[0-9]{8}', name):
        raise ValueError('unique_name must match AAAAAA-YYYYMMDD (1-6 uppercase letters)')
    datetime.strptime(name.split('-')[1], '%Y%m%d')
    if name == 'ACQTPL-20261022':
        raise ValueError('Replace the template unique_name with the approved project identity')
    return ProjectMetadata(**data)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', type=Path)
    parser.add_argument('--unique-name', action='store_true')
    args = parser.parse_args(argv)
    try:
        metadata = load_project_metadata(args.path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Invalid project metadata: {exc}\n')
    print(metadata.unique_name if args.unique_name else json.dumps(metadata.__dict__, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
