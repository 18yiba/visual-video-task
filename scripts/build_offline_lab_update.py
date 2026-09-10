"""Build an additive lab update; no installer, environment, video or acquisition data."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = '_video_eeg_34_update'


def build(destination):
    target = destination / NAME
    if target.exists():
        raise ValueError('Use a new empty destination; do not overwrite an installed update')
    paths = list((ROOT / 'video_eeg').rglob('*.py'))
    configs = ['video_config.yaml', 'video_demo_config.yaml', 'session_manifest_34.csv',
        'formal_excluded_over_60s.csv', 'materials_manifest.json',
        'complete_questions_20260908/question_bank.json']
    paths += [ROOT / 'video_eeg/config' / p for p in configs]
    paths += [ROOT / 'scripts' / p for p in ['offline_lab_update.py', 'check_video_eeg_env.py']]
    for p in paths:
        relative = p.relative_to(ROOT)
        out = target / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
    for title, mode in [('01_先检查', 'check'), ('02_Demo', 'demo'), ('03_正式34组', 'formal')]:
        bat = f'''@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "PYTHON_EXE=%~dp0..\\.venv\\Scripts\\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%~dp0..\\..\\.venv\\Scripts\\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Cannot find the original lab Python environment. Do not run an online installer.
  pause
  exit /b 1
)
"%PYTHON_EXE%" "%~dp0scripts\\offline_lab_update.py" {mode} > "%~dp0{title}_报告.txt" 2>&1
set "RESULT=%ERRORLEVEL%"
type "%~dp0{title}_报告.txt"
pause
exit /b %RESULT%
'''
        # Use ASCII names internally so cmd.exe does not depend on a Chinese codepage.
        bat = bat.replace(f'{title}_报告.txt', f'{mode}_report.txt')
        (target / f'{title}.bat').write_text(bat, encoding='ascii', newline='\r\n')
    shutil.copy2(ROOT / 'docs/OFFLINE_LAB_UPDATE.zh-CN.md', target / '离线更新操作说明.md')
    (target / 'docs').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'docs/OFFLINE_UPDATE_VALIDATION.md', target / 'docs/OFFLINE_UPDATE_VALIDATION.md')
    word = ROOT / 'docs/视频EEG_离线最小更新操作说明.docx'
    if word.exists():
        shutil.copy2(word, target / word.name)
    rows = [dict(path=p.relative_to(target).as_posix(), bytes=p.stat().st_size,
                 sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(target.rglob('*')) if p.is_file()]
    (target / 'OFFLINE_FILES.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    archive = destination / '视频EEG_34组_离线最小更新包.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in target.rglob('*'):
            if p.is_file():
                z.write(p, Path(NAME) / p.relative_to(target))
    print(f'Created: {archive}\nSize: {archive.stat().st_size / 1024**2:.2f} MiB; only adds {NAME}; no old files replaced.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    build(parser.parse_args().destination)
