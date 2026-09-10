from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import ConverterError


@dataclass(frozen=True, slots=True)
class NeuracleHeader:
    channel_names: tuple[str, ...]
    channel_types: tuple[str, ...]
    sampling_frequency: float
    unit: str
    hardware_filters: str


def _cstring(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("ascii", errors="replace").strip()


def parse_neuracle_nsf(path: Path) -> NeuracleHeader:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ConverterError("INVALID_NEURACLE_HEADER", f"Cannot read {path}: {exc}") from exc
    if len(content) < 128 or content[2:5] != b"NSF":
        raise ConverterError("INVALID_NEURACLE_HEADER", f"Not a supported Neuracle NSF header: {path}")
    count = int.from_bytes(content[0x40:0x42], "big")
    if count <= 0 or len(content) < 0x80 + count * 0x80:
        raise ConverterError("INVALID_NEURACLE_HEADER", f"Invalid channel count {count} in {path}")
    names: list[str] = []
    types: list[str] = []
    rates: set[int] = set()
    units: set[str] = set()
    filters: set[str] = set()
    for index in range(count):
        record = content[0x80 + index * 0x80 : 0x80 + (index + 1) * 0x80]
        name = _cstring(record[0:20])
        source_type = _cstring(record[20:40]).upper()
        names.append(name)
        if source_type == "EOG":
            types.append("eog")
        elif source_type in {"HECG", "ECG"}:
            types.append("ecg")
        elif source_type == "EMG":
            types.append("emg")
        else:
            types.append("eeg")
        filters.add(_cstring(record[48:68]))
        units.add(_cstring(record[68:76]))
        rates.add(int.from_bytes(record[76:78], "big"))
    if len(rates) != 1:
        raise ConverterError("INVALID_NEURACLE_HEADER", f"Inconsistent sample rates in {path}: {rates}")
    if len(units) != 1:
        raise ConverterError("INVALID_NEURACLE_HEADER", f"Inconsistent units in {path}: {units}")
    raw_unit = next(iter(units))
    unit = "uV" if raw_unit.lower().startswith("uv") else raw_unit
    return NeuracleHeader(
        channel_names=tuple(names),
        channel_types=tuple(types),
        sampling_frequency=float(next(iter(rates))),
        unit=unit,
        hardware_filters="; ".join(sorted(value for value in filters if value)) or "n/a",
    )
