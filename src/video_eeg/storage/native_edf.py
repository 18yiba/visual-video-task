"""Native BrainCo EDF contract confirmed by the lab on 2026-10-08.

Applies to new CH01..CH32 recordings only, never to historical counter+31 NPY.
"""
from datetime import datetime
import math

import numpy as np

CHANNEL_NAMES = (
    'P8', 'P7', 'T8', 'T7', 'F8', 'F7', 'O2', 'O1',
    'P4', 'P3', 'C4', 'C3', 'F4', 'F3', 'FP2', 'FP1',
    'TP10', 'TP9', 'FT10', 'FT9', 'CP6', 'CP5', 'FC6', 'FC5',
    'CP2', 'CP1', 'FC2', 'FC1', 'IO', 'Pz', 'Cz', 'Fz',
)
REVISION = 'brainco-ch01-ch32-edf-20261008'


def profile():
    return dict(revision=REVISION, device_type='brainco', manufacturer='BrainCo',
                model='n/a', unit='uV', reference='FCz', ground='AFz',
                channel_names=list(CHANNEL_NAMES), sample_counter_row=None,
                power_line_frequency=50,
                software_filters={'Highpass': {'CutoffFrequencyHz': 0.16},
                                  'Lowpass': {'Status': 'unknown'},
                                  'Notch': {'Status': 'unknown'}},
                physical_ranges_uv={name: [-375000, 375000] for name in CHANNEL_NAMES},
                confirmation='Lab user confirmed CH01..CH32 mapping, uV, +/-375 mV '
                             'and default highpass 0.16 Hz on 2026-10-08; '
                             'FCz REF and AFz BIAS per supplied wiring diagram. '
                             'Exact hardware model, lowpass and notch remain unknown.')


def write_edf(path, data, sfreq, started_at, *, simulated=False):
    import edfio
    if data.shape[0] != 32 or not float(sfreq).is_integer() or sfreq <= 0:
        raise ValueError('BrainCo EDF requires 32 CH01..CH32 rows and integer sampling rate.')
    signals = []
    for index, name in enumerate(CHANNEL_NAMES):
        values = np.asarray(data[index], dtype=np.float64)
        if not np.isfinite(values).all() or (values.size and (values.min() < -375000 or values.max() > 375000)):
            raise ValueError('EEG nonfinite or outside confirmed +/-375000 uV range: '+name)
        signals.append(edfio.EdfSignal(values, sfreq, label=name, physical_dimension='uV',
                       physical_range=(-375000, 375000),
                       prefiltering='SIMULATED' if simulated else 'HP:0.16Hz LP:unknown N:unknown'))
    start = datetime.fromisoformat(started_at)
    duration = math.gcd(data.shape[1], int(sfreq))/sfreq if data.shape[1] else 1
    edf = edfio.Edf(signals, recording=edfio.Recording(startdate=start.date()),
                    starttime=start.time().replace(tzinfo=None, microsecond=0),
                    data_record_duration=duration)
    with path.open('xb') as handle:
        edf.write(handle)
    return {name: 750000/65535 for name in CHANNEL_NAMES}


def read_edf(path, metadata):
    import edfio
    edf = edfio.read_edf(path)
    p = metadata.get('native_edf_profile', {})
    if p != profile():
        raise ValueError('Unknown native EDF channel contract.')
    if len(edf.signals) != 32:
        raise ValueError('Native EDF must contain all 32 electrode channels.')
    sfreq = float(metadata['sfreq'])
    for signal, name in zip(edf.signals, CHANNEL_NAMES):
        if (signal.label != name or signal.physical_dimension != 'uV' or
                signal.sampling_frequency != sfreq or
                (signal.physical_min, signal.physical_max) != (-375000, 375000)):
            raise ValueError('Native EDF header disagrees with saved contract: '+name)
    # Preserve decoded EDF precision; exporters copy EDF bytes without requantization.
    data = np.stack([signal.data for signal in edf.signals])
    if data.shape[1] != metadata.get('sample_count'):
        raise ValueError('Native EDF sample count differs from metadata.')
    return data
