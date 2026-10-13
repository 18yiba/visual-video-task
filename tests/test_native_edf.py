"""New CH01..CH32 native recording and historical format coexistence."""
import json
from types import SimpleNamespace

import edfio
import numpy as np
import pytest

from video_eeg.storage.session_recorder import SessionRecorder
from video_eeg.storage.native_edf import CHANNEL_NAMES, read_edf
from video_eeg.utils import bids_export as b, eegqc_export as q


class Source:
    metadata = SimpleNamespace(name='brainco', n_channels=32, sfreq=1000)

    def __init__(self, data):
        self.data = data

    def get_new_samples(self):
        data, self.data = self.data, np.empty((32, 0), dtype=np.float32)
        return data, np.arange(data.shape[1])


def record(folder, data):
    recorder = SessionRecorder(Source(data), sfreq=1000, n_channels=32)
    recorder.start_spooling(folder)
    recorder.pull()
    recorder.add_event('video_on', video_name='original:vid_1', trial_idx=1)
    recorder.freeze()
    recorder.export(folder, metadata=dict(device_type='brainco', sfreq=1000,
        n_channels=32, subject_id='00000001', session_id=1, num_sessions=45,
        termination_reason='completed', timestamp_label='20261008_120000'), pull_final=False)
    return recorder


@pytest.mark.parametrize('count', [1, 3001, 4000])
def test_roundtrip_all_electrodes_in_hardware_order(tmp_path, count):
    # Each row has a distinct amplitude: an accidental reorder or dropped CH01 fails.
    data = np.tile(np.arange(1, 33, dtype=np.float32)[:, None]*100, (1, count))
    record(tmp_path, data)
    assert not list(tmp_path.glob('*.npy'))
    assert not list(tmp_path.glob('*.tmp'))
    m = json.loads((tmp_path/'metadata.json').read_text())
    actual = read_edf(tmp_path/'continuous_eeg.edf', m)
    np.testing.assert_allclose(actual, data, atol=750000/65535/2, rtol=0)
    edf = edfio.read_edf(tmp_path/'continuous_eeg.edf')
    assert [s.label for s in edf.signals] == list(CHANNEL_NAMES)
    assert edf.signals[28].label == 'IO'
    assert m['native_edf_profile']['reference'] == 'FCz'
    assert all(s.prefiltering.startswith('HP:0.16Hz') for s in edf.signals)


def test_empty_startup_keeps_events_without_fabricating_eeg(tmp_path):
    record(tmp_path, np.empty((32, 0), dtype=np.float32))
    assert not list(tmp_path.glob('*.edf')) and not list(tmp_path.glob('*.npy'))
    assert b.read_json(tmp_path/'metadata.json')['eeg_file'] is None
    assert b.read_json(tmp_path/'metadata.json')['sample_count'] == 0


@pytest.mark.parametrize('value', [375001, np.nan, np.inf])
def test_invalid_signal_retains_recovery_spool(tmp_path, value):
    data = np.zeros((32, 3), dtype=np.float32); data[0, 0] = value
    with pytest.raises(ValueError):
        record(tmp_path, data)
    assert (tmp_path/'.continuous_eeg.f32.tmp').exists()
    assert not (tmp_path/'continuous_eeg.edf').exists()


def test_resume_does_not_overwrite_old_npy_or_edf(tmp_path):
    old = tmp_path/'continuous_eeg.npy'; old.write_bytes(b'historical untouched')
    r = record(tmp_path, np.zeros((32, 3), dtype=np.float32))
    assert r.part_index == 2 and r.eeg_filename == 'continuous_eeg_part_002.edf'
    before = (tmp_path/r.eeg_filename).read_bytes()
    r2 = record(tmp_path, np.ones((32, 3), dtype=np.float32))
    assert r2.part_index == 3
    assert old.read_bytes() == b'historical untouched'
    assert (tmp_path/r.eeg_filename).read_bytes() == before


def test_both_exports_copy_native_edf_without_requantization(tmp_path):
    folder = tmp_path/'source/20261008_120000'
    record(folder, np.zeros((32, 3001), dtype=np.float32))
    native_hash = b.digest(folder/'continuous_eeg.edf')
    b.export_recording(folder, tmp_path/'bids', protocol='v2')
    assert b.digest(next((tmp_path/'bids').rglob('*.edf'))) == native_hash
    result = q.export_recording(folder, tmp_path/'qc', protocol='v2', settings={})
    assert result['recordings'][0]['status'] == 'EXPORTED'
    assert b.digest(next((tmp_path/'qc').rglob('*.edf'))) == native_hash
    assert q.export_recording(folder, tmp_path/'qc', protocol='v2', settings={})['recordings'][0]['status'] == 'EXISTS_VERIFIED'


def test_native_edf_official_offline_validation(tmp_path):
    folder = tmp_path/'source/20261008_120000'
    record(folder, np.zeros((32, 3001), dtype=np.float32))
    b.export_recording(folder, tmp_path/'bids', protocol='v2')
    assert b.validate_dataset(tmp_path/'bids')['errors'] == 0
    result = q.export_recording(folder, tmp_path/'qc', protocol='v2', settings={}, validate=True)
    assert result['recordings'][0]['official_validation']['errors'] == 0


def test_edf_header_mismatch_is_rejected(tmp_path):
    record(tmp_path, np.zeros((32, 3001), dtype=np.float32))
    m = b.read_json(tmp_path/'metadata.json'); m['sfreq'] = 500
    with pytest.raises(ValueError, match='header'):
        read_edf(tmp_path/'continuous_eeg.edf', m)


def test_extra_counter_row_is_not_silently_truncated(tmp_path):
    r = SessionRecorder(Source(np.zeros((33, 5), dtype=np.float32)), sfreq=1000, n_channels=32)
    r.start_spooling(tmp_path)
    with pytest.raises(RuntimeError, match='exactly 32'):
        r.pull()
    r.freeze(); r.export(tmp_path, metadata={}, pull_final=False)
    assert not list(tmp_path.glob('*.edf'))
