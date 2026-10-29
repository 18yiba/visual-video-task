"""EDF encoding for Neuracle's forwarded stream without guessing signal units."""
from datetime import datetime
import math

import numpy as np

REVISION = 'neuracle-forwarded-edf-v1'


def profile(forwarding):
    source_names = list(forwarding.get('channel_names') or [])
    source_types = list(forwarding.get('channel_types') or [])
    if not source_names or len(source_names) != len(source_types):
        raise ValueError('Neuracle EDF requires the complete forwarded channel names and types.')
    labels = []
    used = set()
    for index, name in enumerate(source_names, 1):
        label = str(name).strip()[:16] or f'CH{index:02d}'
        if label in used:
            label = f'CH{index:02d}'
        if label in used:
            raise ValueError('Neuracle EDF channel labels are not unique after EDF label encoding.')
        labels.append(label)
        used.add(label)
    trigger_index = forwarding.get('trigger_channel_index')
    if type(trigger_index) is not int or not 0 <= trigger_index < len(labels):
        raise ValueError('Neuracle EDF requires the verified TRG channel index.')
    if trigger_index != len(labels) - 1:
        raise ValueError('Neuracle EDF requires TRG as the final forwarded channel.')
    return dict(
        revision=REVISION,
        device_type='neuracle',
        manufacturer='Neuracle',
        model=str(forwarding.get('module_name') or 'unknown'),
        channel_names=labels,
        source_channel_names=[str(x) for x in source_names],
        channel_types=[str(x) for x in source_types],
        channel_units=['n/a'] * len(labels),
        units_verified=False,
        value_scaling='forwarded values without scaling',
        reference='n/a',
        power_line_frequency='n/a',
        confirmation='Forwarded channel metadata recorded; units, reference, filters and power-line frequency unverified.',
        trigger_channel_index=trigger_index,
        trigger_channel_name=labels[trigger_index],
        channel_sampling_rates_hz=list(forwarding.get('saved_channel_sampling_rates_hz') or []),
        software_filters='unknown',
    )


def write_edf(path, data, sfreq, started_at, channel_profile):
    import edfio

    values = np.asarray(data)
    names = channel_profile['channel_names']
    trigger_index = channel_profile['trigger_channel_index']
    if values.ndim != 2 or values.shape[0] != len(names) or values.shape[1] < 1:
        raise ValueError('Neuracle EDF signal shape does not match the verified channel profile.')
    if not float(sfreq).is_integer() or sfreq <= 0:
        raise ValueError('EDF requires a positive integer sampling frequency.')
    if not np.isfinite(values).all():
        raise ValueError('Neuracle EDF cannot encode nonfinite samples.')
    signals = []
    ranges = []
    quantization = []
    for index, name in enumerate(names):
        signal = np.asarray(values[index], dtype=np.float64)
        if index == trigger_index:
            if (np.any(signal != np.floor(signal)) or np.any(signal < 0) or np.any(signal > 255)):
                raise ValueError('Neuracle TRG values must be integer codes from 0 to 255.')
            physical_range = (0., 65535.)
        else:
            low = float(np.min(signal)); high = float(np.max(signal))
            if low == high:
                pad = max(abs(low) * 1e-6, 1.)
            else:
                pad = max((high - low) * 1e-6, np.finfo(np.float64).eps * max(abs(low), abs(high), 1.))
            physical_range = (low - pad, high + pad)
        step = (physical_range[1] - physical_range[0]) / 65535
        signals.append(edfio.EdfSignal(
            signal,
            sfreq,
            label=name,
            physical_dimension='n/a',
            physical_range=physical_range,
            prefiltering='unknown',
        ))
        ranges.append(list(physical_range))
        quantization.append(step)
    start = datetime.fromisoformat(started_at)
    duration = math.gcd(values.shape[1], int(sfreq)) / sfreq
    edf = edfio.Edf(
        signals,
        recording=edfio.Recording(startdate=start.date()),
        starttime=start.time().replace(tzinfo=None, microsecond=0),
        data_record_duration=duration,
    )
    with path.open('xb') as handle:
        edf.write(handle)
    return dict(physical_ranges= ranges, quantization_steps=quantization,
                units='n/a', units_verified=False)


def read_edf(path, metadata):
    import edfio

    contract = metadata.get('native_edf_profile') or {}
    if contract.get('revision') != REVISION or contract.get('device_type') != 'neuracle':
        raise ValueError('Unknown Neuracle EDF channel contract.')
    edf = edfio.read_edf(path)
    names = contract.get('channel_names') or []
    if len(edf.signals) != len(names):
        raise ValueError('Neuracle EDF channel count differs from metadata.')
    sfreq = float(metadata['sfreq'])
    rows = []
    for signal, name in zip(edf.signals, names):
        if signal.label != name or signal.physical_dimension != 'n/a' or signal.sampling_frequency != sfreq:
            raise ValueError('Neuracle EDF header disagrees with saved channel contract: ' + name)
        rows.append(signal.data)
    data = np.stack(rows)
    if data.shape[1] != metadata.get('sample_count'):
        raise ValueError('Neuracle EDF sample count differs from metadata.')
    return data
