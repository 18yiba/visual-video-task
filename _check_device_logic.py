"""One-off sanity check for device_type / hardware_dummy_mode."""
from __future__ import annotations

from acquisition.factory import AcquirerFactory, register_default_acquirers
from cli import build_acquirer, load_config, resolve_config_path, write_config


def main() -> None:
    register_default_acquirers()
    hardware = AcquirerFactory.list_hardware_devices()
    assert "dummy" not in hardware, hardware
    assert "brainco" in hardware and "neuracle" in hardware

    path = resolve_config_path(None)
    cfg = load_config(path)
    assert cfg["device_type"] != "dummy"
    assert isinstance(cfg["hardware_dummy_mode"], bool)

    cfg["hardware_dummy_mode"] = False
    write_config(path, cfg)
    cfg2 = load_config(path)
    assert cfg2["hardware_dummy_mode"] is False
    assert build_acquirer(device_name=cfg2["device_type"], config=dict(cfg2)).metadata.name != "dummy"

    cfg3 = dict(cfg2)
    cfg3["hardware_dummy_mode"] = True
    assert build_acquirer(device_name=cfg3["device_type"], config=cfg3).metadata.name == "dummy"

    # Restore project default: simulate via checkbox, real device selected.
    cfg2["hardware_dummy_mode"] = True
    write_config(path, cfg2)
    print("ok", cfg2["device_type"], "hardware_dummy_mode=", True)


if __name__ == "__main__":
    main()
