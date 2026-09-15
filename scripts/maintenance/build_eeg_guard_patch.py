"""Build a code-only safety patch preserving installed configs and session state."""
from pathlib import Path
import hashlib,json,shutil,sys
from build_release import source_files,ROOT

def build(destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Use a new destination')
    destination.mkdir(parents=True)
    rows=[]
    for p in source_files():
        rel=p.relative_to(ROOT)
        if not (rel.parts[0]=='video_eeg' and p.suffix=='.py') and rel.as_posix()!='assets/brand/company_logo.png':continue
        target=destination/'payload'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
        rows.append(dict(path=rel.as_posix(),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    (destination/'PATCH_FILES.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    script=ROOT/'scripts/apply_eeg_guard_patch.ps1'
    (destination/script.name).write_text(script.read_text(encoding='utf-8-sig'),encoding='utf-8-sig')
    (destination/'安装断流保护.bat').write_text('@echo off\nchcp 65001 >nul\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0apply_eeg_guard_patch.ps1"\npause\n',encoding='ascii',newline='\r\n')
    shutil.copy2(ROOT/'docs/operations/EEG_AND_RECOVERY.md',destination/'断流保护_安装与排查说明.md')
    print(json.dumps(dict(path=str(destination),runtime_files=len(rows),bytes=sum(p.stat().st_size for p in destination.rglob('*') if p.is_file())),ensure_ascii=False))

if __name__=='__main__':build(sys.argv[1])
