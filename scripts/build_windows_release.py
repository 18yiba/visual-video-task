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

def assert_no_project_installations(site_packages):
    sys.path.insert(0, str(ROOT/'scripts'))
    from check_source_environment import project_installations
    installed = project_installations(site_packages)
    if installed:
        raise RuntimeError('Do not bundle project aliases from site-packages: '+', '.join(installed))

def main():
    p=argparse.ArgumentParser();p.add_argument('--iscc',required=True);p.add_argument('--reuse-runtime',action='store_true')
    p.add_argument('--output-dir',type=Path,default=ROOT.parent/'visual-video-package',
        help='Independent bundle and installer output directory (defaults to a sibling visual-video-package folder)')
    args=p.parse_args()
    output=args.output_dir.resolve()
    if output==ROOT or ROOT.is_relative_to(output):raise ValueError('Output must not replace the working project')
    if output.exists() and any(output.iterdir()) and not args.reuse_runtime:
        raise ValueError('Build output directory must be new and empty; refusing to overwrite existing artifacts')
    output.mkdir(parents=True,exist_ok=True)
    target=output/'VisualVideoTask'
    if target.exists() and not args.reuse_runtime:raise ValueError('Build destination exists; use a fresh build directory, do not overwrite a running app')
    target.mkdir(parents=True,exist_ok=True)
    if args.reuse_runtime:
        if not (target/'BUNDLE_MANIFEST.json').is_file():raise ValueError('Cannot reuse an unknown runtime')
        fresh=output/('source-refresh-'+str(time.time_ns()))
        rows=build_source(fresh)
        # Replace staging atomically, preserving the previous source outside the
        # bundle. Overlay copying would retain files removed from the whitelist.
        previous=target/'app'
        backup=output/('source-superseded-'+str(time.time_ns()))
        for path in (previous,backup,fresh):
            if not path.resolve().is_relative_to(output) or path.is_symlink() or path.is_junction():
                raise ValueError('Unsafe source staging path: '+str(path))
        if previous.exists():previous.rename(backup)
        fresh.rename(previous)
    else:rows=build_source(target/'app')
    # Use a standalone base, never copy a venv launcher or its absolute home.
    base=Path(sys.base_prefix)
    if not (base/'python.exe').is_file():raise RuntimeError('Build on Windows with a complete Python 3.12 installation')
    if not args.reuse_runtime:copy_runtime(base,target/'runtime')
    packages=Path(sys.prefix)/'Lib/site-packages'
    assert_no_project_installations(packages)
    if not args.reuse_runtime:
        shutil.copytree(packages,target/'runtime/Lib/site-packages',dirs_exist_ok=True,
            ignore=lambda folder,names:[n for n in names if n=='__pycache__' or n=='direct_url.json' or n.endswith(('.pyc','.pyo'))])
    # Ship official validator JS + its Deno binary locally; validation needs no network/Node.
    import importlib.metadata
    from deno import find_deno_bin
    for package, distribution in (('bids_validator_deno','bids-validator-deno'),('deno','deno'),('edfio','edfio'),
                                  ('imageio_ffmpeg','imageio-ffmpeg')):
        shutil.copytree(packages/package,target/'runtime/Lib/site-packages'/package,dirs_exist_ok=True,
            ignore=lambda folder,names:[n for n in names if n=='__pycache__' or n.endswith('.pyc')])
        dist=importlib.metadata.distribution(distribution)
        dist_path=Path(dist._path)
        shutil.copytree(dist_path,target/'runtime/Lib/site-packages'/dist_path.name,dirs_exist_ok=True)
    (target/'runtime/Scripts').mkdir(exist_ok=True)
    shutil.copy2(find_deno_bin(),target/'runtime/Scripts/deno.exe')
    for name in ('share','tcl'):
        folder=Path(sys.prefix)/name
        if folder.is_dir() and not args.reuse_runtime:shutil.copytree(folder,target/'runtime'/name,dirs_exist_ok=True)
    from PIL import Image
    icon=output/'app.ico'
    Image.open(ROOT/'assets/brand/company_logo.png').save(icon,sizes=[(16,16),(32,32),(48,48),(64,64),(128,128)])
    csc=Path(__import__('os').environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(csc),'/nologo','/target:winexe','/platform:x64','/r:System.Windows.Forms.dll',
        '/win32icon:'+str(icon),'/out:'+str(target/'VisualVideoTask.exe'),str(ROOT/'packaging/Launcher.cs')],check=True)
    shutil.copy2(ROOT/'docs/operations/WINDOWS_EXE.md',target/'离线安装与旧v1续跑说明.md')
    version=(ROOT/'packaging/version.txt').read_text().strip()
    from concurrent.futures import ThreadPoolExecutor
    def describe(path):
        with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        return {'path':path.relative_to(target).as_posix(),'bytes':path.stat().st_size,'sha256':digest}
    paths=[p for p in target.rglob('*') if p.is_file() and p != target/'BUNDLE_MANIFEST.json']
    with ThreadPoolExecutor(max_workers=8) as pool:
        files=list(pool.map(describe,paths))
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    for row in rows:
        relative=row['path']
        if relative in ('stimuli/videos/.gitkeep','data/sourcedata/.gitkeep'):
            continue
        tracked=subprocess.run(['git','show',commit+':'+relative],cwd=ROOT,capture_output=True)
        if tracked.returncode or hashlib.sha256(tracked.stdout).hexdigest()!=row['sha256']:
            raise RuntimeError('Source differs from committed release: '+relative)
    (target/'BUNDLE_MANIFEST.json').write_text(json.dumps({'version':version,'source_commit':commit,
        'device_entries':['emotivpro','neuracle'],'files':files},indent=2),encoding='utf-8')
    import os
    check_env=os.environ.copy();check_env['VIDEO_EEG_USER_DIR']=str(output/'verification/user')
    subprocess.run([str(target/'VisualVideoTask.exe'),'--self-test'],check=True,env=check_env)
    with (output/'installer_build.log').open('w',encoding='utf-8') as log:
        subprocess.run([args.iscc,'/Q','/O'+str(output),'/DAppVersion='+version,'/DSourceDir='+str(target),str(ROOT/'packaging/video-task.iss')],check=True,stdout=log,stderr=subprocess.STDOUT)
    exe=output/'VisualVideoTask-Setup-Windows-x64.exe'
    with exe.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    (output/'SHA256SUMS.txt').write_text(digest+'  '+exe.name+'\n',encoding='ascii')
    print(json.dumps({'version':version,'installer':str(exe),'bytes':exe.stat().st_size,'sha256':digest}),flush=True)

if __name__=='__main__':main()
