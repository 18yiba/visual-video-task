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
    from video_eeg.utils.desktop_local import desktop_root,migrate,discover_materials
    W=qt();box=W.QMessageBox();box.setWindowTitle('设置实验室本机路径')
    lab=desktop_root()
    box.setText('请先正常结束并保存采集。\n本次把配置与已有记录复制、校验到本机，原件不删除。\n\n视频：'+str(lab/'video_materials')+'\n数据：'+str(lab/'data/sourcedata')+'\n\n完成后运行不再依赖移动硬盘。')
    existing=box.addButton('迁移内容题版v1到本机',W.QMessageBox.ButtonRole.AcceptRole)
    fresh=box.addButton('新电脑，无历史数据',W.QMessageBox.ButtonRole.ActionRole)
    box.addButton(W.QMessageBox.StandardButton.Cancel);box.exec()
    if box.clickedButton()==existing:
        directory=W.QFileDialog.getExistingDirectory(None,'选择实际采集所用旧v1目录（含video_eeg，可从硬盘迁移）',settings.get('legacy_project',settings.get('legacy_source',str(lab))))
        if not directory:return False
        source=Path(directory)
        if not (source/'video_eeg').is_dir() and (source/'visual-video-task-master/video_eeg').is_dir():source=source/'visual-video-task-master'
    elif box.clickedButton()==fresh:source=None
    else:return False
    selection={}
    try:discover_materials(lab,ROOT)
    except ValueError:
        directory=W.QFileDialog.getExistingDirectory(None,'选择本机视频材料目录，可选video_materials或其上级目录',str(lab))
        if directory:selection['materials_selection']=directory
        else:
            answer=W.QMessageBox.question(None,'尚未选择正式材料','是否先迁移配置和记录，只做Demo？正式实验仍须选择并核验本机视频库。')
            if answer!=W.QMessageBox.StandardButton.Yes:return False
            selection['allow_missing_materials']=True
    progress=W.QProgressDialog('正在复制并校验历史记录；原文件不删除。',None,0,100)
    progress.setWindowTitle('迁移到实验室本机');progress.setMinimumDuration(0)
    def update(i,total,name):
        progress.setValue(int(100*i/max(total,1)));progress.setLabelText('复制并校验：'+name);W.QApplication.processEvents()
    try:new=migrate(selection,USER,lab,ROOT,source_project=source,progress=update)
    finally:progress.close()
    settings.clear();settings.update(new)
    from video_eeg.utils.desktop_local import dependency_report
    try:dependency_report(settings,USER,ROOT)
    except (OSError,ValueError) as exc:print('迁移完成，盘点报告暂未生成：'+str(exc),flush=True)
    W.QMessageBox.information(None,'本机设置完成','新记录保存根目录：'+new['data_root']+'\n旧记录已按字节校验复制或保留在本机，原件未删除。\n开始菜单“视频EEG文件盘点”可导出逐文件清单。')
    return True

def verify_materials(settings,protocol):
    from video_eeg.utils.desktop import save_json
    from video_eeg.utils.desktop_local import discover_materials,require_local
    W=qt();cache_path=USER/'material_validation.json'
    cache=json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    try:
        ordinary=Path(discover_materials(settings['lab_root'],ROOT,settings.get('ordinary_root'))['ordinary_root'])
    except ValueError:
        directory=W.QFileDialog.getExistingDirectory(None,'重新选择本机普通材料目录，可选video_materials上级',settings['lab_root'])
        if not directory:return False
        ordinary=Path(discover_materials(settings['lab_root'],ROOT,directory)['ordinary_root'])
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
        require_local(emotion)
        settings['emotion_root']=str(emotion.resolve())
    progress=W.QProgressDialog('首次核验视频需要读取全部材料；后续仅重验变化文件。','取消',0,len(rows))
    progress.setWindowTitle('离线材料核验');progress.setMinimumDuration(0)
    try:
        for i,(path,expected,size) in enumerate(rows):
            progress.setValue(i);W.QApplication.processEvents()
            if progress.wasCanceled():return False
            require_local(path)
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
    p.add_argument('--audit',action='store_true');p.add_argument('--archive-caches',action='store_true');p.add_argument('--drive-report',nargs='?',const='ASK')
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
    from video_eeg.utils.desktop_local import SCHEMA,validate_runtime,local_recording_root,dependency_report,archive_caches,drive_report,require_local
    require_local(ROOT);require_local(USER)
    if args.drive_report:
        letter=args.drive_report
        if letter=='ASK':
            letter,ok=qt().QInputDialog.getText(None,'检查移动硬盘占用','输入盘符，例如E:')
            if not ok:return 0
        result=drive_report(letter,USER)
        qt().QMessageBox.information(None,'占用报告',str(result)+'\n报告不覆盖全部内核句柄；不会自动结束进程。');return 0
    from video_eeg.experiment import video_runner as base
    from video_eeg.utils.desktop import adapt_config,assert_legacy_idle
    from video_eeg.utils.recording_paths import recording_root
    import launch_experiment as launcher
    settings=load_settings()
    if (args.settings or settings.get('schema')!=SCHEMA) and not choose_binding(settings):return 0
    validate_runtime(settings,USER,ROOT)
    if args.audit or args.archive_caches:
        if args.archive_caches:
            answer=qt().QMessageBox.question(None,'归档缓存','只把核验通过的缓存复制校验后移入本机_archive。数据、视频、环境、旧源码和配置保留。是否继续？')
            if answer!=qt().QMessageBox.StandardButton.Yes:return 0
            count=archive_caches(settings,USER,ROOT);message=f'已归档 {count} 个缓存文件。'
        else:message='逐文件依赖和旧目录保留清单已生成。'
        report=dependency_report(settings,USER,ROOT)
        qt().QMessageBox.information(None,'文件盘点',message+'\n'+str(report));os.startfile(report);return 0
    selected=launcher.choose(default_protocol='v1' if settings.get('legacy_snapshot') else 'v2',paths_hint='普通视频：'+settings['ordinary_root']+'\n新数据根目录：'+settings['data_root'])
    if not selected:return 0
    protocol,mode=selected
    if mode=='formal':
        validate_runtime(settings,USER,ROOT,formal=True)
        if not verify_materials(settings,protocol):return 0
    original=base.load_config
    base.load_config=lambda path:adapt_config(original(path),path,settings,USER,ROOT)
    base.recording_root=lambda cfg,project,subject_id=None:local_recording_root(cfg,settings,subject_id)
    if settings.get('legacy_snapshot'):
        from video_eeg.utils.desktop import legacy_config
        _,old=legacy_config(settings['legacy_snapshot'])
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
