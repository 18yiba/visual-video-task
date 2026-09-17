"""Offline Windows desktop entry; the bundled interpreter runs this script."""
from pathlib import Path
import argparse,csv,hashlib,json,os,sys,time,traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
USER=Path(os.environ.get('VIDEO_EEG_USER_DIR',str(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'VisualVideoTask')))

def qt():
    from psychopy.gui import qtgui
    qtgui.ensureQtApp()
    return qtgui.QtWidgets

def load_settings():
    p=USER/'settings.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}

def choose_binding(settings):
    from video_eeg.utils.desktop import legacy_config,assert_legacy_idle,save_json
    W=qt();box=W.QMessageBox();box.setWindowTitle('首次设置：保留原实验进度')
    box.setText('这台电脑是否已有正在使用的v1视频实验？\n\n已有实验请绑定原程序目录。新程序读取原配置和进度，旧程序及数据保持原位。请先正常保存结束本次采集。')
    existing=box.addButton('绑定已有v1',W.QMessageBox.ButtonRole.AcceptRole)
    fresh=box.addButton('新电脑，无历史数据',W.QMessageBox.ButtonRole.ActionRole)
    box.addButton(W.QMessageBox.StandardButton.Cancel);box.exec()
    if box.clickedButton()==existing:
        directory=W.QFileDialog.getExistingDirectory(None,'选择直接包含video_eeg的原v1程序目录')
        if not directory:return False
        project=Path(directory)
        if not (project/'video_eeg').is_dir() and (project/'visual-video-task-master/video_eeg').is_dir():project=project/'visual-video-task-master'
        assert_legacy_idle(project);_,cfg=legacy_config(project)
        settings['legacy_project']=str(project.resolve())
        from video_eeg.utils.video_library import load_video_library
        settings['ordinary_root']=str(load_video_library({**cfg,'_project_dir':str(project)}).root)
    elif box.clickedButton()==fresh:
        settings.pop('legacy_project',None)
        settings.pop('ordinary_root',None)
        settings.pop('emotion_root',None)
    else:return False
    settings['configured']=True;save_json(USER/'settings.json',settings)
    return True

def verify_materials(settings,protocol):
    from video_eeg.utils.desktop import save_json
    W=qt();cache_path=USER/'material_validation.json'
    cache=json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    ordinary=Path(settings.get('ordinary_root',''))
    if not settings.get('ordinary_root') or not ordinary.is_dir():
        directory=W.QFileDialog.getExistingDirectory(None,'选择本机普通视频目录（7996段MP4，可先从移动硬盘复制）')
        if not directory:return False
        ordinary=Path(directory)
        if (ordinary/'videos').is_dir():ordinary=ordinary/'videos'
    manifest=json.loads((ROOT/'video_eeg/config/materials_manifest.json').read_text(encoding='utf-8'))
    rows=[(ordinary/Path(r['path']).name,r['sha256'],r['bytes']) for r in manifest['files']]
    if protocol=='v2':
        emotion=Path(settings.get('emotion_root',''))
        if not settings.get('emotion_root') or not (emotion/'selected').is_dir():
            directory=W.QFileDialog.getExistingDirectory(None,'选择本机情绪视频目录（包含selected，3138段视频）')
            if not directory:return False
            emotion=Path(directory)
            if emotion.name.lower()=='selected':emotion=emotion.parent
        with (ROOT/'video_eeg/config/emotion_source_index_v1.csv').open(encoding='utf-8-sig',newline='') as f:
            rows.extend((emotion/'selected'/r['relative_selected_path'],r['sha256'],None) for r in csv.DictReader(f))
        settings['emotion_root']=str(emotion.resolve())
    progress=W.QProgressDialog('首次核验视频需要读取全部材料；后续仅重验变化文件。','取消',0,len(rows))
    progress.setWindowTitle('离线材料核验');progress.setMinimumDuration(0)
    try:
        for i,(path,expected,size) in enumerate(rows):
            progress.setValue(i);W.QApplication.processEvents()
            if progress.wasCanceled():return False
            if not path.is_file():raise ValueError('缺少视频：'+str(path)+'\n请从移动硬盘补齐材料。')
            stat=path.stat();key=str(path.resolve());signature=[stat.st_size,stat.st_mtime_ns,expected]
            if size is not None and stat.st_size!=size:raise ValueError('视频大小不符：'+str(path))
            if cache.get(key)!=signature:
                with path.open('rb') as handle:actual=hashlib.file_digest(handle,'sha256').hexdigest()
                if actual!=expected:raise ValueError('视频校验失败：'+str(path)+'\n原文件未改动，请核对拷贝来源。')
                cache[key]=signature
        progress.setValue(len(rows))
    finally:progress.close()
    settings['ordinary_root']=str(ordinary.resolve())
    save_json(cache_path,cache);save_json(USER/'settings.json',settings)
    return True

def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--smoke',choices=['v1','v2','disconnect']);p.add_argument('--settings',action='store_true')
    args=p.parse_args()
    USER.mkdir(parents=True,exist_ok=True)
    for name in ('logs','tmp','psychopy'):(USER/name).mkdir(exist_ok=True)
    os.environ.update(PYTHONUTF8='1',PYTHONNOUSERSITE='1',APPDATA=str(USER/'psychopy'),TEMP=str(USER/'tmp'),TMP=str(USER/'tmp'))
    os.environ.pop('VIDEO_EEG_EMOTION_ROOT',None)
    os.chdir(ROOT)
    from psychopy import prefs
    prefs.connections['checkForUpdates']=False
    prefs.connections['allowUsageStats']=False
    if args.self_test:
        from check_video_eeg_env import check_modules
        result=check_modules(quiet=False)
        (USER/'logs/self_test.json').write_text(json.dumps({'status':'PASS' if result==0 else 'FAIL','python':sys.executable,'root':str(ROOT)}),encoding='utf-8')
        return result
    if args.smoke:
        import runpy
        if args.smoke=='disconnect':
            sys.argv=['smoke_eeg_disconnect.py'];script=ROOT/'scripts/validation/smoke_eeg_disconnect.py'
        else:
            sys.argv=['smoke_unified_entry.py','--protocol',args.smoke];script=ROOT/'scripts/validation/smoke_unified_entry.py'
        runpy.run_path(str(script),run_name='__main__');return 0
    from video_eeg.experiment import video_runner as base
    from video_eeg.utils.desktop import adapt_config,assert_legacy_idle
    from video_eeg.utils.recording_paths import recording_root
    import launch_experiment as launcher
    settings=load_settings()
    if (args.settings or not settings.get('configured')) and not choose_binding(settings):return 0
    if settings.get('legacy_project'):assert_legacy_idle(settings['legacy_project'])
    selected=launcher.choose()
    if not selected:return 0
    protocol,mode=selected
    if mode=='formal' and not verify_materials(settings,protocol):return 0
    original=base.load_config
    base.load_config=lambda path:adapt_config(original(path),path,settings,USER,ROOT)
    discovery=Path(settings['legacy_project']) if settings.get('legacy_project') else USER
    base.recording_root=lambda cfg,project,subject_id=None:recording_root(cfg,discovery,subject_id)
    if settings.get('legacy_project'):
        from video_eeg.utils.desktop import legacy_config
        _,old=legacy_config(settings['legacy_project'])
        if not old['protocol'].get('question_bank_path'):
            original_text=base.build_participant_instruction_text
            base.build_participant_instruction_text=lambda **kw:original_text(**kw).replace('部分视频结束后会随机抽查刚才的视频内容，请按题目页面提示作答。','期间保留原协议注意力判断题，请按页面提示作答。')
    return launcher.launch(protocol,mode)

if __name__=='__main__':
    USER.mkdir(parents=True,exist_ok=True);(USER/'logs').mkdir(exist_ok=True)
    log=(USER/'logs'/('launch_'+time.strftime('%Y%m%d_%H%M%S')+'.log')).open('a',encoding='utf-8',buffering=1)
    sys.stdout=sys.stderr=log
    try:raise SystemExit(main())
    except Exception as exc:
        traceback.print_exc()
        try:qt().QMessageBox.critical(None,'视频EEG启动未完成',str(exc)+'\n\n日志位置：'+str(USER/'logs'))
        except Exception:pass
        raise SystemExit(1)
