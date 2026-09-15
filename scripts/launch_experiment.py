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
    import tkinter as tk
    from tkinter import ttk
    root=tk.Tk();root.title('视频EEG实验启动');root.geometry('570x380');root.resizable(False,False)
    from PIL import Image,ImageTk
    from video_eeg.utils.branding import LOGO
    if LOGO.is_file():
        with Image.open(LOGO) as original:display=original.copy()
        display.thumbnail((76,76))
        root.company_logo=ImageTk.PhotoImage(display)
        ttk.Label(root,image=root.company_logo).pack(pady=(8,0))
    selection=tk.StringVar(value=PROTOCOLS['emotion-v2'][0]);mode=tk.StringVar(value='demo');answer=[]
    ttk.Label(root,text='选择实验版本与运行方式',font=('Microsoft YaHei',16)).pack(pady=10)
    combo=ttk.Combobox(root,textvariable=selection,state='readonly',width=44,
        values=[PROTOCOLS[k][0] for k in ('emotion-v2','legacy17')]);combo.pack(pady=8)
    advanced=tk.BooleanVar()
    def toggle():
        values=[v[0] for v in PROTOCOLS.values()] if advanced.get() else [PROTOCOLS[k][0] for k in ('emotion-v2','legacy17')]
        combo['values']=values
        if selection.get() not in values:selection.set(values[0])
    ttk.Checkbutton(root,text='显示其他历史版本（已有被试续跑）',variable=advanced,command=toggle).pack()
    frame=ttk.Frame(root);frame.pack(pady=12)
    ttk.Radiobutton(frame,text='Demo（模拟EEG）',variable=mode,value='demo').pack(side='left',padx=15)
    ttk.Radiobutton(frame,text='正式（真实EEG）',variable=mode,value='formal').pack(side='left',padx=15)
    ttk.Label(root,text='下一页填写被试编号和Session。已有被试请选择原协议。').pack(pady=8)
    def start():
        answer.extend([next(k for k,v in PROTOCOLS.items() if v[0]==selection.get()),mode.get()]);root.destroy()
    ttk.Button(root,text='进入实验',command=start).pack(pady=10)
    root.mainloop();return answer or None

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
