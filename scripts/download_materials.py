"""Download the pinned public corpus and verify every video before use."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def download(url, target, expected, size):
    if target.exists() and target.stat().st_size == size and sha256(target) == expected:
        return
    part = target.with_suffix(target.suffix + '.part')
    for attempt in range(5):
        try:
            offset = part.stat().st_size if part.exists() else 0
            if offset >= size:
                if offset == size and sha256(part) == expected:
                    part.replace(target)
                    return
                part.unlink()
                offset = 0
            headers = {'User-Agent': 'visual-video-task-materials/1'}
            if offset:
                headers['Range'] = f'bytes={offset}-'
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=90) as response:
                resumed = offset > 0 and response.status == 206
                if resumed and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                    raise ValueError('Unexpected server download range')
                with part.open('ab' if resumed else 'wb') as f:
                    shutil.copyfileobj(response, f, 1024 * 1024)
            if part.stat().st_size != size or sha256(part) != expected:
                part.unlink()
                raise ValueError('Downloaded archive checksum mismatch')
            part.replace(target)
            return
        except (OSError, ValueError) as exc:
            print(f'Download retry {attempt + 1}/5: {exc}', flush=True)
            if attempt == 4:
                raise
            time.sleep(3)


def install_archive(archive, destination, rows):
    # Only manifest-listed videos may be extracted. Existing differing files are preserved.
    with zipfile.ZipFile(archive) as z:
        if set(z.namelist()) != {r['path'] for r in rows}:
            raise ValueError('Archive contents differ from manifest')
        for row in rows:
            relative = Path(row['path'])
            if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != 'videos':
                raise ValueError('Unsafe material path')
            target = destination / relative
            if target.exists():
                if target.stat().st_size == row['bytes'] and sha256(target) == row['sha256']:
                    continue
                raise ValueError(f'Existing video differs; preserve and relocate it before retrying: {target}')
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix('.mp4.downloading')
            with z.open(row['path']) as source, temp.open('wb') as out:
                shutil.copyfileobj(source, out, 1024 * 1024)
            if temp.stat().st_size != row['bytes'] or sha256(temp) != row['sha256']:
                temp.unlink()
                raise ValueError(f'Extracted video failed verification: {relative}')
            temp.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-pause', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--keep-archives', action='store_true')
    parser.add_argument('--destination', type=Path, default=ROOT / 'stimuli', help='Parent of videos directory')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'video_eeg/config/materials_manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['metadata'].items():
        if sha256(ROOT / 'video_eeg/config' / name) != expected:
            raise ValueError('Source configuration does not match pinned materials: ' + name)
    destination = args.destination.resolve()
    rows_by_asset = {}
    missing = []
    for row in manifest['files']:
        target = destination / row['path']
        valid = target.is_file() and target.stat().st_size == row['bytes'] and sha256(target) == row['sha256']
        if not valid:
            if target.exists():
                raise ValueError(f'Existing video checksum mismatch; file was not changed: {target}')
            missing.append(row)
        rows_by_asset.setdefault(row['asset'], []).append(row)
    if args.verify_only:
        if missing:
            raise ValueError(f'Missing {len(missing)} videos; first: {missing[0]["path"]}')
    elif missing:
        destination.mkdir(parents=True, exist_ok=True)
        required = sum(r['bytes'] for r in missing) + 2 * 1024**3
        if shutil.disk_usage(destination).free < required:
            raise ValueError(f'Need at least {required / 1024**3:.1f} GiB free')
        cache = ROOT / '.materials_download'
        cache.mkdir(exist_ok=True)
        needed = {r['asset'] for r in missing}
        assets = [a for a in manifest['assets'] if a['name'] in needed]
        base = f'https://github.com/{manifest["repository"]}/releases/download/{manifest["version"]}/'
        for i, asset in enumerate(assets, 1):
            print(f'[{i}/{len(assets)}] Download/verify/extract {asset["name"]}', flush=True)
            archive = cache / asset['name']
            download(base + asset['name'], archive, asset['sha256'], asset['bytes'])
            install_archive(archive, destination, rows_by_asset[asset['name']])
            if not args.keep_archives:
                archive.unlink()
    print(f'Verified {manifest["video_count"]} videos in {destination / "videos"}.', flush=True)
    print('Question bank: 7993 questions; 5728.mp4, 6722.mp4, 6883.mp4 are not sampled.')
    print('Formal: 7949 videos, 34 Sessions (~88.76 net minutes), 18 checks each. Demo: 10 videos, 3 checks.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Materials setup failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
