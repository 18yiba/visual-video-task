"""One experiment entry; protocol and acquisition behavior remain in existing runners."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

PROTOCOLS={
    'emotion-v2':('最新融合版：45组，七级评分','video_emotion_config.yaml','video_emotion_demo_config.yaml'),
    'legacy17':('旧版视频EEG：17组','video_legacy_17_config.yaml','video_demo_config.yaml'),
    'legacy34':('兼容：34组视频EEG','video_config.yaml','video_demo_config.yaml'),
    'emotion-v1':('兼容：45组九级评分','video_emotion_v1_config.yaml','video_emotion_demo_v1_config.yaml'),
    'legacy2779':('兼容：旧2779题库','video_legacy_2779_config.yaml','video_demo_config.yaml'),
}

def choose():
    # Use the subject dialog's Qt backend so Windows DPI scaling and frames match.
    from psychopy.gui import qtgui
    from video_eeg.utils.branding import LOGO,LOGO_SIZE,configure_startup_dialog
    qtgui.ensureQtApp()
    W=qtgui.QtWidgets;Qt=qtgui.Qt;Gui=qtgui.QtGui
    root=W.QDialog();root.setWindowTitle('视频EEG实验启动')
    layout=W.QVBoxLayout(root);layout.setContentsMargins(24,12,24,20);layout.setSpacing(10)
    center=Qt.AlignmentFlag.AlignCenter if hasattr(Qt,'AlignmentFlag') else Qt.AlignCenter
    if LOGO.is_file():
        keep=Qt.AspectRatioMode.KeepAspectRatio if hasattr(Qt,'AspectRatioMode') else Qt.KeepAspectRatio
        smooth=Qt.TransformationMode.SmoothTransformation if hasattr(Qt,'TransformationMode') else Qt.SmoothTransformation
        logo=W.QLabel();logo.setPixmap(Gui.QPixmap(str(LOGO)).scaled(LOGO_SIZE,LOGO_SIZE,keep,smooth));logo.setAlignment(center)
        layout.addWidget(logo)
    title=W.QLabel('选择实验版本与运行方式');title.setFont(Gui.QFont('Microsoft YaHei',16));title.setAlignment(center)
    layout.addWidget(title)
    combo=W.QComboBox();combo.addItems([PROTOCOLS[k][0] for k in ('emotion-v2','legacy17')]);layout.addWidget(combo)
    advanced=W.QCheckBox('显示其他历史版本（已有被试续跑）');layout.addWidget(advanced,alignment=center)
    def toggle():
        selected=combo.currentText()
        values=[v[0] for v in PROTOCOLS.values()] if advanced.isChecked() else [PROTOCOLS[k][0] for k in ('emotion-v2','legacy17')]
        combo.clear();combo.addItems(values)
        if selected in values:combo.setCurrentText(selected)
    advanced.toggled.connect(toggle)
    row=W.QHBoxLayout();row.addStretch()
    demo=W.QRadioButton('Demo（模拟EEG）');formal=W.QRadioButton('正式（真实EEG）');demo.setChecked(True)
    row.addWidget(demo);row.addSpacing(24);row.addWidget(formal);row.addStretch();layout.addLayout(row)
    hint=W.QLabel('下一页填写被试编号和Session。已有被试请选择原协议。');hint.setAlignment(center);layout.addWidget(hint)
    answer=[]
    def start():
        answer.extend([next(k for k,v in PROTOCOLS.items() if v[0]==combo.currentText()),'demo' if demo.isChecked() else 'formal']);root.accept()
    button=W.QPushButton('进入实验');button.clicked.connect(start);layout.addWidget(button,alignment=center)
    configure_startup_dialog(root)
    execute=getattr(root,'exec',None) or root.exec_
    execute();return answer or None

def launch(protocol, mode, extra=None):
    from video_eeg.experiment import video_runner as base
    formal,demo=PROTOCOLS[protocol][1:]
    original=base.load_config;old_default=base.DEFAULT_CONFIG_FILENAME;old_demo=base.DEMO_CONFIG_FILENAME
    def configured(path):
        config=original(path);config['_unified_protocol']=protocol;config['demo_mode']=mode=='demo'
        # Ordinary Demo must work without the official materials, on every installation.
        if mode=='demo' and protocol.startswith('legacy'):
            from prepare_demo_materials import main as prepare_demo
            prepare_demo()
            config['protocol']['video_library_dir']=str(ROOT/'stimuli/demo')
            config['protocol']['question_bank_path']='stimuli/demo/question_bank.json'
        return config
    base.load_config=configured;base.DEFAULT_CONFIG_FILENAME=formal;base.DEMO_CONFIG_FILENAME=demo
    try:return base.main((['--demo'] if mode=='demo' else ['--real-eeg'])+list(extra or []))
    finally:base.load_config=original;base.DEFAULT_CONFIG_FILENAME=old_default;base.DEMO_CONFIG_FILENAME=old_demo

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--protocol',choices=list(PROTOCOLS));p.add_argument('--mode',choices=['demo','formal'])
    args,extra=p.parse_known_args()
    if bool(args.protocol)!=bool(args.mode):p.error('--protocol and --mode must be specified together')
    selected=[args.protocol,args.mode] if args.protocol else choose()
    if not selected:return 0
    if any(x in extra for x in ('--config','--demo','--dummy-eeg','--real-eeg')):
        p.error('Use --protocol and --mode to select the configuration and recording type')
    return launch(*selected,extra)

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(f'启动失败：{exc}',file=sys.stderr)
        raise
