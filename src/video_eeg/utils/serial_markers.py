"""EmotivPRO serial input: exactly one unsigned byte per marker, no reply."""
from __future__ import annotations

import json
import math
from numbers import Integral
from pathlib import Path
import time

from video_eeg.utils.markers import MarkerBackend


class EmotivProSerialBackend(MarkerBackend):
    delivery_status = 'serial_written_unconfirmed'

    def __init__(self, serial_port: str, *, baudrate: int = 115200,
                 write_timeout: float = .1, connection=None, environment_guard=None):
        if not str(serial_port).strip():
            raise ValueError('请选择标记发送端串口，并确认 EmotivPRO 使用配对的另一端。')
        if not math.isfinite(write_timeout) or not 0 < write_timeout <= 1:
            raise ValueError('Serial write timeout must be in (0, 1] seconds')
        self.port = str(serial_port).strip()
        self.baudrate = int(baudrate)
        self._error = None
        self._receipt = None
        self.receipt_filename = None
        self._count = 0
        self.last_write_accepted = None
        self._last_health_check = float('-inf')
        self.port_info = None
        self._environment_guard = environment_guard
        real_connection = connection is None
        if connection is None:
            import serial
            from video_eeg.utils.serial_ports import require_trigger_port
            self.port_info = require_trigger_port(self.port)
            self.port = self.port_info['port']
            try:
                connection = serial.Serial(self.port, baudrate=self.baudrate, bytesize=8,
                    parity='N', stopbits=1, timeout=0, write_timeout=write_timeout,
                    xonxoff=False, rtscts=False, dsrdtr=False)
            except serial.SerialException as exc:
                raise RuntimeError(
                    f'无法打开串口 {self.port}：可能被占用、已拔出或驱动异常。\n'
                    '范式发送端与 EmotivPRO 接收端不能占用同一个端口。\n'
                    '脑电通信接口不能直接当作标记发送端。\n'
                    f'系统信息：{exc}') from exc
        self._serial = connection
        if real_connection:
            from video_eeg.utils.emotivpro_guard import EnvironmentGuard
            try:
                self._environment_guard = EnvironmentGuard()
            except Exception:
                self._serial.close()
                raise

    def environment_report(self):
        if self._environment_guard is None:
            return dict(enabled=False, reason='injected test connection', recording_verified=False,
                        headset_wireless_verified=False, marker_received_verified=False)
        return self._environment_guard.metadata()

    def check_health(self):
        """Check the driver without transmitting or consuming any marker bytes."""
        if self._error:
            raise RuntimeError(self._error)
        if self._environment_guard is not None:
            self._environment_guard.check_health()
        now = time.monotonic()
        try:
            if not self._serial.is_open:
                raise OSError('串口已关闭')
            if now - self._last_health_check < .5:
                return
            self._last_health_check = now
            # Windows ClearCommError detects a removed adapter without a test write.
            _ = self._serial.in_waiting
        except Exception as exc:
            self._error = f'串口 {self.port} 状态检查失败（可能已拔出）：{exc}'
            raise RuntimeError(self._error) from exc

    def start_recording(self, directory: Path, part: int, title: str):
        del title
        self.receipt_filename = f'emotivpro_serial_part_{part:03d}.jsonl'
        self._receipt = (Path(directory)/self.receipt_filename).open('x', encoding='utf-8')
        if self._environment_guard is not None:
            self._environment_guard.start_recording(directory, part)

    def send(self, label: int, timestamp: float | None = None):
        if isinstance(label, bool) or not isinstance(label, Integral) or not 1 <= label <= 255:
            raise ValueError('EmotivPRO serial marker must be an integer from 1 to 255')
        self.last_write_accepted = False
        if self._error:
            raise RuntimeError(self._error)
        if self._environment_guard is not None:
            self._environment_guard.check_health()
        row = dict(code=int(label), requested_unix_sec=timestamp,
            write_started_unix_sec=time.time(), emotivpro_received=None)
        try:
            self.last_write_accepted = None  # A driver timeout may occur after transmission.
            accepted = self._serial.write(bytes([label]))
            self.last_write_accepted = accepted == 1
            if not self.last_write_accepted:
                raise OSError('Serial write did not accept the complete marker byte')
            self._count += 1
            row.update(status=self.delivery_status, write_completed_unix_sec=time.time())
        except Exception as exc:
            self._error = f'EmotivPRO 串口标记发送失败：{exc}'
            row.update(status='failed', error=self._error)
            raise RuntimeError(self._error) from exc
        finally:
            if self._receipt is not None:
                try:
                    self._receipt.write(json.dumps(row, ensure_ascii=False)+'\n')
                    self._receipt.flush()
                except Exception as exc:
                    self._error = f'EmotivPRO 串口发送日志保存失败：{exc}'
                    raise RuntimeError(self._error) from exc

    def close(self):
        try:
            if self._environment_guard is not None:
                self._environment_guard.close()
            self._serial.close()
        finally:
            if self._receipt is not None:
                self._receipt.close()
                self._receipt = None

    def recording_metadata(self):
        return dict(eeg_recording_mode='emotivpro_external', eeg_mode='external',
            sfreq=None, n_channels=None, expected_sampling_rate_hz=None,
            eeg_parameters_source='EmotivPRO exported recording; not queried by paradigm',
            external_recorder='EmotivPRO', external_recording_verified=False,
            serial_port=self.port, serial_baudrate=self.baudrate, serial_format='8N1/no flow control',
            serial_port_info=self.port_info, eeg_connection_verified=False,
            serial_markers_written=self._count, serial_write_error=self._error,
            serial_marker_log=self.receipt_filename, emotivpro_marker_receipt_verified=False,
            external_environment_guard=self.environment_report(),
            marker_timing='serial byte arrival at EmotivPRO; delay/jitter not calibrated',
            psychopy_flip_synchronized_markers=False)
