"""Command-line diagnostics for BrainCo EEG caps after firmware upgrades."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any


@dataclass
class BleDevice:
    device_id: str
    name: str
    rssi: int
    pairing: bool
    battery: int


async def _await_if_needed(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def _device_from_callback(args: tuple[Any, ...]) -> BleDevice | None:
    payload = next((item for item in reversed(args) if hasattr(item, "id")), None)
    if payload is None:
        return None
    device_id = str(getattr(payload, "id", "")).strip()
    name = str(getattr(payload, "name", "")).strip()
    if not device_id or not name.startswith("Zephyr [EEG-"):
        return None
    return BleDevice(
        device_id=device_id,
        name=name,
        rssi=int(getattr(payload, "rssi", -999)),
        pairing=bool(getattr(payload, "is_in_pairing_mode", False)),
        battery=int(getattr(payload, "battery_level", 0)),
    )


def _format_value(value: Any) -> str:
    if value is None:
        return "<none>"
    attrs = {}
    for name in (
        "manufacturer",
        "model",
        "serial",
        "hardware",
        "firmware",
        "ssid",
        "ip",
        "addr",
        "port",
        "connected",
        "enabled",
    ):
        if hasattr(value, name):
            attrs[name] = getattr(value, name)
    return repr(attrs) if attrs else repr(value)


async def _scan(sdk: Any, seconds: float) -> list[BleDevice]:
    devices: dict[str, BleDevice] = {}

    def on_device(*args: Any) -> None:
        device = _device_from_callback(args)
        if device is None:
            return
        previous = devices.get(device.device_id)
        if previous is None or device.rssi > previous.rssi:
            devices[device.device_id] = device

    await _await_if_needed(sdk.init_adapter())
    sdk.set_device_discovered_callback(on_device)
    sdk.ble_start_scan()
    try:
        await asyncio.sleep(seconds)
    finally:
        sdk.ble_stop_scan()
        await asyncio.sleep(0.25)
        sdk.set_device_discovered_callback(None)
    return sorted(devices.values(), key=lambda item: item.rssi, reverse=True)


async def _inspect(sdk: Any, device_id: str, timeout: float) -> bool:
    print(f"\nConnecting over BLE: {device_id}")
    connected = False
    try:
        await asyncio.wait_for(_await_if_needed(sdk.ble_connect(device_id)), timeout)
        connected = True
        print("BLE connection: OK")
        for label, call in (
            ("Device info", sdk.get_ble_device_info),
            ("Wi-Fi config", sdk.get_wifi_config),
            ("Wi-Fi status", sdk.get_wifi_status),
        ):
            try:
                value = await asyncio.wait_for(_await_if_needed(call(device_id)), timeout)
                print(f"{label}: {_format_value(value)}")
            except Exception as exc:
                print(f"{label}: ERROR {type(exc).__name__}: {exc}")
        return True
    except Exception as exc:
        print(f"BLE connection: ERROR {type(exc).__name__}: {exc}")
        print("Put the selected cap into Bluetooth pairing mode, then retry.")
        return False
    finally:
        if connected:
            try:
                await asyncio.wait_for(_await_if_needed(sdk.ble_disconnect(device_id)), timeout)
            except Exception as exc:
                print(f"BLE disconnect warning: {type(exc).__name__}: {exc}")


async def _main_async(args: argparse.Namespace) -> int:
    try:
        import bc_ecap_sdk as sdk
    except ImportError as exc:
        print(f"Cannot import bc_ecap_sdk from {sys.executable}: {exc}")
        return 1

    print(f"Python: {sys.executable}")
    try:
        distribution_version = version("bc-ecap-sdk")
    except PackageNotFoundError:
        distribution_version = "<unknown>"
    print(f"bc-ecap-sdk distribution version: {distribution_version}")
    print(f"bc_ecap_sdk module version: {getattr(sdk, '__version__', '<unknown>')}")
    print(f"BLE scan: {args.scan_seconds:.1f} seconds")
    devices = await _scan(sdk, args.scan_seconds)
    if not devices:
        print("No Zephyr/BrainCo EEG device was found over BLE.")
        return 2

    print("\nBrainCo BLE devices (strongest signal first):")
    print("RSSI   Pairing  Battery  Device ID           Name")
    visible_devices = devices if args.limit <= 0 else devices[: args.limit]
    for device in visible_devices:
        pairing = "yes" if device.pairing else "no"
        print(
            f"{device.rssi:>4}   {pairing:<7}  {device.battery:>3}%     "
            f"{device.device_id:<19} {device.name}"
        )
    if len(visible_devices) < len(devices):
        print(f"... {len(devices) - len(visible_devices)} more device(s); use --limit 0 to show all.")

    if not args.inspect:
        nearest = devices[0]
        print(f"\nNearest candidate: {nearest.device_id} ({nearest.name}, {nearest.rssi} dBm)")
        print("Inspection was not requested; no BLE connection was made.")
        return 0

    device_id = args.device_id.strip()
    if not device_id:
        print("\n--inspect requires --device-id so the wrong nearby cap is not connected.")
        return 3
    return 0 if await _inspect(sdk, device_id, args.connect_timeout) else 4


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan BrainCo/Zephyr EEG caps over BLE and optionally inspect Wi-Fi status."
    )
    parser.add_argument("--scan-seconds", type=float, default=8.0)
    parser.add_argument("--limit", type=int, default=20, help="Maximum scan results to print; 0 shows all.")
    parser.add_argument("--inspect", action="store_true", help="Connect read-only and query device/Wi-Fi status.")
    parser.add_argument("--device-id", default="", help="BLE device ID shown by the scan.")
    parser.add_argument("--connect-timeout", type=float, default=15.0)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main_async(_parse_args())))
