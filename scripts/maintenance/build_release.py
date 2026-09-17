"""Build a source-only, relocatable distribution using an explicit allowlist."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
FOLDERS = ('video_eeg', 'scripts', 'tests', 'docs', 'vendor', 'packaging', '.github')
SUFFIXES = {'.py', '.ps1', '.bat', '.md', '.txt', '.toml', '.yaml', '.yml', '.json', '.csv', '.docx', '.cs', '.iss', '.isl'}
FILES = ('README.md', 'AGENTS.md', 'pyproject.toml', 'setup.py', 'lab_uv_env.toml', 'uv.toml',
         'requirements-psychopy.txt', '.gitignore', '.gitattributes', 'THIRD_PARTY_NOTICES.md',
         'assets/brand/company_logo.png')
PLACEHOLDERS = ('stimuli/videos/.gitkeep', 'data/sourcedata/.gitkeep')
ROOT_BATS = ('run_experiment.bat', 'install_lab_env_uv.bat', 'download_materials.bat')
# Superseded deployment/history documents remain local; the current operator manual replaces them.
EXCLUDED = {'docs/CHANGELOG_LAB_ENV.md', 'docs/ENVIRONMENT_SETUP.md',
            'docs/SESSION_AUDIT_20260905.md', 'docs/VIDEO_QUESTION_AUDIT_20260908.md',
            'scripts/materialize_session_folders.py', 'scripts/verify_session_randomness.py',
            # Replaced manuals and unused pre-integration helpers; see cleanup record.
            'docs/CONFIGURATION.md', 'docs/DATA_MODEL.md', 'docs/EXPERIMENT_FLOW.md',
            'docs/IMPLEMENTATION.md', 'docs/INSTRUCTION.md',
            'docs/视频EEG_实验说明.docx', 'docs/视频EEG_详细操作说明.docx',
            'scripts/export_manual_docx.py',
            'video_eeg/utils/preprocessing.py', 'video_eeg/utils/session_store.py',
            'video_eeg/utils/stream_writer.py'}


def source_files():
    layout = json.loads((ROOT/'scripts/repository_layout.json').read_text(encoding='utf-8'))
    excluded = EXCLUDED | set(layout['retired'])
    result = []
    for folder in FOLDERS:
        for p in (ROOT / folder).rglob('*'):
            if not p.is_file() or p.is_symlink():
                continue
            parts=p.relative_to(ROOT).parts
            if any(part in {'__pycache__','build','dist','.pytest_cache'} or part.endswith(('.egg-info','.dist-info')) for part in parts):
                continue
            if p.relative_to(ROOT).as_posix() in excluded:
                continue
            if p.suffix.lower() in SUFFIXES or p.name == 'LICENSE':
                result.append(p)
    result.extend(ROOT / f for f in FILES if (ROOT / f).is_file())
    result.extend(ROOT / p for p in ROOT_BATS if (ROOT/p).is_file())
    result.extend(ROOT / f for f in PLACEHOLDERS if (ROOT / f).is_file())
    return sorted(set(result))


def build(destination):
    destination = destination.resolve()
    if destination == ROOT or ROOT.is_relative_to(destination):
        raise ValueError('Release destination must not replace the working project')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Use a new empty release destination')
    destination.mkdir(parents=True, exist_ok=True)
    manifest = []
    for p in source_files():
        relative = p.relative_to(ROOT)
        if relative.as_posix() in PLACEHOLDERS and p.stat().st_size:
            raise ValueError('Published data/material placeholders must be empty')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        manifest.append(dict(path=relative.as_posix(), bytes=p.stat().st_size,
            sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    (destination / 'SOURCE_MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--zip', type=Path)
    args = parser.parse_args()
    manifest = build(args.destination)
    if args.zip:
        args.zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.zip, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in args.destination.rglob('*'):
                if p.is_file():
                    z.write(p, Path('visual-video-task') / p.relative_to(args.destination))
    print(f'Packaged {len(manifest)} source files; no participant data, videos, environments or caches.')


if __name__ == '__main__':
    main()
