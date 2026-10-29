"""Combined local v3 launch, connectivity and read-only progress window."""
import argparse
import json
import importlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video_eeg.experiment import video_runner as base
from video_eeg.utils.v3_progress import inspect_progress, valid_subject


def is_neuracle():
    return os.environ.get('VIDEO_EEG_BACKEND', '').lower() == 'neuracle'


def is_brainco():
    return os.environ.get('VIDEO_EEG_BACKEND', '').lower() == 'brainco'


def configuration(emotion_only=False, port=""):
    config_path = Path(os.environ.get('VIDEO_EEG_V3_CONFIG', str(base.CONFIG_DIR / 'video_emotion_v3_config.yaml')))
    cfg = base.load_config(config_path)
    if cfg.get('hardware_dummy_mode') or cfg.get('demo_mode'):
        raise ValueError('v3入口仅支持真实EEG配置，请关闭配置中的模拟模式。')
    cfg['_project_dir'] = str(ROOT)
    from video_eeg.utils.material_settings import apply
    apply(cfg,ROOT)
    if is_neuracle():
        from video_eeg.utils.neuracle_recording import configure, load_profile
        profile = load_profile(ROOT)
        if port: profile['serial_port'] = port
        configure(cfg, profile)
    elif is_brainco():
        cfg['device_type'] = 'brainco'
        device = dict(cfg.get('device', {}))
        device['brainco_transport'] = 'sdk'
        cfg['device'] = device
        storage = dict(cfg.get('storage', {}))
        records = Path(storage.get('records_dir', 'data/sourcedata/v3'))
        if not records.name.endswith('_brainco'):
            records = records.with_name(records.name + '_brainco')
        storage['records_dir'] = records.as_posix()
        cfg['storage'] = storage
    else:
        from video_eeg.utils.emotivpro_recording import configure
        configure(cfg, port)
    if emotion_only:
        from video_eeg.experiment.emotion_v3_runner import configure_emotion_only
        configure_emotion_only(cfg)
    return cfg


def launch_direct(phase, device, extra=None):
    """Run a selected v3 phase through the same device configuration as the console."""
    old_backend = os.environ.get('VIDEO_EEG_BACKEND')
    os.environ['VIDEO_EEG_BACKEND'] = device if device in {'neuracle', 'brainco'} else 'emotivpro'
    try:
        import yaml
        runtime = ROOT / '.tmp'
        runtime.mkdir(exist_ok=True)
        cfg = configuration(emotion_only=False)
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', prefix='v3_cli_', dir=runtime,
                                         encoding='utf-8', delete=False) as stream:
            yaml.safe_dump(cfg, stream, allow_unicode=True)
            config_path = stream.name
        from video_eeg.experiment import emotion_v3_runner
        stage = 'eeg' if phase == 'acquisition' else 'ratings'
        return emotion_v3_runner.main(['--config', config_path, '--device-type', device,
                                       '--emotion-stage', stage, '--real-eeg', *(extra or [])])
    finally:
        if old_backend is None:
            os.environ.pop('VIDEO_EEG_BACKEND', None)
        else:
            os.environ['VIDEO_EEG_BACKEND'] = old_backend


def launch_behavior_rating(window):
    """Expose ratings as a direct console action while reusing the validated route."""
    window.stage.setCurrentIndex(1)
    window.launch()


def make_window():
    from psychopy.gui import qtgui
    qtgui.ensureQtApp()
    W = qtgui.QtWidgets
    C = importlib.import_module(f'{qtgui.haveQt}.QtCore')

    class Window(W.QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('v3 博睿康实验控制台' if is_neuracle() else 'v3 实验控制台')
            self.resize(1000, 700)
            self.connection = None
            self.port = ''
            self.progress = None
            self.running = False
            self.setStyleSheet('''
                QDialog { background: #f3f6fa; }
                QWidget { font-family: "Microsoft YaHei"; font-size: 12px; color: #25344b; }
                QFrame#card { background: white; border: 1px solid #e3e9f0; border-radius: 14px; }
                QLabel#heading { font-size: 25px; font-weight: 700; color: #16283e; }
                QLabel#section { font-size: 16px; font-weight: 600; }
                QLabel#muted { color: #728197; font-size: 11px; }
                QLabel#badge { background: #e4f3ee; color: #157d68; border-radius: 10px; padding: 6px 12px; font-weight: 600; }
                QLineEdit, QComboBox, QSpinBox { background: #f8fafc; border: 1px solid #dce4ed; border-radius: 7px; min-height: 36px; padding: 0 10px; }
                QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #229a83; background: white; }
                QComboBox::drop-down { border: none; width: 26px; }
                QPushButton { background: white; border: 1px solid #d9e3ec; border-radius: 7px; padding: 9px 13px; font-weight: 600; }
                QPushButton:hover { background: #eef6f4; border-color: #81baac; }
                QPushButton#primary { background: #183b53; color: white; border: none; min-height: 27px; }
                QPushButton#primary:hover { background: #235570; }
                QPushButton:disabled { background: #f1f4f7; color: #a5b0bf; border-color: #e5eaf0; }
                QLabel#device { background: #f0f6f8; color: #496479; border-radius: 8px; padding: 12px; }
                QProgressBar { border: none; border-radius: 6px; background: #edf2f7; text-align: center; min-height: 25px; color: #34465b; font-size: 11px; }
                QProgressBar::chunk { background: #7dceba; border-radius: 6px; }
                QProgressBar#rating::chunk { background: #a9c7e4; }
                QTableWidget { border: none; background: white; gridline-color: #edf1f6; alternate-background-color: #f8fafc; selection-background-color: #e0f2ec; selection-color: #176d5b; }
                QHeaderView::section { background: #f3f6fa; border: none; padding: 10px 4px; color: #6a7c91; font-size: 11px; }
                QTableWidget::item { border-bottom: 1px solid #edf1f6; padding: 6px; }
                QPlainTextEdit { background: #f8fafc; border: 1px solid #e1e7ef; border-radius: 7px; padding: 8px; color: #64758b; font-size: 11px; }
                QCheckBox { spacing: 8px; color: #64758b; }
                QScrollBar:vertical { background: #f5f7fa; width: 8px; border-radius: 4px; }
                QScrollBar::handle:vertical { background: #c8d3df; border-radius: 4px; min-height: 25px; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            ''')
            layout = W.QVBoxLayout(self); layout.setContentsMargins(26, 22, 26, 22); layout.setSpacing(20)
            header = W.QHBoxLayout(); header.setSpacing(12)
            from video_eeg.utils.branding import LOGO
            if LOGO.is_file():
                logo = W.QLabel()
                logo.setPixmap(qtgui.QtGui.QPixmap(str(LOGO)).scaled(44, 44, qtgui.Qt.AspectRatioMode.KeepAspectRatio, qtgui.Qt.TransformationMode.SmoothTransformation))
                header.addWidget(logo)
            heading = W.QVBoxLayout(); heading.setSpacing(3)
            title = W.QLabel('情绪视频实验'); title.setObjectName('heading')
            subtitle = W.QLabel('采集、评分与进度管理'); subtitle.setObjectName('muted')
            heading.addWidget(title); heading.addWidget(subtitle); header.addLayout(heading); header.addStretch()
            badge = W.QLabel('v3  /  实验控制台'); badge.setObjectName('badge'); header.addWidget(badge)
            layout.addLayout(header)
            body = W.QHBoxLayout(); body.setSpacing(18); layout.addLayout(body, 1)
            setup = W.QFrame(); setup.setObjectName('card'); setup.setFixedWidth(284)
            controls = W.QVBoxLayout(setup); controls.setContentsMargins(20, 22, 20, 20); controls.setSpacing(12)
            label = W.QLabel('实验设置'); label.setObjectName('section'); controls.addWidget(label)
            hint = W.QLabel('选择阶段，使用原编号继续实验。'); hint.setObjectName('muted'); controls.addWidget(hint)
            self.stage = W.QComboBox(); self.stage.addItems(['EEG采集', '行为评分'])
            self.scope = W.QComboBox(); self.scope.addItems(['全部视频', '仅情绪视频'])
            self.subject = W.QLineEdit(); self.subject.setPlaceholderText('平台已有的8位编号')
            self.paradigm = W.QLineEdit(); self.paradigm.setPlaceholderText('平台已确认的范式代码')
            from video_eeg.utils.eegqc_export import DEFAULT_PARADIGM_CODES
            self.paradigm.setText(DEFAULT_PARADIGM_CODES['v3'])
            self.session = W.QSpinBox(); self.session.setRange(1, 1)
            self.fullscreen = W.QCheckBox('全屏播放'); self.fullscreen.setChecked(True)
            for text, widget in [('实验阶段', self.stage), ('视频范围', self.scope), ('被试编号', self.subject), ('Session', self.session), ('平台范式代码', self.paradigm)]:
                field = W.QVBoxLayout(); field.setSpacing(6)
                label = W.QLabel(text); label.setObjectName('muted'); field.addWidget(label); field.addWidget(widget)
                controls.addLayout(field)
            controls.addWidget(self.fullscreen)
            self.materials = W.QPushButton('视频材料位置（本机 / NAS）')
            controls.addWidget(self.materials)
            self.materials.clicked.connect(self.choose_materials)
            self.detect = W.QPushButton(
                '配置 / 检测脑电与 TRG' if is_neuracle() else
                '检测强脑 SDK 数据流' if is_brainco() else
                '选择 / 检查 Trigger 发送端')
            self.refresh = W.QPushButton('刷新进度')
            self.start = W.QPushButton('开始实验')
            self.start.setObjectName('primary')
            self.rate = W.QPushButton('开始行为评分')
            self.rate.setToolTip('直接进入独立行为评分；不连接或采集 EEG。')
            controls.addWidget(self.detect)
            self.register_eeg = W.QPushButton('登记已导出的 EmotivPRO EEG')
            controls.addWidget(self.register_eeg)
            if is_neuracle(): self.register_eeg.hide()
            self.register_eeg.clicked.connect(self.confirm_external_eeg)
            self.device_status = W.QLabel('尚未选择发送端；脑电请在 EmotivPRO 检查。'); self.device_status.setWordWrap(True)
            self.device_status.setObjectName('device'); controls.addWidget(self.device_status)
            controls.addStretch(); controls.addWidget(self.start); controls.addWidget(self.rate)
            body.addWidget(setup)
            progress_card = W.QFrame(); progress_card.setObjectName('card')
            progress_layout = W.QVBoxLayout(progress_card); progress_layout.setContentsMargins(22, 22, 22, 18); progress_layout.setSpacing(14)
            progress_heading = W.QHBoxLayout()
            label = W.QLabel('完成进度'); label.setObjectName('section'); progress_heading.addWidget(label); progress_heading.addStretch(); progress_heading.addWidget(self.refresh)
            progress_layout.addLayout(progress_heading)
            self.overview = W.QLabel(); self.overview.setWordWrap(True); self.overview.setObjectName('muted'); progress_layout.addWidget(self.overview)
            self.eeg_bar = W.QProgressBar(); self.rating_bar = W.QProgressBar()
            self.rating_bar.setObjectName('rating')
            bars = W.QHBoxLayout(); bars.setSpacing(12)
            for text, bar in [('EEG 采集', self.eeg_bar), ('情绪行为评分', self.rating_bar)]:
                column = W.QVBoxLayout(); column.setSpacing(7)
                column.addWidget(W.QLabel(text)); column.addWidget(bar); bars.addLayout(column)
            progress_layout.addLayout(bars)
            self.table = W.QTableWidget(0, 5)
            self.table.setHorizontalHeaderLabels(['Session', '采集视频', '情绪 EEG', '行为评分', '状态'])
            self.table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
            self.table.verticalHeader().hide(); self.table.verticalHeader().setDefaultSectionSize(40)
            self.table.setAlternatingRowColors(True); self.table.setShowGrid(False)
            self.table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setMinimumHeight(160); progress_layout.addWidget(self.table, 1)
            label = W.QLabel('数据保存位置'); label.setObjectName('muted'); progress_layout.addWidget(label)
            self.location = W.QLineEdit(); self.location.setReadOnly(True); self.location.setMinimumWidth(0)
            self.location.setStyleSheet('font-size: 10px; color: #7b8b9f; min-height: 27px; border: none; background: #f5f7fa;')
            progress_layout.addWidget(self.location)
            body.addWidget(progress_card, 1)
            self.log = W.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(85); self.log.hide()
            footer = W.QHBoxLayout()
            hint = W.QLabel('实验中按 Esc 保存退出，结束后自动更新进度。'); hint.setObjectName('muted'); footer.addWidget(hint); footer.addStretch()
            log_toggle = W.QPushButton('查看运行日志'); log_toggle.setCheckable(True)
            log_toggle.toggled.connect(self.log.setVisible); footer.addWidget(log_toggle)
            layout.addLayout(footer); layout.addWidget(self.log)
            self.probe = C.QProcess(self); self.process = C.QProcess(self)
            self.probe.readyReadStandardOutput.connect(self.read_probe)
            self.probe.readyReadStandardError.connect(lambda: self.log.appendPlainText(bytes(self.probe.readAllStandardError()).decode('utf-8', 'replace')))
            self.probe.finished.connect(self.probe_finished)
            self.probe.errorOccurred.connect(self.probe_failed)
            self.process.readyReadStandardOutput.connect(lambda: self.log.appendPlainText(bytes(self.process.readAllStandardOutput()).decode('utf-8', 'replace')))
            self.process.readyReadStandardError.connect(lambda: self.log.appendPlainText(bytes(self.process.readAllStandardError()).decode('utf-8', 'replace')))
            self.process.finished.connect(self.run_finished)
            self.process.errorOccurred.connect(self.run_failed)
            self.detect.clicked.connect(self.check_connection)
            self.refresh.clicked.connect(self.check_progress)
            self.start.clicked.connect(self.launch)
            self.rate.clicked.connect(lambda: launch_behavior_rating(self))
            self.stage.currentIndexChanged.connect(self.changed_stage)
            self.scope.currentIndexChanged.connect(self.check_progress)
            self.subject.editingFinished.connect(self.check_progress)
            self.session.valueChanged.connect(self.show_selected)
            self.table.cellClicked.connect(lambda row, col: self.session.setValue(row + 1))
            self.changed_mode()

        def locked(self, value):
            self.materials.setEnabled(not value)
            for widget in (self.stage, self.scope, self.subject, self.session, self.paradigm, self.fullscreen, self.detect, self.register_eeg, self.refresh, self.start, self.rate, self.table):
                widget.setEnabled(not value)
            if not value:
                self.changed_stage()

        def changed_mode(self):
            self.connection = None
            self.session.setMaximum(45)
            self.changed_stage()
            self.check_progress()

        def changed_stage(self):
            ratings = self.stage.currentIndex() == 1
            self.paradigm.setEnabled(not ratings and not self.running)
            self.detect.setEnabled(not ratings and not self.running)
            if is_neuracle():
                self.device_status.setText('行为评分无需设备；本阶段不连接或采集 EEG。' if ratings else
                    (f"TCP + TRG 检测通过：{self.connection['channels']} 通道，信号 {self.connection['sfreq']:g} Hz，原始 TRG {self.connection.get('neuracle_forwarding',{}).get('trigger_mapping',{}).get('raw_sampling_rate_hz',self.connection['sfreq']):g} Hz。开始时会重新检测。" if self.connection else '请启动 Collect 数据转发，再检测脑电和同步盒。'))
                return
            if is_brainco():
                self.device_status.setText('行为评分无需设备；本阶段不连接或采集 EEG。' if ratings else
                    (f"强脑 SDK 检测通过：{self.connection['channels']} 通道，{self.connection['sfreq']:g} Hz，已读取 {self.connection['samples']} 个样本。开始时会重新检测。" if self.connection else '请确认强脑设备与 SDK 网络连接，然后检测数据流。'))
                return
            self.device_status.setText('行为评分无需设备；本阶段不连接或采集 EEG。' if ratings else
                ('串口可打开；脑电与接收状态须在 EmotivPRO 核对。' if self.connection else '尚未选择发送端；脑电请在 EmotivPRO 检查。'))

        def choose_materials(self):
            from video_eeg.utils.material_settings import save
            cfg=configuration()
            default=str(Path(cfg['protocol']['video_library_dir']).parent)
            root,ok=W.QInputDialog.getText(self,'视频材料位置','输入包含videos和emotion_video的材料根目录，可使用NAS的\\\\服务器\\共享路径。\nNAS只读取；EEG、面部录像和进度仍保存本机。',text=default)
            if not ok or not root.strip():return
            try:
                value=save(root.strip(),ROOT)
                W.QMessageBox.information(self,'材料位置已保存','普通视频：'+value['ordinary_root']+'\n情绪视频：'+value['emotion_root']+'\\selected\n本机数据与原Session进度不变。')
                self.check_progress()
            except Exception as exc:
                W.QMessageBox.warning(self,'材料位置未更新',str(exc))

        def check_progress(self):
            if not self.subject.text().strip():
                self.progress = None; self.table.setRowCount(0)
                self.overview.setText('填写平台被试编号后，查看各Session的采集与评分进度。')
                self.location.clear(); self.eeg_bar.setValue(0); self.rating_bar.setValue(0)
                return False
            try:
                self.progress = inspect_progress(configuration(self.scope.currentIndex() == 1), self.subject.text(), ROOT)
                self.table.setRowCount(len(self.progress))
                for i, r in enumerate(self.progress):
                    status = '全部完成' if r['eeg_complete'] and r['ratings_complete'] else '观看完成，EEG待登记' if r['eeg_complete'] and r['emotion_eeg_saved'] < r['emotion_total'] else 'EEG已登记，评分待完成' if r['eeg_complete'] else '采集未完成'
                    values = [str(r['session']), f"{r['videos_completed']}/{r['videos_total']}",
                        f"{r['emotion_eeg_saved']}/{r['emotion_total']}", f"{r['ratings_completed']}/{r['emotion_total']}", status]
                    for j, text in enumerate(values):
                        self.table.setItem(i, j, W.QTableWidgetItem(text))
                if is_neuracle():
                    for i, r in enumerate(self.progress):
                        status = '全部完成' if r['eeg_complete'] and r['ratings_complete'] else '采集与 TRG 已保存，待评分' if r['eeg_complete'] and r['emotion_eeg_saved'] == r['emotion_total'] else '需核对采集故障记录' if r['eeg_complete'] else '采集未完成'
                        self.table.setItem(i, 4, W.QTableWidgetItem(status))
                self.show_selected()
                return True
            except Exception as exc:
                self.progress = None; self.table.setRowCount(0)
                self.overview.setText('进度检测失败：' + str(exc))
                self.eeg_bar.setValue(0); self.rating_bar.setValue(0)
                return False

        def show_selected(self):
            if not self.progress:
                return
            r = self.progress[self.session.value() - 1]
            eeg_done = sum(x['eeg_complete'] and x['emotion_eeg_saved'] == x['emotion_total'] for x in self.progress)
            rating_done = sum(x['ratings_complete'] for x in self.progress)
            self.overview.setText(f"被试总进度：EEG完成 {eeg_done}/{len(self.progress)} 个Session；评分完成 {rating_done}/{len(self.progress)} 个Session。\n"
                f"当前Session可继续评分 {r['emotion_eeg_saved'] - r['ratings_completed']} 段；尚未登记情绪EEG {r['emotion_total'] - r['emotion_eeg_saved']} 段。")
            self.location.setText(r['path']); self.location.setCursorPosition(0); self.location.setToolTip(r['path'])
            self.eeg_bar.setRange(0, max(1, r['videos_total'])); self.eeg_bar.setValue(r['videos_completed'])
            self.eeg_bar.setFormat('%v / %m · %p%')
            self.rating_bar.setRange(0, max(1, r['emotion_total'])); self.rating_bar.setValue(r['ratings_completed'])
            self.rating_bar.setFormat('%v / %m · %p%')

        def check_connection(self):
            self.connection = None
            if is_neuracle():
                from video_eeg.utils.neuracle_recording import select_profile
                try:
                    profile = select_profile(ROOT, self)
                except Exception as exc:
                    W.QMessageBox.warning(self, '配置未完成', str(exc)); return
                self.port = profile['serial_port'] if profile else ''
            elif is_brainco():
                self.port = 'brainco-sdk'
            else:
                from video_eeg.utils.emotivpro_port_dialog import select_port
                self.port = select_port()
            if not self.port:
                self.changed_stage(); return
            self.probe_output = ''
            self.locked(True)
            self.device_status.setText('正在核对 TCP 元数据、连续样本及测试码 250/251/252 的 TRG 回传…' if is_neuracle() else
                '正在通过强脑 SDK 检查设备并读取 EEG 样本…' if is_brainco() else
                '正在检查 EmotivPRO 窗口、USB 接收器和发送端；录制状态仍需主试核对…')
            args = [str(Path(__file__).resolve()), '--probe', '--port', self.port]
            self.probe.setWorkingDirectory(str(ROOT)); self.probe.start(sys.executable, args)

        def read_probe(self):
            self.probe_output += bytes(self.probe.readAllStandardOutput()).decode('utf-8', 'replace')

        def probe_finished(self, code, status):
            self.read_probe(); self.locked(False)
            try:
                report = next(json.loads(line[9:]) for line in self.probe_output.splitlines() if line.startswith('V3_PROBE '))
                if code != 0 or not report['ok']:
                    raise RuntimeError(report.get('error', '检测失败'))
                self.connection = report['connection']
                c = self.connection
                if is_neuracle():
                    self.changed_stage(); return
                if is_brainco():
                    self.changed_stage(); return
                self.device_status.setText(f"环境检查通过：{c['serial_port']}、EmotivPRO 窗口和 USB 接收器。录制、无线脑电及标记接收仍需主试核对。")
            except Exception as exc:
                self.connection = None
                self.device_status.setText('检测失败，可重试：' + str(exc))
                if is_neuracle():
                    self.log.appendPlainText('博睿康检测失败：\n' + str(exc))
                    message = W.QMessageBox(self)
                    message.setWindowTitle('博睿康检测失败')
                    message.setText('未通过脑电 / TRG 检测，尚未允许开始采集。')
                    message.setInformativeText(str(exc))
                    message.setDetailedText(self.probe_output or str(exc))
                    message.exec()

        def probe_failed(self, error):
            self.locked(False); self.connection = None
            self.device_status.setText('检测进程失败：' + self.probe.errorString())

        def launch(self):
            try:
                subject = valid_subject(self.subject.text())
                if not self.check_progress():
                    return
                ratings = self.stage.currentIndex() == 1
                from video_eeg.utils.material_settings import check
                check(configuration(self.scope.currentIndex() == 1))
                r = self.progress[self.session.value() - 1]
                if ratings and r['emotion_eeg_saved'] == r['ratings_completed']:
                    raise ValueError('当前Session没有已保存EEG且尚待评分的情绪视频。')
                if not ratings and not self.connection:
                    message = ('请先检测脑电与 TRG。' if is_neuracle() else
                               '请先检测强脑 SDK 数据流。' if is_brainco() else
                               '请先选择并检查 Trigger 发送端。')
                    raise ValueError(message)
                if not ratings and not self.paradigm.text().strip():
                    raise ValueError('请填写当前视频范围在平台上已确认的范式代码。')
                if not ratings:
                    from video_eeg.utils.eegqc_export import v3_capture_identity
                    cfg = configuration(self.scope.currentIndex() == 1)
                    cfg.update(subject_id=subject, paradigm_code=self.paradigm.text().strip())
                    v3_capture_identity(cfg)
                if not ratings and r['eeg_complete']:
                    raise ValueError('当前 Session 观看已完成，请查看采集与评分进度。' if is_neuracle() else '当前Session观看已完成，请先在 EmotivPRO 保存导出并登记 EEG，再进行行为评分。')
                args = ['-m', 'video_eeg.experiment.emotion_v3_runner', '--no-dialog', '--integrated-startup',
                    '--subject-id', subject, '--session-id', str(self.session.value()), '--emotion-stage', 'ratings' if ratings else 'eeg']
                args.append('--real-eeg')
                if is_neuracle():
                    import tempfile
                    import yaml
                    runtime = ROOT / '.tmp'; runtime.mkdir(exist_ok=True)
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', prefix='neuracle_', dir=runtime, encoding='utf-8', delete=False) as stream:
                        yaml.safe_dump(configuration(port=self.port), stream, allow_unicode=True)
                        self.runtime_config = stream.name
                    args += ['--device-type', 'neuracle', '--config', self.runtime_config]
                elif is_brainco() and not ratings:
                    args += ['--device-type', 'brainco']
                elif not ratings:
                    args += ['--device-type', 'emotivpro', '--emotivpro-port', self.port]
                if not is_neuracle() and os.environ.get('VIDEO_EEG_V3_CONFIG'):
                    args += ['--config', os.environ['VIDEO_EEG_V3_CONFIG']]
                if not ratings:
                    args += ['--paradigm-code', self.paradigm.text().strip()]
                if self.scope.currentIndex() == 1:
                    args.append('--emotion-only')
                if not self.fullscreen.isChecked():
                    args.append('--windowed')
                self.running = True; self.locked(True)
                self.log.appendPlainText('实验已启动；在实验窗口按 Esc 保存退出，结束后自动刷新进度。')
                self.process.setWorkingDirectory(str(ROOT)); self.process.start(sys.executable, args)
            except Exception as exc:
                W.QMessageBox.warning(self, '无法开始', str(exc))

        def confirm_external_eeg(self):
            try:
                if not self.check_progress():
                    return
                from video_eeg.utils.emotivpro_recording import confirm_session_dialog
                confirm_session_dialog(self, Path(self.progress[self.session.value()-1]['path']))
                self.check_progress()
            except Exception as exc:
                W.QMessageBox.warning(self, '外部 EEG 登记未完成', str(exc))

        def run_finished(self, code, status):
            self.running = False; self.connection = None; self.locked(False)
            self.check_progress()
            self.log.appendPlainText(f'实验已结束（退出码 {code}），完成进度已刷新。')

        def run_failed(self, error):
            self.running = False; self.locked(False)
            self.log.appendPlainText('启动失败：' + self.process.errorString())

        def reject(self):
            if self.running or self.probe.state() != C.QProcess.ProcessState.NotRunning:
                W.QMessageBox.information(self, '程序运行中', '请先在实验窗口保存退出，或等待连通性检测完成。')
                return
            super().reject()

        def closeEvent(self, event):
            if self.running or self.probe.state() != C.QProcess.ProcessState.NotRunning:
                event.ignore(); self.reject()
            else:
                event.accept()

    return Window()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--port', default='')
    args = parser.parse_args(argv)
    if args.probe:
        try:
            report = dict(ok=True, connection=base.probe_eeg_connection(configuration(port=args.port)))
        except Exception as exc:
            report = dict(ok=False, error=str(exc))
        if is_neuracle():
            try:
                from video_eeg.utils.neuracle_recording import write_probe_report
                report['report_path'] = str(write_probe_report(ROOT, report))
            except OSError as exc:
                print('检测报告保存失败：' + str(exc), file=sys.stderr, flush=True)
        print('V3_PROBE ' + json.dumps(report), flush=True)
        return 0 if report['ok'] else 1
    window = make_window()
    return window.exec()


if __name__ == '__main__':
    raise SystemExit(main())
