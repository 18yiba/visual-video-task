"""Build the additive offline Emotion EEG v2 code package (media copied separately)."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import zipfile
from build_release import source_files

ROOT=Path(__file__).resolve().parents[1]
NAME='_video_eeg_emotion_v2_update'

def build(destination):
    target=Path(destination).resolve()/NAME
    if target.exists():raise ValueError('Use a new destination; never overwrite an installed update')
    allowed=set(source_files())
    paths=[p for p in (ROOT/'video_eeg').rglob('*.py') if p in allowed]
    paths += [p for p in (ROOT/'video_eeg/config').glob('*emotion*') if p.is_file()]
    paths += [ROOT/'video_eeg/config/complete_questions_20260908/question_bank.json', ROOT/'README.md']
    paths += [ROOT/'scripts'/p for p in ('offline_emotion_update.py','check_video_eeg_env.py','audit_emotion_materials.py')]
    paths += [ROOT/'docs'/p for p in ('OFFLINE_EMOTION_V2_UPDATE.zh-CN.md','EMOTION_EEG_V2_PROTOCOL.zh-CN.md','FATIGUE_BINARY_RATIONALE.zh-CN.md')]
    for src in sorted(set(paths)):
        if '__pycache__' in src.parts:continue
        assert src in allowed,src
        dest=target/src.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
    shutil.copy2(ROOT/'docs/OFFLINE_EMOTION_V2_UPDATE.zh-CN.md',target/'离线更新操作说明.md')
    (target/'emotion_video').mkdir()
    (target/'emotion_video/把selected文件夹复制到这里.txt').write_text('从已验证情绪库复制整个 selected 文件夹到这里。完成后应为 emotion_video/selected/positive/...。不要复制 parquet 或旧实验数据。',encoding='utf-8')
    for title,mode in [('01_先检查','check'),('02_Demo','demo'),('03_正式45组','formal')]:
        text=f'''@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "PYTHON_EXE=%~dp0..\\.venv\\Scripts\\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%~dp0..\\..\\.venv\\Scripts\\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Existing Python environment not found. Keep the original program. Do not install online.
  pause
  exit /b 1
)
"%PYTHON_EXE%" "%~dp0scripts\\offline_emotion_update.py" {mode} > "%~dp0{mode}_report.txt" 2>&1
set "RESULT=%ERRORLEVEL%"
type "%~dp0{mode}_report.txt"
pause
exit /b %RESULT%
'''
        (target/(title+'.bat')).write_text(text,encoding='ascii',newline='\r\n')
    files=[dict(path=p.relative_to(target).as_posix(),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(target.rglob('*')) if p.is_file()]
    (target/'OFFLINE_FILES.json').write_text(json.dumps(files,indent=2),encoding='utf-8')
    archive=target.parent/'视频EEG_V2七级_离线更新包.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in target.rglob('*'):
            if p.is_file():z.write(p,Path(NAME)/p.relative_to(target))
    # One-click handoff lives beside the package; materials remain in video/video_materials.
    deploy_script=ROOT/'scripts/deploy_offline_emotion.ps1'
    assert deploy_script in allowed
    (target.parent/deploy_script.name).write_text(deploy_script.read_text(encoding='utf-8-sig'),encoding='utf-8-sig')
    (target.parent/'00_一键部署到实验室电脑.bat').write_text(
        '@echo off\nsetlocal\nchcp 65001 >nul\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy_offline_emotion.ps1"\npause\n',
        encoding='ascii',newline='\r\n')
    print(json.dumps(dict(archive=str(archive),bytes=archive.stat().st_size,files=len(files)),ensure_ascii=False))
    return target,archive

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination',type=Path)
    build(parser.parse_args().destination)
