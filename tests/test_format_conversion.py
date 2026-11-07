"""Synthetic conversion only: no participant records or hardware."""
import importlib.util
from pathlib import Path

import edfio
import numpy as np
import pytest

from test_eegqc_export import fixture
from test_convert_neuracle_npy import source
from video_eeg.utils import bids_export as b

if not (Path(__file__).resolve().parents[2]/'BIDS-convert/convert.py').is_file():
    pytest.skip('Independent sibling BIDS-convert is not attached', allow_module_level=True)

spec = importlib.util.spec_from_file_location('convert_npy_bids', Path(__file__).resolve().parents[1]/'scripts/convert_npy_bids.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def test_brainco_plus_official_and_source_unchanged(tmp_path):
    folder, data, settings = fixture(tmp_path)
    before = {p.name: b.digest(p) for p in folder.iterdir()}
    result = tool.convert(folder, tmp_path/'output', 'v2', settings)
    assert result['official_validation'] == 'PASSED'
    path = next((tmp_path/'output').rglob('*.edf'))
    assert path.read_bytes()[192:197] == b'EDF+C'
    edf = edfio.read_edf(path)
    assert len(edf.annotations) >= 3
    assert len(edf.signals) == 31
    np.testing.assert_allclose(edf.signals[0].data, data[1], atol=200/65535)
    assert {p.name: b.digest(p) for p in folder.iterdir()} == before
    with pytest.raises(ValueError, match='existing'):
        tool.convert(folder, tmp_path/'output', 'v2', settings)


def test_neuracle_plus_preserves_trigger_unknown_units_and_scope(source, tmp_path):
    m = b.read_json(source/'metadata.json')
    m.update(subject_id='00000002', session_id=1, num_sessions=45, protocol_version='emotion-v3',
             emotion_video_scope='emotion_only', session_stamp='20261022_160510',
             recording_ended_at='2026-10-22T16:05:15+08:00')
    b.write_json(source/'metadata.json', m)
    result = tool.convert(source, tmp_path/'output', 'v3', {})
    assert result['official_validation'] == 'PASSED'
    root = tmp_path/'output'
    edf = edfio.read_edf(next(root.rglob('*.edf')))
    original = np.load(source/'continuous_eeg.npy')
    np.testing.assert_array_equal(edf.signals[-1].data, original[-1])
    assert all(s.physical_dimension == 'n/a' for s in edf.signals)
    session = b.read_json(next(root.rglob('session.json')))
    assert session['source_video_scope'] == 'emotion_only'


def test_nested_output_and_missing_contract(tmp_path):
    folder, _, settings = fixture(tmp_path)
    with pytest.raises(ValueError, match='separate'):
        tool.convert(folder.parent, folder.parent/'out', 'v2', settings)
    with pytest.raises(ValueError, match='设备型号'):
        tool.convert(folder, tmp_path/'bad', 'v2', {}, validate=False)
    assert b.read_json(tmp_path/'bad/conversion_report.json')['status'] == 'FAILED'


def test_mixed_device_refused_before_output(tmp_path):
    folder, _, settings = fixture(tmp_path)
    sibling = folder.parent/'20261008_130000'
    sibling.mkdir()
    m = b.read_json(folder/'metadata.json')
    m['device_type'] = 'neuracle'
    b.write_json(sibling/'metadata.json', m)
    with pytest.raises(ValueError, match='Mixed device'):
        tool.convert(folder.parent, tmp_path/'out', 'v2', settings)
    assert not (tmp_path/'out').exists()


def test_interrupted_parts_are_separate_and_keep_behavior(tmp_path):
    folder, _, settings = fixture(tmp_path)
    m = b.read_json(folder/'metadata.json')
    m.update(eeg_part=2, eeg_file='continuous_eeg_part_002.npy', events_file='events_part_002.json',
             recording_uuid='223456781234423482341234567890ab', termination_reason='eeg_background_error')
    (folder/m['eeg_file']).write_bytes((folder/'continuous_eeg.npy').read_bytes())
    (folder/m['events_file']).write_bytes((folder/'events.json').read_bytes())
    b.write_json(folder/'metadata_part_002.json', m)
    tool.convert(folder, tmp_path/'out', 'v2', settings, validate=False)
    assert len(list((tmp_path/'out').rglob('*.edf'))) == 2
    sessions = [b.read_json(p) for p in (tmp_path/'out').rglob('session.json')]
    assert {(s['source_part'], s['recording_status']) for s in sessions} == {(1, 'complete'), (2, 'interrupted')}


def test_invalid_signal_keeps_failure_receipt(tmp_path):
    folder, data, settings = fixture(tmp_path)
    data[1, 10] = np.nan
    np.save(folder/'continuous_eeg.npy', data)
    with pytest.raises(ValueError):
        tool.convert(folder, tmp_path/'out', 'v2', settings, validate=False)
    assert b.read_json(tmp_path/'out/conversion_report.json')['status'] == 'FAILED'
    assert not list((tmp_path/'out').glob('recording-*'))


def test_standalone_directory_bat_conversion_without_project(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    if os.name != 'nt':
        pytest.skip('Windows BAT integration')
    original = Path(__file__).resolve().parents[2]/'BIDS-convert'
    standalone = tmp_path/'standalone tool'
    shutil.copytree(original, standalone, ignore=shutil.ignore_patterns('__pycache__', '.venv', '.build-env', 'releases', '*.exe'))
    folder, _, settings = fixture(tmp_path)
    config = tmp_path/'settings.json'
    b.write_json(config, settings)
    env = dict(os.environ, BIDS_CONVERT_PYTHON=sys.executable, PYTHONPATH='')
    result = subprocess.run([str(standalone/'RUNME.bat'), '--source', str(folder),
        '--output', str(tmp_path/'standalone output'), '--protocol', 'v2', '--config', str(config)],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout+result.stderr
    report = b.read_json(tmp_path/'standalone output/conversion_report.json')
    assert report['official_validation'] == 'PASSED'
    assert len(list((tmp_path/'standalone output').rglob('*.edf'))) == 1
    # The same isolated copy also supports Python isolated mode, with no project imports.
    result = subprocess.run([sys.executable, '-I', str(standalone/'convert.py'), '--help'],
        cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not any('video_eeg' in p.read_text(encoding='utf-8') for p in standalone.rglob('*.py'))


def test_interactive_cancel_without_writes(tmp_path):
    import subprocess
    import sys
    path = Path(__file__).resolve().parents[2]/'BIDS-convert/convert.py'
    result = subprocess.run([sys.executable, str(path)], input='\n\nv3\n\n',
        cwd=tmp_path, capture_output=True, text=True, encoding='utf-8',
        env=__import__('os').environ.copy() | {'PYTHONUTF8': '1'})
    assert result.returncode == 1
    assert not list(tmp_path.iterdir())
