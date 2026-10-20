"""Explicit, freshly validated serial sender selection."""
def select_port():
    from psychopy.gui import qtgui
    from video_eeg.utils.serial_ports import available_ports, require_trigger_port
    qtgui.ensureQtApp()
    widgets = qtgui.QtWidgets
    dialog = widgets.QDialog()
    dialog.setWindowTitle('EmotivPRO：选择标记发送端')
    dialog.setMinimumWidth(640)
    layout = widgets.QVBoxLayout(dialog)
    intro = widgets.QLabel('选择虚拟串口对的发送端；EmotivPRO 监听配对的另一个端口。\n'
        '例如范式发送 COM10，EmotivPRO 接收 COM11；不能选择同一个端口。\n'
        '脑电接收器的通信端口不等于 Trigger 输入口。\n'
        '端口存在或可以打开，都不能证明脑电在线或标记已收到。')
    intro.setWordWrap(True)
    layout.addWidget(intro)
    combo = widgets.QComboBox()
    layout.addWidget(combo)
    detail = widgets.QLabel()
    detail.setWordWrap(True)
    layout.addWidget(detail)
    confirmed = widgets.QCheckBox('已确认这是发送端，EmotivPRO 使用配对的另一端')
    layout.addWidget(confirmed)
    buttons = widgets.QHBoxLayout()
    refresh = widgets.QPushButton('刷新端口')
    accept = widgets.QPushButton('使用所选端口')
    cancel = widgets.QPushButton('取消')
    for button in (refresh, accept, cancel):
        buttons.addWidget(button)
    layout.addLayout(buttons)
    result = []

    def update():
        row = combo.currentData()
        eligible = bool(row and not row['blocked_reason'])
        detail.setText((f"硬件标识：{row['hwid']}\n" +
            (row['blocked_reason'] or '端口已列出；配对关系及实际接收效果仍需核对。'))
            if row else '未选择端口。创建虚拟串口对或接入标记线后点击刷新。')
        confirmed.setEnabled(eligible)
        accept.setEnabled(eligible and confirmed.isChecked())

    def changed():
        confirmed.setChecked(False)
        update()

    def scan():
        combo.clear()
        combo.addItem('请选择标记发送端（不自动选择）', None)
        try:
            for row in available_ports():
                status = ('不可用于此模式' if row['blocked_reason'] else
                    '虚拟串口，需确认配对端' if row['port_kind'] == 'virtual_pair' else '待确认用途')
                combo.addItem(f"{row['port']} — {row['description']}（{status}）", row)
        except Exception as exc:
            widgets.QMessageBox.warning(dialog, '扫描失败', str(exc))
        changed()

    def use_port():
        row = combo.currentData()
        if not row or not confirmed.isChecked():
            return
        try:
            current = require_trigger_port(row['port'])
            if (current['hwid'], current['serial_number']) != (row['hwid'], row['serial_number']):
                raise ValueError('端口对应设备已变化，请刷新列表后重新确认。')
        except ValueError as exc:
            widgets.QMessageBox.warning(dialog, '端口不可用', str(exc))
            scan()
            return
        result.append(current['port'])
        dialog.accept()

    combo.currentIndexChanged.connect(changed)
    confirmed.toggled.connect(update)
    refresh.clicked.connect(scan)
    accept.clicked.connect(use_port)
    cancel.clicked.connect(dialog.reject)
    scan()
    (getattr(dialog, 'exec', None) or dialog.exec_)()
    return result[0] if result else ''
