"""Marker and command-stream helpers."""

from __future__ import annotations

import json
import logging
import socket
import struct
import threading
import time
from abc import ABC, abstractmethod
from collections import deque

LOGGER = logging.getLogger(__name__)

PROTOCOL_EVENT_CODES = {
    # Session level
    "session_start": 101,
    "session_end": 102,
    # Baseline resting EEG
    "baseline_start": 110,
    "baseline_end": 111,
    # Block breaks (optional long rest)
    "block_start": 120,
    "block_end": 121,
    "block_rest_start": 122,
    "block_rest_end": 123,
    # Trial phase markers — video-EEG protocol
    "fixation_on": 130,
    "fixation_off": 131,
    "video_on": 132,
    "video_off": 133,
    "image_on": 132,
    "image_off": 133,
    "blank_on": 134,
    "blank_off": 135,
    "rating_on": 136,
    "rating_off": 137,
    "iti_on": 138,
    "iti_off": 139,
    # Trial boundaries
    "trial_start": 140,
    "trial_end": 141,
    "attention_task_on": 142,
    "attention_response": 143,
    "rating_item_on": 144,
    "rating_item_off": 145,
}

# Human-readable trigger reference for experiment documentation.
TRIGGER_REFERENCE = {
    101: "session_start — 实验 session 开始",
    102: "session_end — 实验 session 结束",
    110: "baseline_start — 静息基线开始",
    111: "baseline_end — 静息基线结束",
    120: "block_start — block 开始",
    121: "block_end — block 结束",
    122: "block_rest_start — block 间休息开始",
    123: "block_rest_end — block 间休息结束",
    130: "fixation_on — 注视十字出现",
    131: "fixation_off — 注视十字结束",
    132: "video_on/image_on — 视频或图片开始呈现",
    133: "video_off/image_off — 视频或图片呈现结束",
    134: "blank_on — 空屏开始",
    135: "blank_off — 空屏结束",
    136: "rating_on — 行为评分界面出现",
    137: "rating_off — 行为评分提交完成",
    138: "iti_on — trial 间隔开始",
    139: "iti_off — trial 间隔结束",
    140: "trial_start — 单个 trial 开始",
    141: "trial_end — 单个 trial 结束",
    142: "attention_task_on — 随机注意力任务出现",
    143: "attention_response — 随机注意力任务按键响应",
    144: "rating_item_on — 图片范式二单个评分题目出现",
    145: "rating_item_off — 图片范式二单个评分题目结束",
}


def _encode_command_payload(command: str) -> bytes:
    return json.dumps(
        {
            "command": command,
            "ts_ms": int(time.time() * 1000),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"


class MarkerBackend(ABC):
    """Abstract marker sink."""

    @abstractmethod
    def send(self, label: int, timestamp: float | None = None) -> None:
        """Emit a marker value."""

    def send_event(self, event_name: str, timestamp: float | None = None) -> None:
        """Emit a named protocol marker when supported."""

        code = PROTOCOL_EVENT_CODES.get(event_name)
        if code is None:
            raise ValueError(f"Unknown protocol event: {event_name}")
        self.send(code, timestamp=timestamp)


class NoOpMarkerBackend(MarkerBackend):
    """Fallback marker sink for environments without hardware triggers."""

    def send(self, label: int, timestamp: float | None = None) -> None:
        LOGGER.debug("No-op marker emitted label=%s timestamp=%s", label, timestamp)

    def send_event(self, event_name: str, timestamp: float | None = None) -> None:
        LOGGER.debug("No-op protocol marker emitted event=%s timestamp=%s", event_name, timestamp)


class TriggerBoxMarkerBackend(MarkerBackend):
    """Neuracle TriggerBox serial backend with handshake and response checks."""

    DEVICE_ID = 1
    BAUDRATE = 115200
    DEVICE_NAME_GET = 4
    DEVICE_INFO_GET = 3
    OUTPUT_EVENT_DATA = 225
    ERROR_RESPONSE = 131

    def __init__(self, serial_port: str = "auto", *, timeout_sec: float = 1.5) -> None:
        import serial
        import serial.tools.list_ports

        configured = str(serial_port or "auto").strip()
        ports = list(serial.tools.list_ports.comports())
        candidates = [port.device for port in ports] if configured.lower() == "auto" else [configured]
        if not candidates:
            raise RuntimeError(
                "未检测到任何COM口，无法连接Neuracle TriggerBox。请检查USB数据线、设备供电和USB串口驱动。"
            )

        self._serial: serial.Serial | None = None
        self.serial_port = ""
        self.device_name = ""
        self.device_info: dict[str, int] = {}
        errors: list[str] = []
        available = {port.device: port.description for port in ports}
        for candidate in candidates:
            try:
                self._serial = serial.Serial(
                    candidate,
                    baudrate=self.BAUDRATE,
                    timeout=float(timeout_sec),
                    write_timeout=float(timeout_sec),
                )
                self.serial_port = candidate
                name_payload = self._transact(self.DEVICE_NAME_GET)
                self.device_name = name_payload.rstrip(b"\x00").decode("utf-8", errors="replace")
                info = self._transact(self.DEVICE_INFO_GET, b"\x01")
                if len(info) < 8:
                    raise RuntimeError(f"设备信息响应过短：{len(info)}字节")
                self.device_info = {
                    "hardware_version": int(info[0]),
                    "firmware_version": int(info[1]),
                    "sensor_count": int(info[2]),
                    "device_id": int.from_bytes(info[4:8], byteorder="big"),
                }
                return
            except Exception as exc:
                errors.append(f"{candidate} ({available.get(candidate, 'unknown')}): {exc}")
                self.close()
        raise RuntimeError("未找到可响应Neuracle协议的TriggerBox。" + "；".join(errors))

    def send(self, label: int, timestamp: float | None = None) -> None:
        del timestamp
        value = int(label)
        if not 1 <= value <= 255:
            raise ValueError(f"TriggerBox事件码必须在1-255之间：{value}")
        response = self._transact(self.OUTPUT_EVENT_DATA, bytes([value]))
        if not response or int(response[0]) != self.OUTPUT_EVENT_DATA:
            raise RuntimeError(f"TriggerBox未确认事件码{value}，响应={response!r}")

    def close(self) -> None:
        connection = self._serial
        self._serial = None
        if connection is not None and connection.is_open:
            connection.close()

    def _transact(self, function_id: int, payload: bytes = b"") -> bytes:
        connection = self._serial
        if connection is None or not connection.is_open:
            raise RuntimeError("TriggerBox串口未打开")
        frame = struct.pack("<BBH", self.DEVICE_ID, int(function_id), len(payload)) + payload
        connection.reset_input_buffer()
        connection.write(frame)
        connection.flush()
        header = self._read_exact(4)
        device_id, response_function, payload_size = struct.unpack("<BBH", header)
        if device_id != self.DEVICE_ID:
            raise RuntimeError(f"TriggerBox设备ID不匹配：{device_id}")
        response_payload = self._read_exact(payload_size)
        if response_function == self.ERROR_RESPONSE:
            error_code = int(response_payload[0]) if response_payload else -1
            raise RuntimeError(f"TriggerBox返回错误码：{error_code}")
        if response_function != int(function_id):
            raise RuntimeError(
                f"TriggerBox功能码不匹配：请求{function_id}，响应{response_function}"
            )
        return response_payload

    def _read_exact(self, size: int) -> bytes:
        connection = self._serial
        if connection is None:
            raise RuntimeError("TriggerBox串口未打开")
        data = connection.read(int(size))
        if len(data) != int(size):
            raise TimeoutError(f"TriggerBox响应超时：需要{size}字节，收到{len(data)}字节")
        return data


class LSLMarkerBackend(MarkerBackend):
    """Publish integer experiment markers for BCIGo/LabRecorder."""

    def __init__(
        self,
        stream_name: str = "visual-video-task-Markers",
        stream_type: str = "Markers",
        source_id: str = "visual-video-task-marker",
    ) -> None:
        from pylsl import StreamInfo, StreamOutlet

        info = StreamInfo(
            str(stream_name).strip() or "visual-video-task-Markers",
            str(stream_type).strip() or "Markers",
            1,
            0.0,
            "int32",
            str(source_id).strip() or "visual-video-task-marker",
        )
        channels = info.desc().append_child("channels")
        channels.append_child("channel").append_child_value("label", "event_code")
        self._outlet = StreamOutlet(info)

    def send(self, label: int, timestamp: float | None = None) -> None:
        if timestamp is None:
            self._outlet.push_sample([int(label)])
        else:
            self._outlet.push_sample([int(label)], float(timestamp))

    def have_consumers(self) -> bool:
        """Return whether BCIGo (or another recorder) subscribed to this stream."""

        return bool(self._outlet.have_consumers())

    def wait_for_consumers(self, timeout_sec: float) -> bool:
        """Wait until BCIGo has selected and opened the Marker stream."""

        return bool(self._outlet.wait_for_consumers(float(timeout_sec)))


class CompositeMarkerBackend(MarkerBackend):
    """Fan one marker out to multiple synchronized sinks."""

    def __init__(self, *backends: MarkerBackend) -> None:
        self._backends = tuple(backends)

    def send(self, label: int, timestamp: float | None = None) -> None:
        for backend in self._backends:
            backend.send(label, timestamp=timestamp)

    def wait_for_consumers(self, timeout_sec: float) -> bool:
        waitable = [
            backend for backend in self._backends if hasattr(backend, "wait_for_consumers")
        ]
        return all(backend.wait_for_consumers(timeout_sec) for backend in waitable)


class LSLCommandOutlet:
    """LSL stream used to publish decoded MI commands."""

    def __init__(self, stream_name: str, stream_type: str) -> None:
        from pylsl import StreamInfo, StreamOutlet

        info = StreamInfo(stream_name, stream_type, 1, 0.0, "string", "oi-mi-command-stream")
        self._outlet = StreamOutlet(info)

    def push(self, command: str) -> None:
        self._outlet.push_sample([command], time.time())


class ArTcpCommandSender:
    """TCP client for the AR game command server."""

    def __init__(self, host: str, port: int, *, timeout_sec: float = 1.0) -> None:
        self._host = host
        self._port = port
        self._timeout_sec = timeout_sec
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    def push(self, command: str) -> None:
        payload = _encode_command_payload(command)
        with self._lock:
            try:
                self._ensure_connected()
                assert self._sock is not None
                self._sock.sendall(payload)
            except OSError as exc:
                self._close_locked()
                raise RuntimeError(
                    f"Failed to send AR command to {self._host}:{self._port}: {exc}"
                ) from exc

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _ensure_connected(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.create_connection(
            (self._host, self._port),
            timeout=self._timeout_sec,
        )
        self._sock.settimeout(self._timeout_sec)

    def _close_locked(self) -> None:
        if self._sock is None:
            return
        try:
            self._sock.close()
        finally:
            self._sock = None


class ArTcpCommandRelay:
    """PC-side relay that accepts a reverse Unity connection and local producers."""

    def __init__(
        self,
        local_host: str,
        local_port: int,
        *,
        downstream_bind_host: str = "0.0.0.0",
        downstream_bind_port: int = 5006,
        timeout_sec: float = 1.0,
    ) -> None:
        self._local_host = local_host
        self._local_port = local_port
        self._downstream_bind_host = downstream_bind_host
        self._downstream_bind_port = downstream_bind_port
        self._timeout_sec = timeout_sec

        self._running = True
        self._local_listener: socket.socket | None = None
        self._downstream_listener: socket.socket | None = None
        self._downstream_client: socket.socket | None = None
        self._downstream_lock = threading.Lock()
        self._pending_payloads: deque[bytes] = deque(maxlen=64)
        self._threads: list[threading.Thread] = []

        self._start_thread(self._run_local_listener, "oi-mi-local-command-relay")
        self._start_thread(self._run_downstream_listener, "oi-mi-downstream-command-relay")
        LOGGER.info(
            "AR command relay started. local=%s:%s downstream=%s:%s",
            self._local_host,
            self._local_port,
            self._downstream_bind_host,
            self._downstream_bind_port,
        )

    def push(self, command: str) -> None:
        self._forward_payload(_encode_command_payload(command))

    def close(self) -> None:
        self._running = False
        self._close_socket(self._local_listener)
        self._local_listener = None
        self._close_socket(self._downstream_listener)
        self._downstream_listener = None
        with self._downstream_lock:
            self._close_socket(self._downstream_client)
            self._downstream_client = None
        for thread in self._threads:
            thread.join(timeout=1.0)

    def _start_thread(self, target: callable, name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _run_local_listener(self) -> None:
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self._local_host, self._local_port))
            listener.listen()
            listener.settimeout(0.5)
            self._local_listener = listener
        except OSError as exc:
            LOGGER.error(
                "Failed to start local AR command relay listener on %s:%s: %s",
                self._local_host,
                self._local_port,
                exc,
            )
            return

        while self._running:
            try:
                client, remote = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            LOGGER.info("Accepted local AR command producer from %s:%s", remote[0], remote[1])
            self._start_thread(
                lambda sock=client: self._handle_local_client(sock),
                f"oi-mi-local-command-producer-{remote[0]}:{remote[1]}",
            )

    def _handle_local_client(self, client: socket.socket) -> None:
        try:
            client.settimeout(0.5)
            buffer = bytearray()
            while self._running:
                try:
                    chunk = client.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break

                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    line_break = buffer.find(b"\n")
                    if line_break < 0:
                        break
                    line = bytes(buffer[:line_break]).strip()
                    del buffer[: line_break + 1]
                    if line:
                        self._forward_payload(line + b"\n")
        finally:
            self._close_socket(client)

    def _run_downstream_listener(self) -> None:
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self._downstream_bind_host, self._downstream_bind_port))
            listener.listen()
            listener.settimeout(0.5)
            self._downstream_listener = listener
        except OSError as exc:
            LOGGER.error(
                "Failed to start downstream AR relay listener on %s:%s: %s",
                self._downstream_bind_host,
                self._downstream_bind_port,
                exc,
            )
            return

        while self._running:
            try:
                client, remote = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            LOGGER.info("Unity downstream connected from %s:%s", remote[0], remote[1])
            client.settimeout(1.0)
            with self._downstream_lock:
                self._close_socket(self._downstream_client)
                self._downstream_client = client
                self._flush_pending_payloads_locked()

            self._start_thread(
                lambda sock=client, addr=remote[0], port=remote[1]: self._monitor_downstream_client(sock, addr, port),
                f"oi-mi-downstream-monitor-{remote[0]}:{remote[1]}",
            )

    def _monitor_downstream_client(self, client: socket.socket, host: str, port: int) -> None:
        try:
            while self._running:
                try:
                    data = client.recv(1)
                except socket.timeout:
                    continue
                except OSError:
                    break

                if not data:
                    break
        finally:
            LOGGER.info("Unity downstream disconnected from %s:%s", host, port)
            with self._downstream_lock:
                if self._downstream_client is client:
                    self._close_socket(self._downstream_client)
                    self._downstream_client = None
            self._close_socket(client)

    def _forward_payload(self, payload: bytes) -> None:
        with self._downstream_lock:
            client = self._downstream_client
            if client is None:
                self._pending_payloads.append(payload)
                LOGGER.debug("Buffered AR command because no Unity downstream client is connected.")
                return
            try:
                client.sendall(payload)
            except OSError as exc:
                LOGGER.warning("Failed to forward AR command to downstream Unity client: %s", exc)
                self._close_socket(client)
                if self._downstream_client is client:
                    self._downstream_client = None
                self._pending_payloads.append(payload)

    def _flush_pending_payloads_locked(self) -> None:
        client = self._downstream_client
        if client is None or not self._pending_payloads:
            return

        while self._pending_payloads:
            payload = self._pending_payloads.popleft()
            try:
                client.sendall(payload)
            except OSError as exc:
                LOGGER.warning("Failed to flush buffered AR command to downstream Unity client: %s", exc)
                self._close_socket(client)
                if self._downstream_client is client:
                    self._downstream_client = None
                self._pending_payloads.appendleft(payload)
                return

    @staticmethod
    def _close_socket(sock: socket.socket | None) -> None:
        if sock is None:
            return
        try:
            sock.close()
        except OSError:
            pass

