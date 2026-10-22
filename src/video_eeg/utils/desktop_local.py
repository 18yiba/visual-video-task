"""Local desktop deployment: immutable config snapshots and verified data copies.

Migration never deletes a source, merges conflicting sessions, or overwrites a
destination. Runtime settings contain only local paths; source paths are audit
information, not runtime dependencies.
"""
from pathlib import Path
import copy,csv,ctypes,hashlib,json,os,shutil,time,uuid
import yaml
from video_eeg.utils.desktop import legacy_config,save_json,assert_legacy_idle

SCHEMA=2
REFERENCE_KEYS=('session_manifest_path','session_manifest','question_bank_path','formal_exclusion_report_path')

def sha256(path):
    with Path(path).open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()

def desktop_root():
    if os.name=='nt':
        buffer=ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None,0x10,None,0,buffer)==0:
            return Path(buffer.value)/'video'
    return Path.home()/'Desktop/video'

def no_links(path):
    path=Path(path).absolute()
    for part in [path,*path.parents]:
        if part.is_symlink() or part.is_junction():raise ValueError('不支持链接或junction路径，请选择真实本机目录：'+str(part))
    return path.resolve()

def require_local(path):
    path=no_links(path)
    if os.name=='nt':
        home=Path(os.environ.get('USERPROFILE',str(Path.home()))).resolve()
        if path.anchor.lower()!=home.anchor.lower() or ctypes.windll.kernel32.GetDriveTypeW(path.anchor)!=3:
            raise ValueError('运行路径必须在本机用户所在磁盘，不能使用移动硬盘或网络路径：'+str(path))
    return path

def files_under(root,exclude=()):
    root=no_links(root);exclude=[Path(p).resolve() for p in exclude]
    if not root.exists():return []
    result=[]
    for folder,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=[name for name in dirs if not any((Path(folder)/name).resolve().is_relative_to(x) for x in exclude)]
        for name in dirs:no_links(Path(folder)/name)
        for name in names:
            path=no_links(Path(folder)/name)
            if any(path.is_relative_to(x) for x in exclude):continue
            result.append(path)
    return sorted(result)

def discover_materials(lab_root,app_root,selected=None):
    """Resolve the actual leaf, including selection of the desktop/video parent."""
    lab_root=require_local(lab_root);app_root=Path(app_root)
    manifest=json.loads((app_root/'video_eeg/config/materials_manifest.json').read_text(encoding='utf-8'))
    names={Path(r['path']).name for r in manifest['files']}
    roots=[Path(selected)] if selected else [lab_root/'video_materials',lab_root/'video/_materials',lab_root/'_materials']
    candidates=[];emotion=[]
    for root in roots:
        root=require_local(root)
        if not root.is_dir():continue
        for folder,dirs,files in os.walk(root,followlinks=False):
            folder=Path(folder)
            dirs[:]=[d for d in dirs if d not in {'data','records_storage','.venv','runtime','logs','parquet_cache','_maintenance'} and not (folder/d).is_symlink() and not (folder/d).is_junction()]
            if len(folder.relative_to(root).parts)>=5:dirs[:]=[]
            if names.issubset(set(files)):candidates.append(require_local(folder));dirs[:]=[]
            if (folder/'selected').is_dir():emotion.append(require_local(folder))
            elif folder.name=='selected':emotion.append(require_local(folder.parent))
    candidates=list(dict.fromkeys(candidates));emotion=list(dict.fromkeys(emotion))
    if len(candidates)!=1:
        raise ValueError(('找到多个完整普通视频库，请明确选择其中一个。' if candidates else '未找到完整普通视频库。应包含 formal_v1/videos；请先复制到本机。')+'\n查找位置：'+'；'.join(map(str,roots)))
    result={'ordinary_root':str(candidates[0])}
    if len(emotion)==1:result['emotion_root']=str(emotion[0])
    return result

def data_candidates(project,cfg):
    project=Path(project).resolve();storage=cfg.get('storage',{})
    base=(project/storage.get('source_data_root','data/sourcedata')).resolve()
    return {
        'v1':list(dict.fromkeys([(project/storage.get('records_dir','data/sourcedata')).resolve(),base/'v1',base/'legacy17',project/'data/video_question_complete_runs'])),
        'v2':list(dict.fromkeys([base/'v2',base/'emotion-v2',project/'data/video_emotion_eeg_runs/protocol_emotion_v2'])),
    }

def copy_checked(source,dest):
    source=no_links(source);dest=Path(dest)
    if dest.exists():raise FileExistsError('拒绝覆盖已有文件：'+str(dest))
    before=sha256(source);stat=source.stat();dest.parent.mkdir(parents=True,exist_ok=True)
    with source.open('rb') as reader,dest.open('xb') as writer:shutil.copyfileobj(reader,writer,1024*1024)
    shutil.copystat(source,dest)
    if sha256(dest)!=before or sha256(source)!=before or source.stat().st_mtime_ns!=stat.st_mtime_ns:
        raise RuntimeError('复制期间文件发生变化或校验失败，请停止采集后重试：'+str(source))
    return {'source':str(source),'destination':str(dest.resolve()),'bytes':stat.st_size,'sha256':before}

def migrate(settings,user_dir,lab_root,app_root,source_project=None,progress=None):
    user_dir=require_local(user_dir);lab_root=require_local(lab_root)
    data_root=require_local(lab_root/'data/sourcedata')
    # Material discovery and free-space validation precede any copy.
    try:materials=discover_materials(lab_root,app_root,settings.get('materials_selection'))
    except ValueError:
        if not settings.get('allow_missing_materials'):raise
        materials={'ordinary_root':str(lab_root/'video_materials/formal_v1/videos'),'materials_pending':True}
    source=Path(source_project or settings.get('legacy_project') or settings.get('legacy_source','')) if (source_project or settings.get('legacy_project') or settings.get('legacy_source')) else None
    old_cfg=None;formal_path=None;plans=[];candidate_map={};roots=[]
    if source:
        source=no_links(source)
        assert_legacy_idle(source)
        formal_path,old_cfg=legacy_config(source,content_only=True)
        candidate_map=data_candidates(source,old_cfg)
        local_candidates=data_candidates(lab_root,{'storage':{}})
        for key in candidate_map:candidate_map[key]=list(dict.fromkeys(candidate_map[key]+local_candidates[key]))
        for candidates in candidate_map.values():
            for p in candidates:
                if p.is_dir() and not p.is_relative_to(data_root) and p not in roots:roots.append(no_links(p))
        # Copy each source tree once. Nested candidate paths map into that copy.
        roots=[r for r in roots if not any(r!=other and r.is_relative_to(other) for other in roots)]
    transaction=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    dest_base=data_root/'imported'/transaction
    mappings={}
    for i,root in enumerate(roots):
        destination=dest_base/f'root_{i+1:02d}'
        mappings[root]=destination
        for p in files_under(root,exclude=(data_root,)):
            plans.append((p,destination/p.relative_to(root)))
    needed=sum(p.stat().st_size for p,_ in plans)
    existing=lab_root
    while not existing.exists():existing=existing.parent
    if shutil.disk_usage(existing).free < needed+64*1024*1024:
        raise OSError(f'本机空间不足，待复制记录至少需要 {needed:,} 字节；原文件未修改。')
    journal=user_dir/'migration'/transaction
    journal.mkdir(parents=True,exist_ok=False)
    receipt={'schema':SCHEMA,'status':'copying','source_project':str(source) if source else None,'lab_root':str(lab_root),'data_root':str(data_root),'files':[]}
    save_json(journal/'receipt.json',receipt)
    new={'schema':SCHEMA,'configured':True,'lab_root':str(lab_root),'data_root':str(data_root),**materials,'migration_receipt':str(journal/'receipt.json'),'resume_roots':{'v1':[],'v2':[]}}
    if source:
        snapshot=journal/'profile';cfgdir=snapshot/'video_eeg/config';cfgdir.mkdir(parents=True)
        references={}
        for name,cfg in [('video_config.yaml',old_cfg),('video_demo_config.yaml',yaml.safe_load((source/'video_eeg/config/video_demo_config.yaml').read_text(encoding='utf-8-sig')))]:
            cfg=copy.deepcopy(cfg)
            for key in REFERENCE_KEYS:
                value=cfg.get('protocol',{}).get(key)
                if not value:continue
                origin=(source/value).resolve()
                if origin not in references:
                    target=snapshot/'references'/(f'{len(references)+1:02d}_'+origin.name)
                    receipt['files'].append(copy_checked(origin,target));references[origin]=target
                cfg['protocol'][key]=references[origin].relative_to(snapshot).as_posix()
            # The archived originals preserve bytes; only the runtime copy's
            # reference paths change. Experiment content and parameters do not.
            (cfgdir/name).write_text(yaml.safe_dump(cfg,allow_unicode=True,sort_keys=False),encoding='utf-8')
        for original in (formal_path,source/'video_eeg/config/video_demo_config.yaml'):
            receipt['files'].append(copy_checked(original,journal/'original_config'/original.name))
        new['legacy_snapshot']=str(snapshot);new['legacy_source']=str(source)
        for i,(origin,destination) in enumerate(plans):
            if progress:progress(i,len(plans),origin.name)
            receipt['files'].append(copy_checked(origin,destination))
            if i%50==0:save_json(journal/'receipt.json',receipt)
        for protocol,candidates in candidate_map.items():
            for p in candidates:
                if p.is_relative_to(data_root):target=p
                else:
                    matching=next((r for r in roots if p.is_relative_to(r)),None)
                    if matching is None:continue
                    target=mappings[matching]/p.relative_to(matching)
                if target.is_dir():new['resume_roots'][protocol].append(str(target))
        # Detect source changes after the complete copy, not just each file.
        for row in receipt['files']:
            if sha256(row['source'])!=row['sha256']:raise RuntimeError('迁移期间源文件变化，设置尚未切换：'+row['source'])
        assert_legacy_idle(source)
    receipt['status']='verified';receipt['copied_files']=len(receipt['files'])
    save_json(journal/'receipt.json',receipt)
    previous=user_dir/'settings.json'
    if previous.exists():copy_checked(previous,journal/'previous_settings.json')
    if new.get('legacy_snapshot'):
        new['snapshot_sha256']={p.relative_to(Path(new['legacy_snapshot'])).as_posix():sha256(p) for p in files_under(new['legacy_snapshot'])}
    save_json(previous,new)
    return new

def validate_runtime(settings,user_dir,app_root,formal=False):
    if settings.get('schema')!=SCHEMA:raise ValueError('请先完成本机路径设置。')
    if settings.get('legacy_source'):assert_legacy_idle(settings['legacy_source'])
    for p in (user_dir,app_root,settings['lab_root'],settings['data_root']):require_local(p)
    if settings.get('legacy_snapshot'):
        snapshot=require_local(settings['legacy_snapshot']);legacy_config(snapshot,content_only=True)
        for relative,expected in settings.get('snapshot_sha256',{}).items():
            path=(snapshot/relative).resolve()
            if not path.is_relative_to(snapshot) or sha256(path)!=expected:raise ValueError('本机协议快照被改动，请保留现场排查：'+str(path))
    for roots in settings.get('resume_roots',{}).values():
        for p in roots:require_local(p)
    if formal:
        for key in ('ordinary_root','emotion_root'):
            if settings.get(key):require_local(settings[key])

def local_recording_root(config,settings,subject_id=None):
    from video_eeg.utils.recording_paths import recording_root
    root=require_local(settings['data_root'])
    key=config.get('_unified_protocol')
    if config.get('demo_mode'):return root/'demo'/key
    subject=str(subject_id or config.get('subject_id','S001')).strip()
    if not subject or subject in {'.','..'} or any(c in subject for c in '/\\:*?"<>|'):raise ValueError('被试编号含非法路径字符。')
    candidates=[root/key,root] if key=='v1' else [root/key]
    candidates += [Path(p) for p in settings.get('resume_roots',{}).get(key,[])]
    candidates=list(dict.fromkeys(require_local(p) for p in candidates))
    found=[p for p in candidates if any((p/subject).glob('session_*/session_state.json')) or any((p/subject).glob('run_*/session_*/session_state.json'))]
    if len(found)>1:raise RuntimeError('同一被试存在多份进度，不能自动合并或覆盖。请核对迁移报告：\n'+'\n'.join(map(str,found)))
    return found[0] if found else root/key

def inventory_paths(root):
    root=no_links(root);result=[]
    for folder,dirs,names in os.walk(root,followlinks=False):
        for name in list(dirs):
            path=Path(folder)/name
            if path.is_symlink() or path.is_junction():
                result.append(path);dirs.remove(name)
        result.extend(Path(folder)/name for name in names)
    return sorted(result)

def dependency_report(settings,user_dir,app_root):
    """List actual external runtime files individually; keep old files by default."""
    validate_runtime(settings,user_dir,app_root)
    folder=Path(user_dir)/'reports';folder.mkdir(parents=True,exist_ok=True)
    used=[]
    for label,root in [('配置快照',settings.get('legacy_snapshot')),('普通视频',settings.get('ordinary_root')),('情绪视频',str(Path(settings['emotion_root'])/'selected') if settings.get('emotion_root') else None),('全部数据与进度',settings['data_root'])]:
        if root:
            used.extend({'category':label,'path':str(p),'action':'保留'} for p in files_under(root))
    with (folder/'当前依赖逐文件.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['category','path','action']);writer.writeheader();writer.writerows(used)
    source=Path(settings['legacy_source']) if settings.get('legacy_source') else None
    plan={'source_root':str(source) if source else None,'files':[],'note':'仅自动归档已核验缓存；旧源码、环境、配置及未知文件保留用于回退，不等于可删除。'}
    if source and source.exists():
        for p in inventory_paths(source):
            parts=p.relative_to(source).parts
            protected=p.is_symlink() or p.is_junction() or any(x.lower() in {'data','records_storage','video_materials','_materials','.venv','runtime','third_party'} for x in parts) or p.suffix.lower() in {'.mp4','.npy','.edf','.bdf','.fif'} or 'session_state' in p.name
            cache=not protected and (('__pycache__' in parts and p.suffix.lower() in {'.pyc','.pyo'}) or ('.pytest_cache' in parts and p.name in {'nodeids','lastfailed','stepwise','CACHEDIR.TAG','.gitignore','README.md'}))
            plan['files'].append({'path':str(p),'relative':p.relative_to(source).as_posix(),'action':'可归档缓存' if cache else '保留原件/回退/待人工核对','sha256':sha256(p) if cache else ''})
    elif (folder/'旧目录整理计划.json').is_file():
        previous=json.loads((folder/'旧目录整理计划.json').read_text(encoding='utf-8'))
        if previous.get('source_root')==plan['source_root']:plan=previous
    plan['source_available']=bool(source and source.exists())
    save_json(folder/'旧目录整理计划.json',plan)
    with (folder/'旧目录逐文件清单.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['path','relative','action','sha256']);writer.writeheader();writer.writerows(plan['files'])
    return folder

def archive_caches(settings,user_dir,app_root):
    report=dependency_report(settings,user_dir,app_root)
    plan=json.loads((report/'旧目录整理计划.json').read_text(encoding='utf-8'))
    source=Path(plan['source_root']) if plan['source_root'] else None
    if not source:return 0
    if not source.exists():raise ValueError('源目录未连接，仅保留上次清单，未执行归档。')
    source=no_links(source);assert_legacy_idle(source)
    destination=require_local(Path(settings['lab_root'])/'_archive'/('cache_'+uuid.uuid4().hex))
    moved=[]
    for row in plan['files']:
        if row['action']!='可归档缓存':continue
        path=no_links(row['path']);target=destination/row['relative']
        if not path.is_relative_to(source) or not target.resolve().is_relative_to(destination):raise ValueError('归档路径越界。')
        if sha256(path)!=row['sha256']:raise RuntimeError('缓存已变化，停止归档：'+str(path))
        # Verified copy first; unlink only this checked cache file, never a tree.
        copied=copy_checked(path,target);path.unlink();moved.append(copied)
        save_json(destination/'恢复清单.json',moved)
    return len(moved)

def drive_report(letter,user_dir):
    import psutil
    anchor=letter.rstrip('\\/').upper()
    if len(anchor)!=2 or anchor[1]!=':' or not anchor[0].isalpha():raise ValueError('请输入盘符，例如E:')
    rows=[];denied=0
    for proc in psutil.process_iter(['pid','name']):
        try:
            paths=[proc.exe(),proc.cwd()]+[f.path for f in proc.open_files()]
            matches=[p for p in paths if p.upper().startswith(anchor+'\\')]
            if matches:rows.append({'pid':proc.pid,'name':proc.info['name'],'paths':matches})
        except (psutil.AccessDenied,psutil.NoSuchProcess):denied+=1
    report={'drive':anchor,'processes':rows,'inaccessible_processes':denied,'limitation':'仅检查可读取的进程文件、程序和工作目录，不能覆盖全部内核句柄；不自动结束任何进程。'}
    path=Path(user_dir)/'reports/硬盘占用.json';save_json(path,report)
    return path
