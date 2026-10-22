"""Windows process/USB supervision, NOT EEG or recording-state telemetry."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import threading
import time

from video_eeg.experiment.eeg_health import EegAcquisitionError

APP_NAMES = {'emotivpro.exe', 'emotivpro_zh.exe'}
RECEIVER_USB_ID = (0x1915, 0xc00a)  # This deployment's USB840M/nRF52 interface.


class GuardError(EegAcquisitionError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _windows_for_processes(pids):
    import ctypes
    from ctypes import wintypes as w
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user.EnumWindows.restype = w.BOOL
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.GetWindowTextLengthW.argtypes = [w.HWND]
    user.IsWindowVisible.argtypes = [w.HWND]
    user.IsHungAppWindow.argtypes = [w.HWND]
    found = {pid: [] for pid in pids}
    def visit(hwnd, _):
        pid = w.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in found and user.IsWindowVisible(hwnd) and user.GetWindowTextLengthW(hwnd):
            found[pid.value].append(not bool(user.IsHungAppWindow(hwnd)))
        return True
    callback = callback_type(visit)
    if not user.EnumWindows(callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return found


def observe_environment():
    if sys.platform != 'win32':
        raise OSError('当前 EmotivPRO 外部录制监测只支持 Windows。')
    import psutil
    from serial.tools.list_ports import comports
    processes = []
    for process in psutil.process_iter(['pid', 'name', 'create_time']):
        info = process.info
        if str(info.get('name', '')).lower() in APP_NAMES:
            processes.append(dict(name=info['name'], pid=info['pid'], started=info['create_time']))
    windows = _windows_for_processes([p['pid'] for p in processes]) if processes else {}
    for p in processes:
        states = windows[p['pid']]
        p.update(window=bool(states), responding=bool(states) and all(states))
    receivers = [dict(vid=p.vid, pid=p.pid, serial_number=p.serial_number,
                      location=p.location, port=p.device) for p in comports()]
    return dict(processes=processes, receivers=receivers)


class EnvironmentGuard:
    poll_interval_sec = .5
    stale_timeout_sec = 3.

    def __init__(self, *, observer=None, monotonic=None):
        self._observe = observer or observe_environment
        self._clock = monotonic or time.monotonic
        self._snapshot = None
        self._binding = None
        self._fresh = None
        self._error = None
        self._log_path = None
        self._thread = None
        self._closed = False
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.poll()

    def _append(self, row):
        if self._log_path is not None:
            with self._log_path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(row, timestamp_unix_sec=time.time()), ensure_ascii=False)+'\n')

    def _fail(self, code, message):
        first = False
        with self._lock:
            if self._error is None:
                self._error = dict(code=code, message=message, timestamp_unix_sec=time.time())
                first = True
            error = dict(self._error)
        if first:
            try: self._append(dict(status='failed', error=error, observation=self._snapshot))
            except OSError: pass  # Metadata and the session fault handler still preserve the cause.
        raise GuardError(error['code'], error['message'])

    def _raise_if_fault(self):
        if self._error:
            raise GuardError(self._error['code'], self._error['message'])

    def _validate(self, state):
        apps = [p for p in state['processes'] if str(p.get('name', '')).lower() in APP_NAMES]
        if not apps:
            self._fail('app_missing', 'EmotivPRO 未运行或已退出。EMOTIV Launcher / Cortex 后台服务不能替代录制软件。')
        if len(apps) != 1:
            self._fail('app_ambiguous', '发现多个 EmotivPRO 进程，无法确定本次录制，请关闭多余实例后重新检查。')
        app = apps[0]
        if not app.get('window'):
            self._fail('app_window_missing', '未检测到 EmotivPRO 主窗口，请等待软件启动并打开主窗口后重新检查。')
        if not app.get('responding'):
            self._fail('app_unresponsive', 'Windows 报告 EmotivPRO 窗口无响应，已停止本次实验。')
        if not app.get('pid') or app.get('started') is None:
            self._fail('app_unknown', '无法确认 EmotivPRO 进程身份，不能开始或继续实验。')
        receivers = [p for p in state['receivers'] if (p.get('vid'), p.get('pid')) == RECEIVER_USB_ID]
        if not receivers:
            self._fail('receiver_missing', '未检测到本方案使用的 USB840M / nRF52 接收器接口，可能已拔出或驱动失效。请检查 USB 连接。')
        if len(receivers) != 1:
            self._fail('receiver_ambiguous', '检测到多个 nRF52 接口，无法确定本次接收器，请仅连接本次使用的接收器后重新检查。')
        receiver = receivers[0]
        identity = receiver.get('serial_number') or receiver.get('location')
        if not identity:
            self._fail('receiver_unknown', '无法获取接收器 USB 身份，不能仅凭 COM 编号确认设备。')
        result = dict(app_pid=app['pid'], app_started=app['started'], app_name=app['name'],
                      app_responding=True, receiver_identity=f'1915:c00a:{identity}',
                      receiver_port=receiver['port'], receiver_usb_present=True)
        binding = (result['app_pid'], result['app_started'], result['receiver_identity'])
        if self._binding is not None and binding != self._binding:
            self._fail('environment_changed', 'EmotivPRO 已重启或 USB 接收器已更换。本次实验停止，请重新核对录制后重启范式。')
        self._binding = binding
        return result

    def poll(self):
        self._raise_if_fault()
        if self._closed:
            return
        if self._fresh is not None and self._clock()-self._fresh > self.stale_timeout_sec:
            self._fail('monitor_stale', '外部录制环境监测超过 3 秒未更新，可能发生休眠或程序阻塞，已停止实验。')
        try:
            snapshot = self._validate(self._observe())
            self._raise_if_fault()
            if self._closed:
                return
            self._snapshot = snapshot
            self._fresh = self._clock()
            self._append(dict(status='ok', observation=snapshot))
        except GuardError:
            raise
        except Exception as exc:
            self._fail('monitor_error', f'外部录制环境监测失败：{exc}')

    def start_recording(self, directory, part):
        self.poll()
        self._log_path = Path(directory)/f'emotivpro_guard_part_{part:03d}.jsonl'
        try:
            with self._log_path.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(status='ok', observation=self._snapshot,
                    timestamp_unix_sec=time.time()), ensure_ascii=False)+'\n')
        except Exception as exc:
            self._fail('monitor_log_error', f'监测日志无法保存：{exc}')
        self._thread = threading.Thread(target=self._loop, name='emotivpro-environment', daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.wait(self.poll_interval_sec):
            try:
                self.poll()
            except GuardError:
                return

    def check_health(self):
        self._raise_if_fault()
        if self._closed:
            self._fail('monitor_closed', '外部录制环境监测已关闭。')
        if self._fresh is None or self._clock()-self._fresh > self.stale_timeout_sec:
            self._fail('monitor_stale', '外部录制环境监测超过 3 秒未更新，已停止实验。')

    def metadata(self):
        return dict(enabled=True, observation=copy.deepcopy(self._snapshot),
                    error=copy.deepcopy(self._error), poll_interval_sec=self.poll_interval_sec,
                    stale_timeout_sec=self.stale_timeout_sec,
                    log_file=self._log_path.name if self._log_path else None,
                    recording_verified=False, headset_wireless_verified=False,
                    marker_received_verified=False,
                    measures='EmotivPRO process/window and USB receiver presence only; not recording, wireless EEG, sample arrival or marker receipt')

    def close(self):
        self._closed = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.)
