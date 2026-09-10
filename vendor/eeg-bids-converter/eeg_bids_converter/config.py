from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConverterError


@dataclass(slots=True)
class DatasetConfig:
    name: str = "EEG Image Dataset"
    description: str = "Raw EEG and behavior data converted from heterogeneous experiment exports."
    bids_version: str = "1.11.1"
    dataset_type: str = "raw"
    authors: list[str] = field(default_factory=list)
    license: str | None = None
    acknowledgements: str | None = None
    how_to_acknowledge: str | None = None
    funding: list[str] = field(default_factory=list)
    ethics_approvals: list[str] = field(default_factory=list)
    references_and_links: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DeviceProfileConfig:
    profile_id: str
    source_device_types: tuple[str, ...]
    manufacturer: str
    modality: str = "eeg"
    data_format: str = "numpy"
    header_source: str = "config"
    sampling_frequency_source: str = "metadata"
    sampling_frequency_hz: float | None = None
    unit: str = "uV"
    reference: str = "n/a"
    channel_names: tuple[str, ...] = ()
    channel_types: tuple[str, ...] = ()
    sample_counter_row: int | None = None
    counter_threshold: float = 0.95
    power_line_frequency: float | None = None
    software_filters: str | dict[str, Any] | None = None


@dataclass(slots=True)
class ConverterConfig:
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    timezone: str = "Asia/Shanghai"
    task_mappings: dict[str, str] = field(default_factory=lambda: {"image_b": "image"})
    task_descriptions: dict[str, str] = field(default_factory=dict)
    task_instructions: dict[str, str] = field(default_factory=dict)
    task_event_columns: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    task_stimulus_presentation: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_task: str | None = None
    subject_pattern: str = r"^[sS](?P<subject>\d+)$"
    excluded_device_types: tuple[str, ...] = ()
    device_profiles: dict[str, DeviceProfileConfig] = field(default_factory=dict)
    stimulus_libraries: tuple[str, ...] = (
        "pilot",
        "formal_500_v1",
        "formal_500_v2",
    )
    stimulus_aliases: tuple[str, ...] = ("formal_1",)
    power_line_frequency: float = 50.0
    strict: bool = True
    software_filters: str = "n/a"

    def device_profile_for(self, source_device_type: str) -> DeviceProfileConfig:
        normalized = source_device_type.strip().casefold()
        matches = [
            profile
            for profile in self.device_profiles.values()
            if normalized in {value.casefold() for value in profile.source_device_types}
        ]
        if not matches:
            raise ConverterError(
                "UNSUPPORTED_DEVICE_PROFILE",
                f"No configured device profile matches device_type={source_device_type!r}",
            )
        if len(matches) > 1:
            raise ConverterError(
                "DEVICE_PROFILE_COLLISION",
                f"Multiple profiles match device_type={source_device_type!r}: "
                f"{[profile.profile_id for profile in matches]}",
            )
        return matches[0]


def _ensure_label(value: str, field_name: str) -> str:
    sanitized = "".join(ch for ch in value if ch.isalnum() or ch == "+")
    if not sanitized:
        raise ConverterError("INVALID_BIDS_LABEL", f"{field_name} has no legal BIDS characters: {value!r}")
    return sanitized


def load_config(path: Path | None) -> ConverterConfig:
    cfg = ConverterConfig()
    if path is None:
        return cfg
    if not path.exists():
        raise ConverterError("CONFIG_NOT_FOUND", f"Config does not exist: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    dataset_raw = raw.get("dataset", {})
    cfg.dataset = DatasetConfig(
        name=str(dataset_raw.get("name", cfg.dataset.name)),
        description=str(dataset_raw.get("description", cfg.dataset.description)),
        bids_version=str(dataset_raw.get("bids_version", cfg.dataset.bids_version)),
        dataset_type=str(dataset_raw.get("dataset_type", cfg.dataset.dataset_type)),
        authors=[str(x) for x in dataset_raw.get("authors", cfg.dataset.authors)],
        license=str(dataset_raw["license"]) if dataset_raw.get("license") else None,
        acknowledgements=str(dataset_raw["acknowledgements"]) if dataset_raw.get("acknowledgements") else None,
        how_to_acknowledge=str(dataset_raw["how_to_acknowledge"]) if dataset_raw.get("how_to_acknowledge") else None,
        funding=[str(x) for x in dataset_raw.get("funding", [])],
        ethics_approvals=[str(x) for x in dataset_raw.get("ethics_approvals", [])],
        references_and_links=[str(x) for x in dataset_raw.get("references_and_links", [])],
    )
    cfg.timezone = str(raw.get("timezone", cfg.timezone))
    tasks = raw.get("tasks", {})
    cfg.default_task = tasks.get("default", cfg.default_task)
    mappings = tasks.get("mappings", cfg.task_mappings)
    normalized: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    instructions: dict[str, str] = {}
    event_columns: dict[str, dict[str, dict[str, Any]]] = {}
    stimulus_presentation: dict[str, dict[str, Any]] = {}
    for source_name, target in mappings.items():
        target_name = target.get("task") if isinstance(target, dict) else target
        task_label = _ensure_label(str(target_name), "task")
        normalized[str(source_name)] = task_label
        if isinstance(target, dict):
            if target.get("description"):
                descriptions[task_label] = str(target["description"])
            if target.get("instructions"):
                instructions[task_label] = str(target["instructions"])
            if isinstance(target.get("event_columns"), dict):
                event_columns[task_label] = {
                    str(column): dict(metadata)
                    for column, metadata in target["event_columns"].items()
                    if isinstance(metadata, dict)
                }
            if isinstance(target.get("stimulus_presentation"), dict):
                stimulus_presentation[task_label] = dict(target["stimulus_presentation"])
    cfg.task_mappings = normalized or cfg.task_mappings
    cfg.task_descriptions = descriptions
    cfg.task_instructions = instructions
    cfg.task_event_columns = event_columns
    cfg.task_stimulus_presentation = stimulus_presentation
    source = raw.get("source", {})
    cfg.subject_pattern = str(source.get("subject_pattern", cfg.subject_pattern))
    cfg.excluded_device_types = tuple(str(x).casefold() for x in source.get("excluded_device_types", []))
    stimuli = raw.get("stimuli", {})
    cfg.stimulus_libraries = tuple(str(x) for x in stimuli.get("libraries", cfg.stimulus_libraries))
    cfg.stimulus_aliases = tuple(str(x) for x in stimuli.get("aliases", cfg.stimulus_aliases))
    eeg = raw.get("eeg", {})
    cfg.power_line_frequency = float(eeg.get("power_line_frequency", cfg.power_line_frequency))
    cfg.software_filters = eeg.get("software_filters", cfg.software_filters)
    profiles_raw = raw.get("devices", {}).get("profiles", {})
    if not isinstance(profiles_raw, dict):
        raise ConverterError("INVALID_DEVICE_PROFILES", "devices.profiles must be a mapping")
    profiles: dict[str, DeviceProfileConfig] = {}
    for profile_id, profile_raw in profiles_raw.items():
        if not isinstance(profile_raw, dict):
            raise ConverterError("INVALID_DEVICE_PROFILE", f"Profile {profile_id!r} must be a mapping")
        names = tuple(str(x) for x in profile_raw.get("channel_names", []))
        types = tuple(str(x).lower() for x in profile_raw.get("channel_types", []))
        if names and not types:
            types = ("eeg",) * len(names)
        if types and len(types) != len(names):
            raise ConverterError(
                "CHANNEL_TYPE_COUNT_MISMATCH",
                f"Profile {profile_id!r} has {len(names)} names but {len(types)} channel types",
            )
        sample_counter_row = profile_raw.get("sample_counter_row")
        profiles[str(profile_id)] = DeviceProfileConfig(
            profile_id=str(profile_id),
            source_device_types=tuple(
                str(x) for x in profile_raw.get("source_device_types", [profile_id])
            ),
            manufacturer=str(profile_raw.get("manufacturer", "n/a")),
            modality=str(profile_raw.get("modality", "eeg")).lower(),
            data_format=str(profile_raw.get("data_format", "numpy")).lower(),
            header_source=str(profile_raw.get("header_source", "config")).lower(),
            sampling_frequency_source=str(
                profile_raw.get("sampling_frequency_source", "metadata")
            ).lower(),
            sampling_frequency_hz=(
                float(profile_raw["sampling_frequency_hz"])
                if profile_raw.get("sampling_frequency_hz") is not None
                else None
            ),
            unit=str(profile_raw.get("unit", "uV")),
            reference=str(profile_raw.get("reference", "n/a")),
            channel_names=names,
            channel_types=types,
            sample_counter_row=int(sample_counter_row) if sample_counter_row is not None else None,
            counter_threshold=float(profile_raw.get("counter_threshold", 0.95)),
            power_line_frequency=(
                float(profile_raw["power_line_frequency"])
                if profile_raw.get("power_line_frequency") is not None
                else None
            ),
            software_filters=profile_raw.get("software_filters"),
        )
    cfg.device_profiles = profiles
    cfg.strict = bool(raw.get("strict", cfg.strict))
    return cfg
