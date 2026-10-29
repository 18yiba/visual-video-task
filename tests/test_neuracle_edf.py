import json
from types import SimpleNamespace

import edfio
import numpy as np

from video_eeg.storage.neuracle_edf import read_edf
from video_eeg.storage.neuracle_recorder import NeuracleSessionRecorder
from video_eeg.storage.neuracle_saved_trigger import verify_saved_triggers
from video_eeg.utils import bids_export


class Source:
    metadata = SimpleNamespace(name='neuracle', n_channels=3, sfreq=250)

    def __init__(self):
        self.data = np.array([[1., 2., 3., 4.], [4., 3., 2., 1.], [0., 0., 132., 0.]], dtype=np.float32)

    def get_new_samples(self):
        data, self.data = self.data, np.empty((3, 0), dtype=np.float32)
        return data, np.arange(data.shape[1]) / 250

    def recording_metadata(self):
        return {'neuracle_forwarding': {
            'channel_names': ['C3', 'C4', 'TRG'],
            'channel_types': ['EEG', 'EEG', 'TRG'],
            'channel_sampling_rates_hz': [250., 250., 250.],
            'saved_channel_sampling_rates_hz': [250., 250., 250.],
            'trigger_channel_index': 2,
            'trigger_channel_name': 'TRG',
            'module_name': 'Test Module',
            'trigger_mapping': {'ratio': 1, 'raw_sampling_rate_hz': 250., 'eeg_sampling_rate_hz': 250.},
        }, 'eeg_recording_mode': 'neuracle_tcp_local'}


def record(folder):
    source = Source()
    recorder = NeuracleSessionRecorder(source, sfreq=250, n_channels=3)
    recorder.start_spooling(folder)
    recorder.pull()
    receipt_path = folder / 'trg_receipts_part_001.jsonl'
    receipt_path.write_text(json.dumps(dict(sequence=1, received_sample_index=2, code=132,
        minimum_sample_index=1, hardware_ack=True)) + '\n', encoding='utf-8')
    recorder.freeze()
    recorder.export(folder, metadata=dict(device_type='neuracle', sfreq=250, n_channels=3,
        subject_id='S1', session_id=1, num_sessions=45, protocol_version='emotion-v2',
        session_stamp='20261028_120000', neuracle_trigger=dict(sent_count=1, confirmed_count=1,
        pending_codes=[], error=None)), pull_final=False)
    return recorder


def test_neuracle_final_recording_is_edf_and_trigger_roundtrips_exactly(tmp_path):
    recorder = record(tmp_path)
    assert recorder.eeg_filename == 'continuous_eeg.edf'
    assert (tmp_path / 'continuous_eeg.edf').is_file()
    assert not (tmp_path / 'continuous_eeg.npy').exists()
    assert not (tmp_path / '.continuous_eeg.f32.tmp').exists()
    metadata = json.loads((tmp_path / 'metadata.json').read_text(encoding='utf-8'))
    assert metadata['eeg_format'] == 'EDF'
    assert metadata['units_verified'] is False
    assert metadata['native_edf_profile']['channel_units'] == ['n/a'] * 3
    signals = edfio.read_edf(tmp_path / 'continuous_eeg.edf').signals
    assert [signal.label for signal in signals] == ['C3', 'C4', 'TRG']
    assert signals[-1].data.tolist() == [0., 0., 132., 0.]
    saved = read_edf(tmp_path / 'continuous_eeg.edf', metadata)
    assert saved.shape == (3, 4)
    result = json.loads((tmp_path / 'trg_saved_check_part_001.json').read_text(encoding='utf-8'))
    assert result['status'] == 'passed' and result['eeg_file'] == 'continuous_eeg.edf'


def test_neuracle_edf_can_be_read_by_export_profiles(tmp_path):
    record(tmp_path)
    metadata = json.loads((tmp_path / 'metadata.json').read_text(encoding='utf-8'))
    profile = bids_export.profile_for(metadata, 3)
    assert profile['channel_names'] == ['C3', 'C4', 'TRG']
    assert profile['channel_units'] == ['n/a'] * 3
    assert bids_export.load_signal(tmp_path / 'continuous_eeg.edf', metadata).shape == (3, 4)
    rows = bids_export.channel_rows(profile, 250)
    assert [row['type'] for row in rows] == ['EEG', 'EEG', 'TRIG']
    assert [row['units'] for row in rows] == ['n/a', 'n/a', 'n/a']


def test_neuracle_edf_exports_as_bids_without_claiming_unknown_units(tmp_path):
    source = tmp_path / '20261028_120000'
    output = tmp_path / 'bids'
    record(source)
    result = bids_export.export_recording(source, output, protocol='v2')
    channels = next(output.rglob('*_channels.tsv'))
    eeg_json = next(output.rglob('*_eeg.json'))
    assert result['recordings'][0]['status'] == 'EXPORTED'
    assert 'C3\tEEG\tn/a\t250' in channels.read_text(encoding='utf-8')
    sidecar = json.loads(eeg_json.read_text(encoding='utf-8'))
    assert sidecar['EEGChannelCount'] == 2 and sidecar['TriggerChannelCount'] == 1
    assert sidecar['EEGReference'] == 'n/a'


def test_neuracle_resume_appends_edf_without_overwriting_historical_npy(tmp_path):
    old = tmp_path / 'continuous_eeg.npy'
    old.write_bytes(b'legacy-npy-record')
    recorder = record(tmp_path)
    assert recorder.part_index == 2
    assert recorder.eeg_filename == 'continuous_eeg_part_002.edf'
    assert old.read_bytes() == b'legacy-npy-record'
