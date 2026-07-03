"""Command-line entry point for the video-EEG experiment platform."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import numpy as np
import yaml
from rich.console import Console
from rich.table import Table

from acquisition.factory import AcquirerFactory, register_default_acquirers
from protocol.video_protocol import EegSessionManager, VideoProtocolConfig, build_playlist
from tasks.task_factory import load_task_from_config
from utils.markers import TRIGGER_REFERENCE, TriggerBoxMarkerBackend, NoOpMarkerBackend

LOGGER = logging.getLogger(__name__)
CONSOLE = Console()
DEFAULT_CONFIG_FILENAME = "config.yaml"
_PROJECT_DEFAULT_CONFIG_PATH = Path(__file__).with_name(DEFAULT_CONFIG_FILENAME)
_DEFAULT_CONFIG_TEMPLATE: dict[str, Any] = {
    "subject_id": "S001",
    "session_id": 1,
    "task_mode": "visual",
    "device_type": "dummy",
    "hardware_dummy_mode": False,
    "sfreq": 250,
    "buffer_sec": 120,
    "protocol": {
        "fixation_sec": 1.5,
        "default_video_sec": 8.0,
        "blank_sec": 1.0,
        "iti_sec": 2.0,
        "baseline_sec": 60.0,
        "trials_per_session": 90,
        "video_dir": "videos",
        "random_seed": 17,
    },
    "device": {
        "neuracle_host": "127.0.0.1",
        "neuracle_port": 8712,
        "brainco_addr": "",
        "brainco_port": 0,
        "brainco_auto_discover": True,
        "brainco_scan_timeout_sec": 6.0,
        "brainco_ready_timeout_sec": 20.0,
        "brainco_start_retries": 2,
        "brainco_gain": 6,
        "brainco_signal_source": "NORMAL",
        "brainco_device_id": "eeg-cap",
        "trigger_serial_port": "",
    },
    "storage": {
        "records_dir": "records_storage",
        "ratings_dir": "ratings_storage",
    },
}


@dataclass(slots=True)
class AppContext:
    config: dict[str, Any]
    config_path: Path
    console: Console


def default_config() -> dict[str, Any]:
    if _PROJECT_DEFAULT_CONFIG_PATH.exists():
        with _PROJECT_DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as handle:
            project_template = yaml.safe_load(handle) or {}
        if isinstance(project_template, dict):
            return deepcopy(project_template)
    return deepcopy(_DEFAULT_CONFIG_TEMPLATE)


def resolve_config_path(config_path: Path | None = None) -> Path:
    if config_path is not None:
        return Path(config_path).expanduser().resolve()
    cwd_config = Path.cwd() / DEFAULT_CONFIG_FILENAME
    if cwd_config.exists():
        return cwd_config.resolve()
    return _PROJECT_DEFAULT_CONFIG_PATH.resolve()


def write_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)


def ensure_config_exists(path: Path) -> Path:
    if not path.exists():
        write_config(path, default_config())
        LOGGER.info("Created default config at %s", path)
    return path


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


def load_config(path: Path) -> dict[str, Any]:
    path = ensure_config_exists(resolve_config_path(path))
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    required_keys = {"subject_id", "device_type", "sfreq"}
    missing = sorted(required_keys - set(config))
    if missing:
        raise click.ClickException(f"Missing required config keys: {', '.join(missing)}")
    return config


def default_device_channels(device_name: str) -> int:
    return 32 if device_name == "brainco" else 64


def build_acquirer(*, device_name: str, config: dict[str, Any]) -> Any:
    register_default_acquirers()
    device_cfg = config.get("device", {})
    device_name = "dummy" if bool(config.get("hardware_dummy_mode", False)) else device_name
    kwargs: dict[str, Any] = {
        "sfreq": float(config["sfreq"]),
        "n_channels": default_device_channels(device_name),
        "buffer_sec": float(config.get("buffer_sec", 120.0)),
    }
    if device_name == "neuracle":
        kwargs["neuracle_host"] = str(device_cfg.get("neuracle_host", "127.0.0.1"))
        kwargs["neuracle_port"] = int(device_cfg.get("neuracle_port", 8712))
    if device_name == "brainco":
        kwargs["brainco_addr"] = str(device_cfg.get("brainco_addr", ""))
        kwargs["brainco_port"] = int(device_cfg.get("brainco_port", 0))
        kwargs["auto_discover"] = bool(device_cfg.get("brainco_auto_discover", True))
        kwargs["scan_timeout_sec"] = float(device_cfg.get("brainco_scan_timeout_sec", 6.0))
        kwargs["ready_timeout_sec"] = float(device_cfg.get("brainco_ready_timeout_sec", 20.0))
        kwargs["start_retries"] = int(device_cfg.get("brainco_start_retries", 2))
        kwargs["eeg_gain"] = int(device_cfg.get("brainco_gain", 6))
        kwargs["signal_source"] = str(device_cfg.get("brainco_signal_source", "NORMAL"))
        kwargs["device_id"] = str(device_cfg.get("brainco_device_id", "eeg-cap"))
    return AcquirerFactory.create(device_name, **kwargs)


def build_marker_backend(config: dict[str, Any]) -> Any:
    serial_port = str(config.get("device", {}).get("trigger_serial_port", "")).strip()
    if serial_port:
        return TriggerBoxMarkerBackend(serial_port)
    return NoOpMarkerBackend()


@click.group(invoke_without_command=True)
@click.option("--config", "config_path", type=click.Path(dir_okay=False, path_type=Path), default=None)
@click.pass_context
def cli(ctx: click.Context, config_path: Path | None) -> None:
    """Video-EEG experiment CLI."""
    setup_logging()
    resolved = resolve_config_path(config_path)
    config = load_config(resolved)
    ctx.obj = AppContext(config=config, config_path=resolved, console=CONSOLE)
    if ctx.invoked_subcommand is None:
        CONSOLE.print("使用 [bold]video-eeg gui[/bold] 启动 Streamlit 实验台，或 --help 查看子命令。")


@cli.command()
@click.pass_obj
def gui(app: AppContext) -> None:
    """Launch the Streamlit graphical user interface."""
    gui_script = Path(__file__).with_name("gui.py").resolve()
    if not gui_script.exists():
        raise click.ClickException("gui.py not found.")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(gui_script), "--", "--config", str(app.config_path)]
    )


@cli.command("list-devices")
def list_devices() -> None:
    register_default_acquirers()
    table = Table(title="EEG Devices")
    table.add_column("Device")
    for device_name in AcquirerFactory.list_devices():
        table.add_row(device_name)
    CONSOLE.print(table)


@cli.command("list-triggers")
def list_triggers() -> None:
    table = Table(title="Video-EEG Trigger Codes")
    table.add_column("Code")
    table.add_column("Description")
    for code in sorted(TRIGGER_REFERENCE):
        table.add_row(str(code), TRIGGER_REFERENCE[code])
    CONSOLE.print(table)


@cli.command("probe-device")
@click.option("--device", "device_name", type=str, default=None)
@click.option("--duration", type=float, default=5.0, show_default=True)
@click.pass_obj
def probe_device(app: AppContext, device_name: str | None, duration: float) -> None:
    config = app.config
    selected = device_name or str(config["device_type"])
    acquirer = build_acquirer(device_name=selected, config=config)
    app.console.print(f"[cyan]Connecting device={selected} channels={acquirer.metadata.n_channels}[/cyan]")
    try:
        acquirer.start_stream()
        time.sleep(max(duration, 0.1))
        window, _ = acquirer.get_chunk(2.0)
        app.console.print(
            f"[green]OK[/green] shape={window.shape} mean={window.mean():.3f} std={window.std():.3f}"
        )
    finally:
        acquirer.stop_stream()


@cli.command("dry-run")
@click.option("--trials", type=int, default=2, show_default=True, help="Number of mock trials to run.")
@click.pass_obj
def dry_run(app: AppContext, trials: int) -> None:
    """Run a short mock session to verify EEG pull + trigger alignment."""
    config = app.config
    protocol = VideoProtocolConfig.from_config(config)
    playlist = build_playlist(protocol)[:trials]
    acquirer = build_acquirer(device_name=str(config["device_type"]), config=config)
    task = load_task_from_config(config)
    marker_backend = task.wrap_marker_backend(build_marker_backend(config))
    records_dir = Path(str(config.get("storage", {}).get("records_dir", "records_storage")))
    manager = EegSessionManager(
        acquirer,
        marker_backend,
        sfreq=float(config["sfreq"]),
        records_dir=records_dir,
        subject_id=str(config["subject_id"]),
        session_id=int(config.get("session_id", 1)),
    )
    session_dir = manager.start(metadata={"dry_run": True, "trials": trials})
    app.console.print(f"[cyan]Session started[/cyan] {session_dir}")
    if protocol.baseline_sec > 0:
        manager.run_baseline(min(protocol.baseline_sec, 3.0))
    for trial_idx, video_name in enumerate(playlist):
        manager.begin_trial(trial_idx=trial_idx, video_name=video_name)
        manager.fixation_on(trial_idx=trial_idx, video_name=video_name)
        time.sleep(min(protocol.fixation_sec, 1.0))
        manager.fixation_off(trial_idx=trial_idx)
        manager.video_on(trial_idx=trial_idx, video_name=video_name)
        time.sleep(min(protocol.default_video_sec, 2.0))
        manager.video_off(trial_idx=trial_idx, video_name=video_name)
        manager.blank_on(trial_idx=trial_idx)
        time.sleep(min(protocol.blank_sec, 0.5))
        manager.blank_off(trial_idx=trial_idx)
        manager.rating_on(trial_idx=trial_idx, video_name=video_name)
        time.sleep(0.2)
        manager.rating_off(trial_idx=trial_idx)
        manager.end_trial(trial_idx=trial_idx, video_name=video_name)
        manager.iti_on(trial_idx=trial_idx)
        time.sleep(min(protocol.iti_sec, 0.5))
        manager.iti_off(trial_idx=trial_idx)
    exported = manager.stop_and_export(metadata={"dry_run": True, "playlist": playlist})
    app.console.print(f"[green]Exported[/green] {exported}")


if __name__ == "__main__":
    cli()
