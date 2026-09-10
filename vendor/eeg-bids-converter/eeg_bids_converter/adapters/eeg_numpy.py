from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..config import ConverterConfig, DeviceProfileConfig
from ..errors import ConverterError
from ..models import EEGProfile, RecordingRecord
from .eeg_base import EEGSourceAdapter
from .neuracle_header import NeuracleHeader, parse_neuracle_nsf


def _effective_event_frequency(event_files: tuple[Path, ...]) -> float | None:
    frequencies: list[float] = []
    for path in event_files:
        try:
            events = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(events, list) or len(events) < 2:
            continue
        valid = [
            event for event in events
            if isinstance(event, dict)
            and isinstance(event.get("sample_index"), (int, float))
            and isinstance(event.get("relative_time_sec"), (int, float))
        ]
        if len(valid) < 2:
            continue
        first, last = valid[0], valid[-1]
        elapsed = float(last["relative_time_sec"]) - float(first["relative_time_sec"])
        samples = float(last["sample_index"]) - float(first["sample_index"])
        if elapsed > 0 and samples > 0:
            frequencies.append(samples / elapsed)
    if not frequencies:
        return None
    return float(np.median(frequencies))


def _unit_multiplier(unit: str) -> float:
    normalized = unit.strip().lower().replace("µ", "u")
    values = {"v": 1.0, "mv": 1e-3, "uv": 1e-6, "nv": 1e-9}
    if normalized not in values:
        raise ConverterError("UNKNOWN_SIGNAL_UNIT", f"Unsupported electrophysiology unit: {unit!r}")
    return values[normalized]


class NumpyEEGAdapter(EEGSourceAdapter):
    """Load channel × sample NumPy recordings through configured device profiles."""

    def __init__(self, source_root: Path, cfg: ConverterConfig):
        self.source_root = source_root.resolve()
        self.cfg = cfg
        self._header_cache: dict[str, NeuracleHeader] = {}

    def _configured_profile(self, record: RecordingRecord) -> DeviceProfileConfig:
        profile = self.cfg.device_profile_for(record.device_type)
        if profile.modality != "eeg":
            raise ConverterError(
                "UNSUPPORTED_RECORDING_MODALITY",
                f"Profile {profile.profile_id!r} declares modality={profile.modality!r}; "
                "this adapter writes EEG recordings and synchronized auxiliary channels",
                record.source_record_id,
            )
        if profile.data_format != "numpy":
            raise ConverterError(
                "UNSUPPORTED_DEVICE_FORMAT",
                f"Profile {profile.profile_id!r} requires data_format={profile.data_format!r}",
                record.source_record_id,
            )
        return profile

    def _metadata_sampling_frequency(
        self,
        record: RecordingRecord,
        profile: DeviceProfileConfig,
    ) -> float:
        if profile.sampling_frequency_source == "config":
            value = profile.sampling_frequency_hz
        elif profile.sampling_frequency_source == "metadata":
            value = record.metadata.get("sfreq")
        else:
            raise ConverterError(
                "INVALID_SAMPLING_FREQUENCY_SOURCE",
                f"Profile {profile.profile_id!r} has unsupported sampling_frequency_source="
                f"{profile.sampling_frequency_source!r}",
                record.source_record_id,
            )
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ConverterError(
                "MISSING_SAMPLING_FREQUENCY",
                f"Profile {profile.profile_id!r} cannot resolve sampling frequency",
                record.source_record_id,
            ) from exc
        if result <= 0:
            raise ConverterError(
                "INVALID_SAMPLING_FREQUENCY",
                f"Sampling frequency must be positive, got {result}",
                record.source_record_id,
            )
        return result

    def _subject_root(self, record: RecordingRecord) -> Path:
        try:
            first = record.source_path.resolve().relative_to(self.source_root).parts[0]
        except (ValueError, IndexError) as exc:
            raise ConverterError(
                "INVALID_SOURCE_PATH",
                f"Recording is not beneath source root: {record.source_path}",
                record.source_record_id,
            ) from exc
        return self.source_root / first

    def _neuracle_header_for(self, record: RecordingRecord) -> NeuracleHeader:
        cache_key = record.source_subject.casefold()
        if cache_key in self._header_cache:
            return self._header_cache[cache_key]
        headers = [parse_neuracle_nsf(path) for path in self._subject_root(record).rglob("neuracle.nsf")]
        if not headers:
            raise ConverterError(
                "MISSING_DEVICE_HEADER",
                f"No neuracle.nsf found for {record.source_subject}",
                record.source_record_id,
            )
        first = headers[0]
        if any(header != first for header in headers[1:]):
            raise ConverterError(
                "DEVICE_HEADER_COLLISION",
                f"Multiple incompatible neuracle.nsf profiles found for {record.source_subject}",
                record.source_record_id,
            )
        self._header_cache[cache_key] = first
        return first

    def profile(self, record: RecordingRecord) -> EEGProfile:
        if not record.has_eeg:
            raise ConverterError("MISSING_EEG_FILE", "Recording has no EEG files", record.source_record_id)
        configured = self._configured_profile(record)
        if configured.header_source == "neuracle_nsf":
            return self._header_profile(record, configured)
        if configured.header_source == "config":
            return self._config_profile(record, configured)
        raise ConverterError(
            "UNSUPPORTED_HEADER_SOURCE",
            f"Profile {configured.profile_id!r} has header_source={configured.header_source!r}",
            record.source_record_id,
        )

    def _config_profile(
        self,
        record: RecordingRecord,
        configured: DeviceProfileConfig,
    ) -> EEGProfile:
        if not configured.channel_names:
            raise ConverterError(
                "MISSING_CHANNEL_PROFILE",
                f"Profile {configured.profile_id!r} must define channel_names",
                record.source_record_id,
            )
        sfreq = self._metadata_sampling_frequency(record, configured)
        effective = _effective_event_frequency(record.events_files)
        if effective is not None and abs(effective - sfreq) / sfreq > 0.05:
            raise ConverterError(
                "SAMPLING_FREQUENCY_CONFLICT",
                f"Configured/metadata frequency={sfreq:g} Hz but events imply {effective:.3f} Hz",
                record.source_record_id,
            )
        dropped = (
            (f"source_row_{configured.sample_counter_row}:sample_counter",)
            if configured.sample_counter_row is not None
            else ()
        )
        return EEGProfile(
            sampling_frequency=sfreq,
            channel_names=configured.channel_names,
            channel_types=configured.channel_types,
            unit=configured.unit,
            eeg_reference=configured.reference,
            power_line_frequency=(
                configured.power_line_frequency
                if configured.power_line_frequency is not None
                else self.cfg.power_line_frequency
            ),
            software_filters=(
                configured.software_filters
                if configured.software_filters is not None
                else self.cfg.software_filters
            ),
            manufacturer=configured.manufacturer,
            dropped_channels=dropped,
            provenance={
                "profile_id": configured.profile_id,
                "profile_source": "config",
                "event_effective_sfreq": effective,
            },
        )

    def _header_profile(
        self,
        record: RecordingRecord,
        configured: DeviceProfileConfig,
    ) -> EEGProfile:
        header = self._neuracle_header_for(record)
        metadata_sfreq = record.metadata.get("sfreq")
        effective = _effective_event_frequency(record.events_files)
        provenance: dict[str, object] = {
            "profile_id": configured.profile_id,
            "profile_source": "neuracle.nsf",
            "metadata_sfreq": metadata_sfreq,
            "event_effective_sfreq": effective,
        }
        if metadata_sfreq is not None:
            try:
                metadata_value = float(metadata_sfreq)
                if abs(metadata_value - header.sampling_frequency) / header.sampling_frequency > 0.05:
                    provenance["source_metadata_conflict"] = (
                        f"metadata={metadata_value:g}Hz; header={header.sampling_frequency:g}Hz"
                    )
            except (TypeError, ValueError):
                provenance["source_metadata_conflict"] = f"invalid metadata sfreq={metadata_sfreq!r}"
        if effective is not None and abs(effective - header.sampling_frequency) / header.sampling_frequency > 0.08:
            record.warnings.append(
                f"EVENT_FREQUENCY_DEVIATION:{effective:.3f}vs{header.sampling_frequency:g}"
            )
        return EEGProfile(
            sampling_frequency=header.sampling_frequency,
            channel_names=header.channel_names,
            channel_types=header.channel_types,
            unit=header.unit,
            eeg_reference=configured.reference,
            power_line_frequency=(
                configured.power_line_frequency
                if configured.power_line_frequency is not None
                else self.cfg.power_line_frequency
            ),
            software_filters=(
                configured.software_filters
                if configured.software_filters is not None
                else self.cfg.software_filters
            ),
            manufacturer=configured.manufacturer,
            hardware_filters=header.hardware_filters,
            provenance=provenance,
        )

    def load_part(self, record: RecordingRecord, index: int) -> np.ndarray:
        data = self._open_validated_part(record, index)
        profile = self.profile(record)
        return np.asarray(data, dtype=np.float64) * _unit_multiplier(profile.unit)

    def validate(self, record: RecordingRecord) -> EEGProfile | None:
        """Validate profiles, shapes and optional counters without loading full arrays."""
        if not record.has_eeg:
            return None
        profile = self.profile(record)
        for index in range(len(record.eeg_files)):
            data = self._open_validated_part(record, index)
            if data.shape[0] != len(profile.channel_names):
                raise ConverterError(
                    "CHANNEL_COUNT_MISMATCH",
                    f"Validated data has {data.shape[0]} channels but profile has "
                    f"{len(profile.channel_names)}",
                    record.source_record_id,
                )
        return profile

    def _open_validated_part(self, record: RecordingRecord, index: int) -> np.ndarray:
        try:
            path = record.eeg_files[index]
        except IndexError as exc:
            raise ConverterError("MISSING_EEG_PART", f"EEG part {index} does not exist", record.source_record_id) from exc
        try:
            data = np.load(path, mmap_mode="r")
        except Exception as exc:
            raise ConverterError("EEG_LOAD_FAILURE", f"Cannot load {path}: {exc}", record.source_record_id) from exc
        if data.ndim != 2:
            raise ConverterError("INVALID_EEG_SHAPE", f"Expected 2D NPY, got {data.shape}", record.source_record_id)
        configured = self._configured_profile(record)
        profile = self.profile(record)
        counter_row = configured.sample_counter_row
        expected_rows = len(profile.channel_names) + (1 if counter_row is not None else 0)
        if data.shape[0] != expected_rows:
            raise ConverterError(
                "CHANNEL_COUNT_MISMATCH",
                f"Profile {configured.profile_id!r} expects {expected_rows} source rows, got {data.shape}",
                record.source_record_id,
            )
        if counter_row is None:
            return data
        if counter_row < 0:
            counter_row += data.shape[0]
        if not 0 <= counter_row < data.shape[0]:
            raise ConverterError(
                "INVALID_COUNTER_ROW",
                f"sample_counter_row={configured.sample_counter_row} is outside {data.shape}",
                record.source_record_id,
            )
        probe = np.asarray(data[counter_row, : min(data.shape[1], 500_000)], dtype=np.float64)
        if probe.size < 2:
            raise ConverterError("INVALID_EEG_SHAPE", "Recording has fewer than 2 samples", record.source_record_id)
        counter_fraction = float(np.mean(np.diff(probe) == 1.0))
        if counter_fraction < configured.counter_threshold:
            raise ConverterError(
                "SAMPLE_COUNTER_VALIDATION_FAILED",
                f"Profile {configured.profile_id!r} row {counter_row} increment ratio="
                f"{counter_fraction:.6f}, threshold={configured.counter_threshold}",
                record.source_record_id,
            )
        if counter_row == 0:
            return data[1:, :]
        if counter_row == data.shape[0] - 1:
            return data[:-1, :]
        return np.concatenate((data[:counter_row, :], data[counter_row + 1 :, :]), axis=0)
