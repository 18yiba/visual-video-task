"""Fresh port inventory; enumeration cannot establish EEG or marker connectivity."""
from __future__ import annotations


def available_ports() -> list[dict]:
    from serial.tools import list_ports
    rows = []
    for port in sorted(list_ports.comports()):
        details = ' '.join(str(getattr(port, key, '') or '') for key in
                           ('description', 'hwid', 'manufacturer', 'product')).lower()
        reason = ''
        virtual_pair = any(word in details for word in ('com0com', 'cncport', 'vspd', 'vspe',
            'eltima virtual', 'eltima software', 'eterlogic', 'hhd virtual'))
        if (port.vid, port.pid) == (0x1915, 0xC00A) or 'nrf52 connectivity' in details:
            reason = ('nRF52 通信接口：尚未确认支持 EmotivPRO 单字节 Trigger，'
                      '本入口不向此接口发送标记。')
        rows.append(dict(port=port.device, description=port.description or '未知设备',
                         hwid=port.hwid, vid=port.vid, pid=port.pid,
                         serial_number=port.serial_number, blocked_reason=reason,
                         port_kind='virtual_pair' if virtual_pair else 'physical_or_unknown'))
    return rows


def require_trigger_port(name: str) -> dict:
    name = str(name).strip()
    for row in available_ports():
        if row['port'].casefold() == name.casefold():
            if row['blocked_reason']:
                raise ValueError(f"{row['port']}：{row['blocked_reason']}")
            return row
    raise ValueError(f'串口 {name or "（未选择）"} 不存在或已拔出，请刷新列表后重新选择。')
