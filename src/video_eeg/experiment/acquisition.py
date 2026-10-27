"""Shared device and trigger construction for every experiment runner."""
from __future__ import annotations

from typing import Any

_LSL_MARKER_BACKENDS: dict[tuple[str, str, str], Any] = {}


def expected_sampling_rate(config: dict[str, Any]) -> float:
    value = config.get("eeg_sampling_rate_hz", config.get("sfreq", 1000.0))
    rate = float(value)
    if rate <= 0:
        raise ValueError("video EEG expected sampling rate must be positive")
    return rate


def build_acquirer(*, device_name: str, config: dict[str, Any]) -> Any:
    from video_eeg.devices.factory import AcquirerFactory, register_default_acquirers

    register_default_acquirers()
    device_cfg = dict(config.get("device", {}))
    selected = (
        "dummy"
        if bool(config.get("hardware_dummy_mode", False))
        else str(device_name or config.get("device_type", "brainco")).strip().lower()
    )
    if selected == 'emotivpro':
        from video_eeg.devices.external_recorder_acquirer import ExternalRecorderAcquirer
        return ExternalRecorderAcquirer(sfreq=expected_sampling_rate(config), n_channels=1,
                                       backend_name='emotivpro')
    # BrainCo Demo exercises the same 32-electrode native EDF writer.
    simulated_brainco = selected == 'dummy' and str(config.get('device_type', 'brainco')).lower() == 'brainco'
    n_channels = 32 if selected == "brainco" or simulated_brainco else 64
    neuracle_eeg_channels: int | None = None
    neuracle_include_trigger = False
    if selected == "neuracle":
        neuracle_eeg_channels = int(device_cfg.get("neuracle_eeg_channels", 64))
        if neuracle_eeg_channels <= 0:
            raise RuntimeError("device.neuracle_eeg_channels must be positive")
        neuracle_include_trigger = bool(device_cfg.get("neuracle_include_trigger_channel", True))
        n_channels = neuracle_eeg_channels + int(neuracle_include_trigger)
    kwargs: dict[str, Any] = {
        "sfreq": expected_sampling_rate(config),
        "n_channels": n_channels,
        "buffer_sec": float(config.get("buffer_sec", 180.0)),
    }
    factory_name = selected
    if selected == "neuracle":
        kwargs.update(
            {
                "eeg_channel_count": neuracle_eeg_channels,
                "include_trigger_channel": neuracle_include_trigger,
                "neuracle_host": str(device_cfg.get("neuracle_host", "127.0.0.1")),
                "neuracle_port": int(device_cfg.get("neuracle_port", 8712)),
            }
        )
    elif selected == "brainco":
        transport = str(device_cfg.get("brainco_transport", "bcigo")).strip().lower()
        if transport == "bcigo":
            factory_name = "brainco_bcigo"
            kwargs["backend_name"] = "brainco_bcigo"
        elif transport == "lsl":
            factory_name = "brainco_lsl"
            kwargs.update(
                {
                    "stream_name": str(device_cfg.get("brainco_lsl_stream_name", "")),
                    "stream_type": str(device_cfg.get("brainco_lsl_stream_type", "EEG")),
                    "source_id": str(device_cfg.get("brainco_lsl_source_id", "")),
                    "resolve_timeout_sec": float(device_cfg.get("brainco_lsl_resolve_timeout_sec", 15.0)),
                    "ready_timeout_sec": float(device_cfg.get("brainco_lsl_ready_timeout_sec", 10.0)),
                    "backend_name": "brainco_lsl",
                }
            )
        elif transport == "sdk":
            kwargs.update(
                {
                    "brainco_addr": str(device_cfg.get("brainco_addr", "")),
                    "brainco_port": int(device_cfg.get("brainco_port", 0)),
                    "auto_discover": bool(device_cfg.get("brainco_auto_discover", True)),
                    "scan_timeout_sec": float(device_cfg.get("brainco_scan_timeout_sec", 6.0)),
                    "ready_timeout_sec": float(device_cfg.get("brainco_ready_timeout_sec", 20.0)),
                    "start_retries": int(device_cfg.get("brainco_start_retries", 2)),
                    "eeg_gain": int(device_cfg.get("brainco_gain", 6)),
                    "signal_source": str(device_cfg.get("brainco_signal_source", "NORMAL")),
                    "device_id": str(device_cfg.get("brainco_device_id", "bcigo")),
                }
            )
        else:
            raise RuntimeError("device.brainco_transport must be bcigo, lsl, or sdk")
    if selected == 'neuracle' and device_cfg.get('neuracle_strict'):
        from video_eeg.devices.neuracle_verified import VerifiedNeuracleAcquirer
        return VerifiedNeuracleAcquirer(**kwargs)
    return AcquirerFactory.create(factory_name, **kwargs)


def build_marker_backend(config: dict[str, Any]) -> Any:
    from video_eeg.utils.markers import (
        CompositeMarkerBackend,
        LSLMarkerBackend,
        NoOpMarkerBackend,
        TriggerBoxMarkerBackend,
    )

    device_cfg = dict(config.get("device", {}))
    if str(config.get('device_type', '')).lower() == 'emotivpro':
        if config.get('hardware_dummy_mode'):
            return NoOpMarkerBackend()
        from video_eeg.utils.serial_markers import EmotivProSerialBackend
        return EmotivProSerialBackend(device_cfg.get('emotivpro_serial_port', ''),
            baudrate=int(device_cfg.get('emotivpro_baudrate', 115200)))
    if config.get('device_type') == 'neuracle' and device_cfg.get('neuracle_strict') and not config.get('hardware_dummy_mode'):
        from video_eeg.utils.neuracle_markers import VerifiedTriggerBox
        return VerifiedTriggerBox(device_cfg.get('trigger_serial_port', ''))
    backends: list[Any] = []
    serial_port = str(device_cfg.get("trigger_serial_port", "")).strip()
    if serial_port:
        backends.append(
            TriggerBoxMarkerBackend(
                serial_port,
                timeout_sec=float(device_cfg.get("trigger_serial_timeout_sec", 1.5)),
            )
        )
    brainco_marker = (
        str(config.get("device_type", "")).strip().lower() == "brainco"
        and str(device_cfg.get("brainco_transport", "bcigo")).strip().lower() in {"bcigo", "lsl"}
    )
    if brainco_marker and bool(device_cfg.get("lsl_marker_enabled", True)):
        marker_identity = (
            str(device_cfg.get("lsl_marker_stream_name", "video-eeg-Markers")),
            str(device_cfg.get("lsl_marker_stream_type", "Markers")),
            str(device_cfg.get("lsl_marker_source_id", "video-eeg-marker")),
        )
        backend = _LSL_MARKER_BACKENDS.get(marker_identity)
        if backend is None:
            try:
                backend = LSLMarkerBackend(
                    stream_name=marker_identity[0],
                    stream_type=marker_identity[1],
                    source_id=marker_identity[2],
                )
            except ImportError:
                backend = None
            if backend is not None:
                _LSL_MARKER_BACKENDS[marker_identity] = backend
        if backend is None:
            return NoOpMarkerBackend()
        backends.append(backend)
    if not backends:
        return NoOpMarkerBackend()
    if len(backends) == 1:
        return backends[0]
    return CompositeMarkerBackend(*backends)


def uses_bcigo_external_recording(config: dict[str, Any]) -> bool:
    if bool(config.get("hardware_dummy_mode", False)):
        return False
    return (
        str(config.get("device_type", "brainco")).strip().lower() == "brainco"
        and str(config.get("device", {}).get("brainco_transport", "bcigo")).strip().lower()
        == "bcigo"
    )


def uses_emotivpro_recording(config):
    return str(config.get('device_type', '')).lower() == 'emotivpro' and not config.get('hardware_dummy_mode', False)


def uses_external_recording(config):
    return uses_emotivpro_recording(config) or uses_bcigo_external_recording(config)


