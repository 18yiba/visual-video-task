"""Graphical, EEG-free launcher for the v3 behavior-rating stage."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))


DEVICES = (
    ('EMOTIV / EmotivPRO', 'emotivpro'),
    ('博睿康 / Collect TCP', 'neuracle'),
    ('强脑 SDK', 'brainco'),
)


def rating_arguments(device, subject, session, *, emotion_only=False, fullscreen=True):
    args = ['main.py', '--paradigm', 'v3', '--phase', 'behavior-rating', '--device', device,
            '--subject-id', subject, '--session-id', str(session), '--no-dialog', '--integrated-startup']
    if emotion_only:
        args.append('--emotion-only')
    if not fullscreen:
        args.append('--windowed')
    return args


def main():
    from psychopy.gui import qtgui

    qtgui.ensureQtApp()
    W = qtgui.QtWidgets
    C = __import__(f'{qtgui.haveQt}.QtCore', fromlist=['QtCore'])
    from video_eeg.utils.branding import LOGO
    chinese_font = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts' / 'simhei.ttf'
    if chinese_font.is_file():
        qtgui.QtGui.QFontDatabase.addApplicationFont(str(chinese_font))

    class RatingWindow(W.QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('v3 情绪视频行为评分')
            self.resize(860, 650)
            self.setMinimumSize(780, 590)
            self.progress = None
            self.process = C.QProcess(self)
            self.process.setWorkingDirectory(str(ROOT))
            self.process.readyReadStandardOutput.connect(self.read_output)
            self.process.readyReadStandardError.connect(self.read_output)
            self.process.finished.connect(self.finished)
            self.process.errorOccurred.connect(self.failed)
            self.setStyleSheet('''
                QDialog { background: #f3f6fa; }
                QWidget { font-family: "SimHei"; font-size: 13px; color: #25344b; }
                QFrame#card { background: white; border: 1px solid #e3e9f0; border-radius: 14px; }
                QLabel#heading { font-size: 25px; font-weight: 700; color: #16283e; }
                QLabel#muted { color: #728197; font-size: 12px; }
                QLabel#progress { background: #f3f7fa; border-radius: 9px; padding: 15px; color: #3d566b; }
                QLabel#status { color: #50647a; }
                QLineEdit, QComboBox, QSpinBox { background: #f8fafc; border: 1px solid #dce4ed; border-radius: 7px; min-height: 38px; padding: 0 10px; }
                QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #229a83; background: white; }
                QPushButton { background: white; border: 1px solid #d9e3ec; border-radius: 7px; padding: 10px 16px; font-weight: 600; min-height: 24px; }
                QPushButton:hover { background: #eef6f4; border-color: #81baac; }
                QPushButton#primary { background: #183b53; color: white; border: none; }
                QPushButton#primary:hover { background: #235570; }
                QPushButton:disabled { background: #f1f4f7; color: #a5b0bf; border-color: #e5eaf0; }
                QCheckBox { spacing: 8px; color: #64758b; }
                QPlainTextEdit { background: #f8fafc; border: 1px solid #e1e7ef; border-radius: 7px; padding: 8px; color: #64758b; font-size: 11px; }
            ''')
            outer = W.QVBoxLayout(self)
            outer.setContentsMargins(28, 24, 28, 22)
            outer.setSpacing(18)

            header = W.QHBoxLayout()
            if LOGO.is_file():
                logo = W.QLabel()
                logo.setPixmap(qtgui.QtGui.QPixmap(str(LOGO)).scaled(
                    48, 48, qtgui.Qt.AspectRatioMode.KeepAspectRatio,
                    qtgui.Qt.TransformationMode.SmoothTransformation))
                header.addWidget(logo)
            title_box = W.QVBoxLayout()
            title = W.QLabel('情绪视频行为评分')
            title.setObjectName('heading')
            subtitle = W.QLabel('独立评分入口 · 不连接或采集 EEG')
            subtitle.setObjectName('muted')
            title_box.addWidget(title)
            title_box.addWidget(subtitle)
            header.addLayout(title_box)
            header.addStretch()
            header.addWidget(W.QLabel('v3 / RATING'))
            outer.addLayout(header)

            card = W.QFrame()
            card.setObjectName('card')
            form = W.QFormLayout(card)
            form.setContentsMargins(24, 22, 24, 22)
            form.setHorizontalSpacing(24)
            form.setVerticalSpacing(14)
            self.device = W.QComboBox()
            for label, value in DEVICES:
                self.device.addItem(label, value)
            self.scope = W.QComboBox()
            self.scope.addItem('全部视频', False)
            self.scope.addItem('仅情绪视频', True)
            self.subject = W.QLineEdit()
            self.subject.setPlaceholderText('输入平台已有的 8 位被试编号')
            validator = qtgui.QtGui.QRegularExpressionValidator(C.QRegularExpression(r'[0-9]{0,8}'), self.subject)
            self.subject.setValidator(validator)
            self.session = W.QSpinBox()
            self.session.setRange(1, 45)
            self.session.setValue(1)
            self.fullscreen = W.QCheckBox('评分视频全屏播放')
            self.fullscreen.setChecked(True)
            form.addRow('原 EEG 采集设备', self.device)
            form.addRow('采集视频范围', self.scope)
            form.addRow('被试编号', self.subject)
            form.addRow('Session', self.session)
            form.addRow('', self.fullscreen)
            outer.addWidget(card)

            self.progress_label = W.QLabel('填写被试编号后查看本 Session 的可评分进度。')
            self.progress_label.setObjectName('progress')
            self.progress_label.setWordWrap(True)
            outer.addWidget(self.progress_label)
            self.path_label = W.QLabel('')
            self.path_label.setObjectName('muted')
            self.path_label.setWordWrap(True)
            outer.addWidget(self.path_label)

            self.log = W.QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setMaximumHeight(90)
            self.log.hide()
            outer.addWidget(self.log)

            footer = W.QHBoxLayout()
            self.status = W.QLabel('选择与原采集记录相同的设备和视频范围。')
            self.status.setObjectName('status')
            footer.addWidget(self.status, 1)
            self.refresh = W.QPushButton('刷新进度')
            self.start = W.QPushButton('开始行为评分')
            self.start.setObjectName('primary')
            footer.addWidget(self.refresh)
            footer.addWidget(self.start)
            outer.addLayout(footer)

            self.device.currentIndexChanged.connect(lambda *_: self.refresh_progress())
            self.scope.currentIndexChanged.connect(lambda *_: self.refresh_progress())
            self.subject.editingFinished.connect(self.refresh_progress)
            self.session.valueChanged.connect(lambda *_: self.refresh_progress())
            self.refresh.clicked.connect(self.refresh_progress)
            self.start.clicked.connect(self.start_rating)

        def current_config(self):
            backend = self.device.currentData()
            old_backend = os.environ.get('VIDEO_EEG_BACKEND')
            os.environ['VIDEO_EEG_BACKEND'] = backend
            try:
                from launch_emotion_v3 import configuration
                return configuration(emotion_only=bool(self.scope.currentData()))
            finally:
                if old_backend is None:
                    os.environ.pop('VIDEO_EEG_BACKEND', None)
                else:
                    os.environ['VIDEO_EEG_BACKEND'] = old_backend

        def refresh_progress(self):
            subject = self.subject.text().strip()
            if len(subject) != 8 or not all('0' <= char <= '9' for char in subject):
                self.progress = None
                self.progress_label.setText('请输入 8 位平台被试编号，以读取原采集记录和待评分数量。')
                self.path_label.clear()
                return False
            try:
                from video_eeg.utils.v3_progress import inspect_progress
                self.progress = inspect_progress(self.current_config(), subject, ROOT)
                row = self.progress[self.session.value() - 1]
                pending = max(0, row['emotion_eeg_saved'] - row['ratings_completed'])
                self.progress_label.setText(
                    f"Session {row['session']:02d}　可评分 {pending} 段　"
                    f"EEG已保存 {row['emotion_eeg_saved']}/{row['emotion_total']}　"
                    f"评分完成 {row['ratings_completed']}/{row['emotion_total']}"
                )
                self.path_label.setText('原记录位置：' + row['path'])
                return True
            except Exception as exc:
                self.progress = None
                self.progress_label.setText('无法读取该设备和视频范围的进度：' + str(exc))
                self.path_label.clear()
                return False

        def start_rating(self):
            if not self.refresh_progress():
                return
            row = self.progress[self.session.value() - 1]
            if row['emotion_eeg_saved'] <= row['ratings_completed']:
                W.QMessageBox.information(self, '暂无待评分内容', '该 Session 没有已保存 EEG 且尚未完成行为评分的视频。')
                return
            try:
                from video_eeg.utils.material_settings import check
                check(self.current_config())
                from video_eeg.utils.v3_progress import valid_subject
                subject = valid_subject(self.subject.text())
            except Exception as exc:
                W.QMessageBox.warning(self, '无法开始评分', str(exc))
                return
            args = rating_arguments(self.device.currentData(), subject, self.session.value(),
                emotion_only=bool(self.scope.currentData()), fullscreen=self.fullscreen.isChecked())
            self.set_busy(True)
            self.status.setText('评分程序已启动；请在实验窗口完成视频重播与评分。')
            self.process.start(sys.executable, args)

        def set_busy(self, busy):
            for widget in (self.device, self.scope, self.subject, self.session, self.fullscreen,
                           self.refresh, self.start):
                widget.setEnabled(not busy)

        def read_output(self):
            out = bytes(self.process.readAllStandardOutput()).decode('utf-8', 'replace')
            err = bytes(self.process.readAllStandardError()).decode('utf-8', 'replace')
            if out or err:
                self.log.show()
                self.log.appendPlainText((out + err).rstrip())

        def finished(self, code, status):
            self.set_busy(False)
            self.status.setText(f'评分程序已结束（退出码 {code}）；进度已刷新。')
            self.refresh_progress()

        def failed(self, error):
            self.set_busy(False)
            self.status.setText('评分程序启动失败：' + self.process.errorString())

        def reject(self):
            if self.process.state() != C.QProcess.ProcessState.NotRunning:
                W.QMessageBox.information(self, '评分运行中', '请先在评分视频窗口保存退出。')
                return
            super().reject()

        def closeEvent(self, event):
            if self.process.state() != C.QProcess.ProcessState.NotRunning:
                event.ignore()
                W.QMessageBox.information(self, '评分运行中', '请先在评分视频窗口保存退出。')
                return
            event.accept()

    app = qtgui.QtWidgets.QApplication.instance()
    if app is not None:
        window = RatingWindow()
        return window.exec()
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
