import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location('convert_neuracle', Path(__file__).resolve().parents[1] / 'scripts/convert_neuracle_npy.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    names = [f'EEG{i:02}' for i in range(59)] + ['ECG', 'HEOR', 'HEOL', 'VEOU', 'VEOL', 'Trigger']
    data = np.random.default_rng(1).normal(size=(65, 4000)).astype('float32')
    data[-1] = 0
    data[-1, 100:110] = 150
    data[-1, 3000:3010] = 151
    np.save(root / 'continuous_eeg.npy', data)
    m = dict(device_type='neuracle', local_eeg_recorded=True, sfreq=1000., n_channels=65,
             sample_count=4000, eeg_part=1, eeg_file='continuous_eeg.npy', trigger_channel_index=64,
             recording_started_at='2026-10-22T16:05:10.469299+08:00',
             neuracle_forwarding=dict(channel_names=names,
                 channel_types=['EEG'] * 59 + ['HECG'] + ['EOG'] * 4 + ['Trigger'],
                 channel_sampling_rates_hz=[1000.] * 65, trigger_channel_index=64))
    (root / 'metadata.json').write_text(json.dumps(m))
    (root / 'events.json').write_text('[]')
    segment = {k: m[k] for k in ('eeg_file', 'sample_count', 'n_channels', 'sfreq')}
    segment.update(part=1, status='finalized', termination_reason='esc_emergency')
    (root / 'eeg_segments.json').write_text(json.dumps(dict(completed=False, segments=[segment])))
    return root


def test_preview_and_verified_copy(source, tmp_path):
    output = tmp_path / 'converted'
    before = {p.name: tool.sha256(p) for p in source.iterdir()}
    assert tool.convert(source, output)['duration_sec'] == 4
    assert not output.exists()
    result = tool.convert(source, output, True)
    assert result['trigger_exact'] and result['termination_reason'] == 'esc_emergency'
    assert result['bids_validation'] == 'NOT_RUN'
    assert before == {p.name: tool.sha256(p) for p in source.iterdir()}
    assert not list(output.glob('*.npy'))
    m = json.loads((output / 'metadata.json').read_text())
    assert m['native_edf_profile']['channel_units'] == ['n/a'] * 65
    assert m['sample_count'] == 4000
    with pytest.raises(ValueError, match='already exists'):
        tool.convert(source, output, True)


@pytest.mark.parametrize('fault', ['shape', 'rates', 'segment', 'trigger'])
def test_invalid_contract_never_published(source, tmp_path, fault):
    path = source / 'metadata.json'
    m = json.loads(path.read_text())
    if fault == 'shape':
        m['sample_count'] = 8000
    elif fault == 'rates':
        m['neuracle_forwarding']['channel_sampling_rates_hz'][0] = 250
    elif fault == 'trigger':
        m['trigger_channel_index'] = 0
    else:
        segments = json.loads((source / 'eeg_segments.json').read_text())
        segments['segments'][0]['status'] = 'writing'
        (source / 'eeg_segments.json').write_text(json.dumps(segments))
    path.write_text(json.dumps(m))
    with pytest.raises(ValueError):
        tool.convert(source, tmp_path / 'bad', True)
    assert not (tmp_path / 'bad').exists()


def test_nested_output_refused(source):
    with pytest.raises(ValueError, match='separate'):
        tool.convert(source, source / 'edf', True)
