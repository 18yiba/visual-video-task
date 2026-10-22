"""Local Neuracle profile. Shared protocol configuration is never rewritten."""
import copy
import json
import math
from pathlib import Path

DEFAULTS=dict(host='127.0.0.1',tcp_port=8712,signal_channels=64,sfreq=1000,serial_port='')


def write_probe_report(root, report):
    from datetime import datetime
    from uuid import uuid4
    folder=Path(root)/'logs'; folder.mkdir(parents=True,exist_ok=True)
    path=folder/('neuracle_probe_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid4().hex[:8]+'.json')
    with path.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2)
    return path


def load_profile(root):
    p=Path(root)/'neuracle.local.json'
    return dict(DEFAULTS,**(json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}))


def configure(config, profile):
    p=dict(DEFAULTS,**profile)
    if not p['host'].strip() or not 1<=int(p['tcp_port'])<=65535:raise ValueError('TCP 地址或端口不合法。')
    if not 1<=int(p['signal_channels'])<=512:raise ValueError('信号通道数不合法。')
    if not math.isfinite(float(p['sfreq'])) or float(p['sfreq'])<=0:raise ValueError('采样率不合法。')
    config['device_type']='neuracle'
    config['sfreq']=config['eeg_sampling_rate_hz']=float(p['sfreq'])
    device=copy.deepcopy(config.get('device',{}))
    device.update(neuracle_strict=True,neuracle_host=p['host'].strip(),neuracle_port=int(p['tcp_port']),
        neuracle_eeg_channels=int(p['signal_channels']),neuracle_include_trigger_channel=True,
        trigger_serial_port=p['serial_port'],lsl_marker_enabled=False)
    config['device']=device
    storage=dict(config.get('storage',{}))
    original=Path(storage.get('records_dir','data/sourcedata/v3'))
    if not original.name.endswith('_neuracle'):original=original.with_name(original.name+'_neuracle')
    storage['records_dir']=original.as_posix();config['storage']=storage


def select_profile(root,parent=None):
    from psychopy.gui import qtgui
    from serial.tools.list_ports import comports
    W=qtgui.QtWidgets
    p=load_profile(root)
    dialog=W.QDialog(parent);dialog.setWindowTitle('博睿康 TCP 与真实同步盒');dialog.resize(620,330)
    form=W.QFormLayout(dialog)
    host=W.QLineEdit(p['host']);port=W.QSpinBox();port.setRange(1,65535);port.setValue(p['tcp_port'])
    rate=W.QSpinBox();rate.setRange(1,10000);rate.setValue(int(p['sfreq']))
    count=W.QSpinBox();count.setRange(1,512);count.setValue(p['signal_channels'])
    serial=W.QComboBox();serial.addItem('请选择真实同步盒串口','')
    for item in comports():
        text=' '.join([item.description or '',item.hwid or '',item.manufacturer or '']).lower()
        if 'usb' not in (item.hwid or '').lower() or any(v in text for v in ('virtual','vspe','com0com','com2com','虚拟')):continue
        serial.addItem(f'{item.device} — {item.description} — {item.hwid}',item.device)
        if item.device==p['serial_port']:serial.setCurrentIndex(serial.count()-1)
    for label,field in [('转发电脑 IP',host),('TCP 端口',port),('信号采样率 Hz（不含 TRG）',rate),('信号通道数（不含 TRG）',count),('同步盒串口',serial)]:form.addRow(label,field)
    note=W.QLabel('先在 Collect 启动数据转发。检测会发送测试码 250、251、252，并核对 TRG 回传。\n正式实验会重新检查；64 信号模式按参考范式通道名称取数，TRG 保存为最后一行。信号 250 Hz / TRG 1000 Hz 时，采样率填 250；原始 TRG 另存。');note.setWordWrap(True);form.addRow(note)
    buttons=W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok|W.QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
    if not dialog.exec():return None
    p=dict(host=host.text().strip(),tcp_port=port.value(),sfreq=rate.value(),signal_channels=count.value(),serial_port=serial.currentData())
    if not p['serial_port']:raise ValueError('请选择真实 USB 同步盒串口。')
    configure({},p)
    path=Path(root)/'neuracle.local.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
    return p


def probe(config):
    import time
    from video_eeg.experiment.video_runner import build_acquirer,build_marker_backend
    acquirer=build_acquirer(device_name='neuracle',config=config)
    backend=None
    try:
        acquirer.start_stream()
        backend=build_marker_backend(config);acquirer.bind_marker(backend)
        samples=0
        # Drain startup data before sending unique diagnostic codes.
        end=time.monotonic()+.25
        while time.monotonic()<end:
            data,_=acquirer.get_new_samples();samples+=data.shape[1];time.sleep(.01)
        for code in (250,251,252):
            backend.send(code)
            deadline=time.monotonic()+4
            while backend.pending:
                data,_=acquirer.get_new_samples();samples+=data.shape[1]
                backend.check_health()
                if time.monotonic()>deadline:raise RuntimeError('TRG 测试回传超时')
                time.sleep(.01)
            # Allow the hardware pulse to return to zero.
            end=time.monotonic()+.15
            while time.monotonic()<end:
                data,_=acquirer.get_new_samples();samples+=data.shape[1];time.sleep(.01)
        end=time.monotonic()+1
        while time.monotonic()<end:
            data,_=acquirer.get_new_samples();samples+=data.shape[1];backend.check_health();time.sleep(.01)
        if samples<int(acquirer.metadata.sfreq):raise RuntimeError('收到的数据不足一秒，不能开始实验。')
        return dict(device='neuracle',channels=acquirer.metadata.n_channels,sfreq=acquirer.metadata.sfreq,
            samples=samples,serial_port=backend.port,recording_mode='neuracle_tcp_local',
            expected_sampling_rate_hz=acquirer.metadata.sfreq,**acquirer.recording_metadata(),
            **backend.recording_metadata(),test_codes=[250,251,252])
    finally:
        acquirer.stop_stream()
        if backend is not None:backend.close()
