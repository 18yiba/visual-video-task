"""Bundle a complete, relocatable CPython runtime; no Python/uv on target PCs."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/maintenance'))
from build_release import build as build_source

def copy_runtime(source,target):
    def ignored(folder,names):
        # Keep runtime libraries, codecs and package data. Drop only caches and
        # installation provenance containing the development machine's paths.
        return [n for n in names if n=='__pycache__' or n.endswith(('.pyc','.pyo')) or n=='direct_url.json']
    shutil.copytree(source,target,ignore=ignored)

def main():
    p=argparse.ArgumentParser();p.add_argument('--iscc',required=True);p.add_argument('--reuse-runtime',action='store_true');args=p.parse_args()
    target=ROOT/'dist/VisualVideoTask'
    if target.exists() and not args.reuse_runtime:raise ValueError('Build destination exists; use a fresh build directory, do not overwrite a running app')
    target.mkdir(parents=True,exist_ok=True)
    if args.reuse_runtime:
        if not (target/'BUNDLE_MANIFEST.json').is_file():raise ValueError('Cannot reuse an unknown runtime')
        fresh=ROOT/'dist'/('source-refresh-'+str(time.time_ns()))
        rows=build_source(fresh)
        # Replace staging atomically, preserving the previous source outside the
        # bundle. Overlay copying would retain files removed from the whitelist.
        previous=target/'app'
        backup=ROOT/'dist'/('source-superseded-'+str(time.time_ns()))
        for path in (previous,backup,fresh):
            if not path.resolve().is_relative_to((ROOT/'dist').resolve()) or path.is_symlink() or path.is_junction():
                raise ValueError('Unsafe source staging path: '+str(path))
        if previous.exists():previous.rename(backup)
        fresh.rename(previous)
    else:build_source(target/'app')
    # Use a standalone base, never copy a venv launcher or its absolute home.
    base=Path(sys.base_prefix)
    if not (base/'python.exe').is_file():raise RuntimeError('Build on Windows with a complete Python 3.12 installation')
    if not args.reuse_runtime:copy_runtime(base,target/'runtime')
    packages=Path(sys.prefix)/'Lib/site-packages'
    if not args.reuse_runtime:
        shutil.copytree(packages,target/'runtime/Lib/site-packages',dirs_exist_ok=True,
            ignore=lambda folder,names:[n for n in names if n=='__pycache__' or n=='direct_url.json' or n.endswith(('.pyc','.pyo'))])
    for name in ('share','tcl'):
        folder=Path(sys.prefix)/name
        if folder.is_dir() and not args.reuse_runtime:shutil.copytree(folder,target/'runtime'/name,dirs_exist_ok=True)
    from PIL import Image
    Image.open(ROOT/'assets/brand/company_logo.png').save(ROOT/'packaging/app.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128)])
    csc=Path(__import__('os').environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(csc),'/nologo','/target:winexe','/platform:x64','/r:System.Windows.Forms.dll',
        '/win32icon:'+str(ROOT/'packaging/app.ico'),'/out:'+str(target/'VisualVideoTask.exe'),str(ROOT/'packaging/Launcher.cs')],check=True)
    shutil.copy2(ROOT/'docs/operations/WINDOWS_EXE.md',target/'离线安装与旧v1续跑说明.md')
    version=(ROOT/'packaging/version.txt').read_text().strip()
    files=[]
    for path in target.rglob('*'):
        if path.is_file() and path != target/'BUNDLE_MANIFEST.json':
            with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
            files.append({'path':path.relative_to(target).as_posix(),'bytes':path.stat().st_size,'sha256':digest})
    (target/'BUNDLE_MANIFEST.json').write_text(json.dumps({'version':version,'files':files},indent=2),encoding='utf-8')
    subprocess.run([str(target/'VisualVideoTask.exe'),'--self-test'],check=True)
    with (ROOT/'dist/installer_build.log').open('w',encoding='utf-8') as log:
        subprocess.run([args.iscc,'/Q','/DAppVersion='+version,'/DSourceDir='+str(target),str(ROOT/'packaging/video-task.iss')],check=True,stdout=log,stderr=subprocess.STDOUT)
    exe=ROOT/'dist/VisualVideoTask-Setup-Windows-x64.exe'
    with exe.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    (ROOT/'dist/SHA256SUMS.txt').write_text(digest+'  '+exe.name+'\n',encoding='ascii')
    print(json.dumps({'version':version,'installer':str(exe),'bytes':exe.stat().st_size,'sha256':digest}),flush=True)

if __name__=='__main__':main()
