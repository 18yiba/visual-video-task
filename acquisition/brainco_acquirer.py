"""BrainCo EEG Cap acquisition backend backed by the bc_ecap_sdk package."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Awaitable, Sequence
from typing import Any

import numpy as np

from acquisition.base import AbstractAcquirer, AcquirerMetadata, EEGChunk

LOGGER = logging.getLogger(__name__)
_BRAINCO_MDNS_SERVICE = "_brainco-eeg._tcp.local."

_SAMPLE_RATE_TO_ENUM = {
    250: "SR_250Hz",
    500: "SR_500Hz",
    1000: "SR_1000Hz",
    2000: "SR_2000Hz",
}

_GAIN_TO_ENUM = {
    1: "GAIN_1",
    2: "GAIN_2",
    4: "GAIN_4",
    6: "GAIN_6",
    8: "GAIN_8",
    12: "GAIN_12",
    24: "GAIN_24",
}


class BrainCoAcquirer(AbstractAcquirer):
    """Wrap BrainCo's async TCP SDK behind the unified acquirer API."""

    def __init__(
        self,
        sfreq: float = 250.0,
        n_channels: int = 32,
        buffer_sec: float = 60.0,
        brainco_addr: str = "",
        brainco_port: int = 0,
        auto_discover: bool = True,
        scan_timeout_sec: float = 6.0,
        ready_timeout_sec: float = 10.0,
        start_retries: int = 2,
        eeg_gain: int = 6,
        signal_source: str = "NORMAL",
        device_id: str = "eeg-cap",
    ) -> None:
        if n_channels <= 0 or n_channels > 32:
            raise ValueError("BrainCo EEG Cap supports 1-32 EEG channels.")
        if int(sfreq) not in _SAMPLE_RATE_TO_ENUM:
            allowed = ", ".join(str(v) for v in sorted(_SAMPLE_RATE_TO_ENUM))
            raise ValueError(f"Unsupported BrainCo sample rate {sfreq}. Allowed: {allowed}")
        if eeg_gain not in _GAIN_TO_ENUM:
            allowed = ", ".join(str(v) for v in sorted(_GAIN_TO_ENUM))
            raise ValueError(f"Unsupported BrainCo gain {eeg_gain}. Allowed: {allowed}")

        self.metadata = AcquirerMetadata(name="brainco", sfreq=float(sfreq), n_channels=n_channels)
        self._buffer_sec = float(buffer_sec)
        self._brainco_addr = brainco_addr.strip()
        self._brainco_port = int(brainco_port)
        self._auto_discover = bool(auto_discover)
        self._scan_timeout_sec = float(scan_timeout_sec)
        self._ready_timeout_sec = float(ready_timeout_sec)
        self._start_retries = max(int(start_retries), 1)
        self._eeg_gain = int(eeg_gain)
        self._signal_source = signal_source.strip().upper() or "NORMAL"
        self._device_id = device_id

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._client: Any = None
        self._sdk: Any = None
        self._cache_lock = threading.Lock()
        self._first_sample_event = threading.Event()
        self._response_event = threading.Event()
        self._msg_resp_lock = threading.Lock()
        self._eeg_cache = np.empty((n_channels, 0), dtype=np.float32)
        self._pending_msg_responses: dict[int, deque[tuple[Any, ...]]] = {}
        self._generic_msg_responses: deque[tuple[Any, ...]] = deque()
        self._raw_packet_count = 0
        self._callback_sample_count = 0
        self._total_samples_seen = 0
        self._last_chunk_total_samples = 0
        self._last_raw_packet_monotonic = 0.0
        self._last_msg_response_monotonic = 0.0
        self._cached_discovery_target: tuple[str, int] | None = None

    def start_stream(self) -> None:
        import bc_ecap_sdk as sdk

        if self._client is not None:
            self.stop_stream()

        last_error: Exception | None = None

        for attempt in range(1, self._start_retries + 1):
            self._sdk = sdk
            self._first_sample_event.clear()
            self._response_event.clear()
            with self._cache_lock:
                self._eeg_cache = np.empty((self.metadata.n_channels, 0), dtype=np.float32)
            with self._msg_resp_lock:
                self._pending_msg_responses.clear()
                self._generic_msg_responses.clear()
            self._raw_packet_count = 0
            self._callback_sample_count = 0
            self._total_samples_seen = 0
            self._last_chunk_total_samples = 0
            self._last_raw_packet_monotonic = 0.0
            self._last_msg_response_monotonic = 0.0
            self._start_loop_thread()
            addr, port = self._resolve_addr_port()
            self._client = sdk.ECapClient(addr, port)
            parser = sdk.MessageParser(self._device_id, sdk.MsgType.EEGCap)
            self._register_sdk_callbacks()

            try:
                self._run_sdk_call(self._client.start_data_stream, parser)
                buffer_len = max(int(self.metadata.sfreq * min(self._buffer_sec, 60.0)), 1024)
                sdk.set_cfg(buffer_len, max(256, int(self.metadata.sfreq)), 256)
                config_msg_id = self._run_sdk_call(
                    self._client.set_eeg_config,
                    getattr(sdk.EegSampleRate, _SAMPLE_RATE_TO_ENUM[int(self.metadata.sfreq)]),
                    getattr(sdk.EegSignalGain, _GAIN_TO_ENUM[self._eeg_gain]),
                    getattr(sdk.EegSignalSource, self._signal_source),
                )
                # Some BrainCo firmware/SDK combinations apply EEG config successfully
                # but never surface a matching msg response callback for this command.
                # Treat missing config acks like start_eeg_stream: warn and continue,
                # then rely on actual EEG sample arrival as the final success criterion.
                self._wait_for_command_response(config_msg_id, "set_eeg_config", allow_missing=True)
                sdk.clear_eeg_buffer()
                start_msg_id = self._run_sdk_call(self._client.start_eeg_stream)
                self._wait_for_command_response(start_msg_id, "start_eeg_stream", allow_missing=True)
                self._wait_for_samples()
                break
            except Exception as exc:
                last_error = exc
                LOGGER.warning(
                    "BrainCo stream start attempt %s/%s failed: %s",
                    attempt,
                    self._start_retries,
                    exc,
                )
                self.stop_stream()
                if attempt >= self._start_retries:
                    raise
                time.sleep(0.5)
        else:
            if last_error is not None:
                raise last_error

        LOGGER.info(
            "BrainCo acquisition started at %s:%s sfreq=%.1fHz channels=%s",
            addr,
            port,
            self.metadata.sfreq,
            self.metadata.n_channels,
        )

    def stop_stream(self) -> None:
        sdk = self._sdk
        client = self._client
        self._client = None

        if client is not None:
            try:
                self._run_sdk_call(client.stop_eeg_stream)
            except Exception as exc:
                LOGGER.warning("Failed to stop BrainCo EEG stream cleanly: %s", exc)
            try:
                client.disconnect_tcp_blocking()
            except Exception as exc:
                LOGGER.warning("Failed to disconnect BrainCo TCP client cleanly: %s", exc)

        if sdk is not None:
            try:
                sdk.clear_eeg_buffer()
            except Exception:
                pass
            self._clear_sdk_callbacks()

        self._stop_loop_thread()
        self._sdk = None
        self._first_sample_event.clear()
        self._response_event.clear()
        with self._cache_lock:
            self._eeg_cache = np.empty((self.metadata.n_channels, 0), dtype=np.float32)
        with self._msg_resp_lock:
            self._pending_msg_responses.clear()
            self._generic_msg_responses.clear()
        self._raw_packet_count = 0
        self._callback_sample_count = 0
        self._total_samples_seen = 0
        self._last_chunk_total_samples = 0
        self._last_raw_packet_monotonic = 0.0
        self._last_msg_response_monotonic = 0.0
        LOGGER.info("BrainCo acquisition stopped")

    def get_chunk(self, window_sec: float) -> EEGChunk:
        if self._client is None or self._sdk is None:
            raise RuntimeError("BrainCo stream is not started")

        required = int(window_sec * self.metadata.sfreq)
        if required <= 0:
            raise RuntimeError("window_sec must yield at least one sample")

        deadline = time.monotonic() + max(window_sec, 0.1) + self._ready_timeout_sec
        # Keep pulling until we have enough buffered data and at least one new sample
        # since the previous sliding-window request. Otherwise repeated get_chunk()
        # calls can return the exact same trailing window forever.
        while time.monotonic() < deadline:
            self._drain_eeg_buffer()
            if self._cache_sample_count() >= required and self._total_samples_seen > self._last_chunk_total_samples:
                break
            time.sleep(0.05)
        available = self._cache_sample_count()
        if available < required:
            raise RuntimeError(f"Not enough BrainCo samples yet: have {available}, need {required}")
        if self._total_samples_seen <= self._last_chunk_total_samples:
            raise RuntimeError("BrainCo stream produced no new samples for realtime chunking.")
        with self._cache_lock:
            eeg = np.asarray(self._eeg_cache[: self.metadata.n_channels, -required:], dtype=np.float32)
        self._last_chunk_total_samples = self._total_samples_seen
        timestamps = np.arange(required, dtype=np.float64) / self.metadata.sfreq
        return eeg, timestamps

    def get_new_samples(self) -> EEGChunk:
        if self._client is None or self._sdk is None:
            raise RuntimeError("BrainCo stream is not started")
        data = self._drain_eeg_buffer()
        if data.size == 0:
            return (
                np.empty((self.metadata.n_channels, 0), dtype=np.float32),
                np.empty((0,), dtype=np.float64),
            )
        timestamps = np.arange(data.shape[1], dtype=np.float64) / self.metadata.sfreq
        return data, timestamps

    def _resolve_addr_port(self) -> tuple[str, int]:
        if self._brainco_addr and self._brainco_port > 0:
            return self._brainco_addr, self._brainco_port
        if self._cached_discovery_target is not None:
            return self._cached_discovery_target
        if not self._auto_discover:
            raise RuntimeError("BrainCo address/port missing and auto_discover is disabled.")
        target = self._discover_device()
        self._cached_discovery_target = target
        return target

    def _discover_device(self) -> tuple[str, int]:
        assert self._sdk is not None
        result = self._run_coroutine(self._discover_device_async(), timeout=self._scan_timeout_sec + 2.0)
        return result

    async def _discover_device_async(self) -> tuple[str, int]:
        assert self._sdk is not None
        try:
            scan_result = await asyncio.wait_for(
                self._coerce_sdk_awaitable(self._sdk.mdns_start_scan()),
                timeout=self._scan_timeout_sec,
            )
        except asyncio.TimeoutError:
            await self._stop_sdk_mdns_scan_async()
            zeroconf_resolved = await self._discover_device_via_zeroconf_async()
            if zeroconf_resolved is not None:
                return zeroconf_resolved
            callback_resolved = await self._discover_device_via_callback_async()
            if callback_resolved is not None:
                return callback_resolved
            raise RuntimeError("BrainCo auto-discovery timed out.")
        await self._stop_sdk_mdns_scan_async()

        candidates: list[Any]
        if isinstance(scan_result, Sequence) and not isinstance(scan_result, (str, bytes, bytearray)):
            candidates = list(scan_result)
        else:
            candidates = [scan_result]
        candidates = [item for item in candidates if item is not None]
        if not candidates:
            raise RuntimeError("BrainCo auto-discovery found no devices.")

        missing_port_addr: str | None = None
        for device in candidates:
            resolved = self._coerce_discovered_target(device)
            if resolved is not None:
                return resolved
            partial_addr = self._extract_candidate_addr(device)
            if partial_addr and missing_port_addr is None:
                missing_port_addr = partial_addr

        if missing_port_addr:
            zeroconf_resolved = await self._discover_device_via_zeroconf_async()
            if zeroconf_resolved is not None:
                return zeroconf_resolved
            raise RuntimeError(
                "BrainCo auto-discovery found the device address "
                f"{missing_port_addr!r} but no port. Set device.brainco_port in config.yaml."
            )
        zeroconf_resolved = await self._discover_device_via_zeroconf_async()
        if zeroconf_resolved is not None:
            return zeroconf_resolved
        callback_resolved = await self._discover_device_via_callback_async()
        if callback_resolved is not None:
            return callback_resolved
        raise RuntimeError(f"BrainCo auto-discovery returned invalid target(s): {candidates!r}")

    async def _stop_sdk_mdns_scan_async(self) -> None:
        assert self._sdk is not None
        try:
            stop_op = self._sdk.mdns_stop_scan()
            if hasattr(stop_op, "__await__"):
                await self._coerce_sdk_awaitable(stop_op)
        except Exception:
            pass

    async def _discover_device_via_callback_async(self) -> tuple[str, int] | None:
        """Fallback discovery path for SDK builds that surface data via callbacks."""

        assert self._sdk is not None
        start_scan_multi = getattr(self._sdk, "mdns_start_scan_multi", None)
        if start_scan_multi is None:
            return None

        loop = asyncio.get_running_loop()
        discovered: asyncio.Future[tuple[str, int]] = loop.create_future()
        scan_task: asyncio.Task[Any] | None = None

        def on_device(device: Any) -> None:
            resolved = self._coerce_discovered_target(device)
            if resolved is None or discovered.done():
                return
            def deliver() -> None:
                if not discovered.done():
                    discovered.set_result(resolved)

            loop.call_soon_threadsafe(deliver)

        try:
            scan_op = start_scan_multi(on_device)
            if hasattr(scan_op, "__await__"):
                scan_task = asyncio.create_task(self._coerce_sdk_awaitable(scan_op))
            return await asyncio.wait_for(discovered, timeout=self._scan_timeout_sec)
        except asyncio.TimeoutError:
            return None
        finally:
            try:
                stop_op = self._sdk.mdns_stop_scan()
                if hasattr(stop_op, "__await__"):
                    await self._coerce_sdk_awaitable(stop_op)
            except Exception:
                pass
            if scan_task is not None and not scan_task.done():
                scan_task.cancel()
                try:
                    await scan_task
                except Exception:
                    pass

    async def _discover_device_via_zeroconf_async(self) -> tuple[str, int] | None:
        """Fallback to direct Zeroconf browsing when the SDK omits the TCP port."""

        return await asyncio.to_thread(self._discover_device_via_zeroconf_blocking)

    def _discover_device_via_zeroconf_blocking(self) -> tuple[str, int] | None:
        """Resolve BrainCo's mDNS service to an address and port using zeroconf."""

        try:
            from zeroconf import IPVersion, ServiceBrowser, ServiceListener, Zeroconf
        except ImportError:
            LOGGER.info("zeroconf is not installed; skipping direct BrainCo mDNS fallback")
            return None

        timeout_ms = max(int(self._scan_timeout_sec * 1000), 1000)
        resolved: tuple[str, int] | None = None
        resolved_event = threading.Event()
        zeroconf = Zeroconf()

        class Listener(ServiceListener):
            def add_service(self, zc: Any, service_type: str, name: str) -> None:
                self._resolve(zc, service_type, name)

            def update_service(self, zc: Any, service_type: str, name: str) -> None:
                self._resolve(zc, service_type, name)

            def remove_service(self, zc: Any, service_type: str, name: str) -> None:
                return

            def _resolve(self, zc: Any, service_type: str, name: str) -> None:
                nonlocal resolved
                if resolved_event.is_set():
                    return
                info = zc.get_service_info(service_type, name, timeout=timeout_ms)
                if info is None:
                    return
                addresses = info.parsed_addresses(IPVersion.All)
                if not addresses or int(info.port) <= 0:
                    return
                resolved = (addresses[0], int(info.port))
                resolved_event.set()

        browser: Any = None
        try:
            browser = ServiceBrowser(zeroconf, _BRAINCO_MDNS_SERVICE, listener=Listener())
            resolved_event.wait(self._scan_timeout_sec)
            if resolved is not None:
                LOGGER.info("BrainCo device discovered via zeroconf: addr=%s port=%s", resolved[0], resolved[1])
            return resolved
        finally:
            if browser is not None:
                browser.cancel()
            zeroconf.close()

    def _coerce_discovered_target(self, device: Any) -> tuple[str, int] | None:
        """Normalize SDK discovery outputs into a concrete TCP target."""

        addr = self._extract_candidate_addr(device)
        port = self._extract_candidate_port(device)
        if not addr:
            return None
        if port <= 0 and self._brainco_port > 0:
            LOGGER.warning(
                "BrainCo auto-discovery returned address without port: %r. Falling back to configured port %s.",
                device,
                self._brainco_port,
            )
            port = self._brainco_port
        if port <= 0:
            return None
        LOGGER.info(
            "BrainCo device discovered: model=%s sn=%s addr=%s port=%s",
            getattr(device, "model", "unknown"),
            getattr(device, "sn", "unknown"),
            addr,
            port,
        )
        return addr, port

    def _extract_candidate_addr(self, device: Any) -> str:
        candidate: Any = None
        if isinstance(device, dict):
            candidate = (
                device.get("addr")
                or device.get("address")
                or device.get("host")
                or device.get("hostname")
                or device.get("ip")
            )
        elif isinstance(device, Sequence) and not isinstance(device, (str, bytes, bytearray)):
            if len(device) >= 1:
                candidate = device[0]
        else:
            candidate = (
                getattr(device, "addr", None)
                or getattr(device, "address", None)
                or getattr(device, "host", None)
                or getattr(device, "hostname", None)
            )

        if candidate is None and isinstance(device, (str, bytes, bytearray)):
            text = device.decode("utf-8", errors="ignore") if isinstance(device, (bytes, bytearray)) else device
            candidate, _ = self._split_discovery_text(text)
        return str(candidate).strip() if candidate not in (None, "") else ""

    def _extract_candidate_port(self, device: Any) -> int:
        candidate: Any = None
        if isinstance(device, dict):
            candidate = device.get("port")
        elif isinstance(device, Sequence) and not isinstance(device, (str, bytes, bytearray)):
            if len(device) >= 2:
                candidate = device[1]
        else:
            candidate = getattr(device, "port", None)

        if candidate in (None, "") and isinstance(device, (str, bytes, bytearray)):
            text = device.decode("utf-8", errors="ignore") if isinstance(device, (bytes, bytearray)) else device
            _, candidate = self._split_discovery_text(text)
        try:
            return int(candidate)
        except (TypeError, ValueError):
            return 0

    def _split_discovery_text(self, text: str) -> tuple[str, int]:
        """Parse discovery strings like 'host:port' while preserving plain IP strings."""

        value = text.strip()
        if not value:
            return "", 0
        bracket_match = re.fullmatch(r"\[(.+)\]:(\d+)", value)
        if bracket_match is not None:
            return bracket_match.group(1).strip(), int(bracket_match.group(2))
        if value.count(":") == 1:
            host, port_text = value.rsplit(":", 1)
            if host and port_text.isdigit():
                return host.strip(), int(port_text)
        return value, 0

    def _drain_eeg_buffer(self) -> np.ndarray:
        """Fetch any newly available BrainCo samples into the local rolling cache."""

        assert self._sdk is not None
        take = max(int(self.metadata.sfreq * min(self._buffer_sec, 60.0)), 256)
        data = self._normalize_buffer(self._sdk.get_eeg_buffer(take, True), allow_empty=True)
        if data.shape[1] == 0:
            return data

        self._append_eeg_samples(data, from_callback=False)
        return data

    def _wait_for_samples(self) -> None:
        deadline = time.monotonic() + self._ready_timeout_sec
        while time.monotonic() < deadline:
            if self._first_sample_event.is_set():
                return
            data = self._drain_eeg_buffer()
            if data.shape[1] > 0:
                return
            self._first_sample_event.wait(timeout=0.1)
        if self._raw_packet_count <= 0:
            raise RuntimeError(
                "Timed out waiting for BrainCo EEG samples. "
                "No TCP payloads or SDK message responses were observed after start_eeg_stream; "
                "the device likely rejected the command sequence or the configured device_id/protocol does not match."
            )
        raise RuntimeError(
            "Timed out waiting for BrainCo EEG samples. "
            "TCP payloads were observed, but neither the SDK callback path nor get_eeg_buffer() produced EEG data."
        )

    def _register_sdk_callbacks(self) -> None:
        assert self._sdk is not None
        self._sdk.set_connection_state_callback(self._handle_connection_state_callback)
        self._sdk.set_received_data_callback(self._handle_received_data_callback)
        self._sdk.set_msg_resp_callback(self._handle_message_response_callback)

    def _clear_sdk_callbacks(self) -> None:
        assert self._sdk is not None
        try:
            self._sdk.set_connection_state_callback(self._noop_callback)
        except Exception:
            pass
        try:
            self._sdk.set_received_data_callback(self._noop_callback)
        except Exception:
            pass
        try:
            self._sdk.set_msg_resp_callback(self._noop_callback)
        except Exception:
            pass

    def _handle_connection_state_callback(self, *args: Any) -> None:
        if args:
            LOGGER.info("BrainCo connection state callback: %s", ", ".join(repr(arg) for arg in args))

    def _handle_received_data_callback(self, *args: Any) -> None:
        self._raw_packet_count += 1
        self._last_raw_packet_monotonic = time.monotonic()
        self._response_event.set()

    def _handle_message_response_callback(self, *args: Any) -> None:
        self._last_msg_response_monotonic = time.monotonic()
        self._response_event.set()
        message_id = self._extract_message_id(args)
        with self._msg_resp_lock:
            if message_id is None:
                self._generic_msg_responses.append(tuple(args))
            else:
                self._pending_msg_responses.setdefault(message_id, deque()).append(tuple(args))
        if args:
            LOGGER.debug("BrainCo message response callback: %s", ", ".join(repr(arg) for arg in args))

    def _append_eeg_samples(self, data: np.ndarray, *, from_callback: bool) -> None:
        if data.shape[1] == 0:
            return
        max_samples = max(int(self.metadata.sfreq * self._buffer_sec), data.shape[1], 1)
        with self._cache_lock:
            self._eeg_cache = np.concatenate([self._eeg_cache, data], axis=1)
            if self._eeg_cache.shape[1] > max_samples:
                self._eeg_cache = self._eeg_cache[:, -max_samples:]
            self._total_samples_seen += int(data.shape[1])
        if from_callback:
            self._callback_sample_count += int(data.shape[1])
        self._first_sample_event.set()

    def _cache_sample_count(self) -> int:
        with self._cache_lock:
            return int(self._eeg_cache.shape[1])

    def _wait_for_command_response(self, msg_id: Any, label: str, *, allow_missing: bool = False) -> None:
        if not isinstance(msg_id, int) or msg_id <= 0:
            return

        deadline = time.monotonic() + self._ready_timeout_sec
        while time.monotonic() < deadline:
            with self._msg_resp_lock:
                responses = self._pending_msg_responses.get(msg_id)
                if responses:
                    responses.popleft()
                    if not responses:
                        self._pending_msg_responses.pop(msg_id, None)
                    return
                if self._generic_msg_responses:
                    self._generic_msg_responses.popleft()
                    LOGGER.debug(
                        "Using generic BrainCo response as acknowledgement for %s (msgId=%s).",
                        label,
                        msg_id,
                    )
                    return
            if self._response_event.wait(timeout=0.1):
                self._response_event.clear()

        if allow_missing:
            LOGGER.warning(
                "Timed out waiting for BrainCo response to %s (msgId=%s); continuing and waiting for EEG samples.",
                label,
                msg_id,
            )
            return
        raise RuntimeError(f"Timed out waiting for BrainCo response to {label} (msgId={msg_id}).")

    def _extract_message_id(self, payload: Any) -> int | None:
        if isinstance(payload, bool):
            return None
        if isinstance(payload, int):
            return payload if payload > 0 else None
        if isinstance(payload, dict):
            for key in ("msgId", "msg_id", "id"):
                message_id = self._extract_message_id(payload.get(key))
                if message_id is not None:
                    return message_id
            return None
        if isinstance(payload, (str, bytes, bytearray)):
            text = payload.decode("utf-8", errors="ignore") if isinstance(payload, (bytes, bytearray)) else payload
            match = re.search(r'"?msgId"?\s*[:=]\s*(\d+)', text)
            if match is not None:
                return int(match.group(1))
            return None
        if isinstance(payload, Sequence):
            for value in payload:
                message_id = self._extract_message_id(value)
                if message_id is not None:
                    return message_id
            return None
        for attr in ("msgId", "msg_id", "id"):
            if hasattr(payload, attr):
                message_id = self._extract_message_id(getattr(payload, attr))
                if message_id is not None:
                    return message_id
        return None

    @staticmethod
    def _noop_callback(*args: Any) -> None:
        return

    def _normalize_buffer(self, raw: Any, *, allow_empty: bool = False) -> np.ndarray:
        if raw is None:
            raw = []
        if isinstance(raw, np.ndarray):
            arr = np.asarray(raw, dtype=np.float32)
        else:
            arr = np.asarray(raw, dtype=np.float32)

        if arr.size == 0:
            if allow_empty:
                return np.empty((self.metadata.n_channels, 0), dtype=np.float32)
            raise RuntimeError("BrainCo EEG buffer is empty.")

        if arr.ndim == 1:
            if arr.size % self.metadata.n_channels != 0:
                raise RuntimeError(
                    f"Unexpected BrainCo buffer size {arr.size} for {self.metadata.n_channels} channels"
                )
            arr = arr.reshape(-1, self.metadata.n_channels)

        if arr.ndim != 2:
            raise RuntimeError(f"Unexpected BrainCo buffer shape: {arr.shape}")

        if arr.shape[1] == self.metadata.n_channels:
            return arr.T
        if arr.shape[0] == self.metadata.n_channels:
            return arr
        if arr.shape[1] > self.metadata.n_channels:
            return arr[:, : self.metadata.n_channels].T
        if arr.shape[0] > self.metadata.n_channels:
            return arr[: self.metadata.n_channels, :]
        raise RuntimeError(f"Unexpected BrainCo channel layout: {arr.shape}")

    def _start_loop_thread(self) -> None:
        if self._loop is not None:
            return

        ready = threading.Event()

        def runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            ready.set()
            loop.run_forever()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

        self._loop_thread = threading.Thread(target=runner, name="brainco-sdk-loop", daemon=True)
        self._loop_thread.start()
        if not ready.wait(timeout=2.0):
            raise RuntimeError("Failed to start BrainCo asyncio loop thread.")

    def _stop_loop_thread(self) -> None:
        loop = self._loop
        thread = self._loop_thread
        self._loop = None
        self._loop_thread = None
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=2.0)

    async def _coerce_sdk_awaitable(self, value: Any) -> Any:
        if hasattr(value, "__await__"):
            return await value
        return value

    def _run_sdk_call(self, func: Any, *args: Any) -> Any:
        async def runner() -> Any:
            return await self._coerce_sdk_awaitable(func(*args))

        return self._run_coroutine(runner(), timeout=self._ready_timeout_sec)

    def _run_coroutine(self, coro: Awaitable[Any], timeout: float) -> Any:
        if self._loop is None:
            raise RuntimeError("BrainCo asyncio loop is not running.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise RuntimeError("BrainCo SDK call timed out.") from exc
