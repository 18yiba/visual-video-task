"""Read-only check for obsolete installations of this project."""
import importlib.metadata
from pathlib import Path
import re
import sys


PROJECT_DISTRIBUTIONS = {'video-eeg', 'acq-task-template'}
PROJECT_ENTRYPOINTS = {'video-eeg', 'acq-task'}


def project_installations(site_packages: Path) -> list[str]:
    found = []
    for dist in importlib.metadata.distributions(path=[str(site_packages)]):
        name = re.sub(r'[-_.]+', '-', dist.metadata.get('Name', '')).lower()
        if name in PROJECT_DISTRIBUTIONS:
            found.append(f'{name} {dist.version}')
        if any(re.sub(r'[-_.]+', '-', ep.name).lower() in PROJECT_ENTRYPOINTS
               for ep in dist.entry_points):
            found.append(f'{name} console entry')
    for path in site_packages.iterdir():
        normalized = re.sub(r'[-.]+', '_', path.name).lower()
        if path.suffix.lower() in {'.pth', '.egg-link'} and any(
                name in normalized for name in ('video_eeg', 'acq_task')):
            found.append(path.name)
    return sorted(set(found))


def main() -> int:
    site_packages = Path(sys.prefix) / ('Lib/site-packages' if sys.platform == 'win32'
                                      else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
    found = project_installations(site_packages)
    if found:
        print('Obsolete project installation found; recreate this project environment: '
              + ', '.join(found), file=sys.stderr)
        return 1
    print('No obsolete project installation detected.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
