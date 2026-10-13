"""Synthetic native EDF fixtures; never claim hardware or signal quality."""
import csv
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from video_eeg.storage.session_recorder import SessionRecorder
from video_eeg.utils import bids_export as b, eegqc_export as q


def fixture(tmp_path, scope='all', reason='completed', n=4001):
    folder = tmp_path/'source/session_01/20261011_120000'
    class Source:
        metadata = SimpleNamespace(name='brainco', n_channels=32, sfreq=1000)
        data = np.zeros((32, n), dtype=np.float32)
        def get_new_samples(self):
            data = self.data
            self.data = np.empty((32, 0), dtype=np.float32)
            return data, np.arange(data.shape[1])
    recorder = SessionRecorder(Source(), sfreq=1000, n_channels=32)
    recorder.start_spooling(folder)
    recorder.add_event('EMOTION_VIDEO_ONSET', video_id='emotion:clip1', trial_id=1, attempt_id=1)
    recorder.pull()
    recorder.add_event('EMOTION_VIDEO_OFFSET', video_id='emotion:clip1', trial_id=1, attempt_id=1, completed_naturally=True)
    recorder.freeze()
    recorder.export(folder, metadata=dict(device_type='brainco', sfreq=1000, n_channels=32,
        subject_id='00000001', platform_participant_id='00000001', paradigm_code='EMOVID-20261008',
        session_id=1, num_sessions=45, protocol_version='emotion-v3', emotion_video_scope=scope,
        termination_reason=reason), pull_final=False)
    return folder


@pytest.mark.parametrize('scope', ['all', 'emotion_only'])
def test_v3_native_edf_single_package_preserves_uuid_and_sample_count(tmp_path, scope):
    folder = fixture(tmp_path, scope)
    original = {p.name: b.digest(p) for p in folder.iterdir() if p.is_file()}
    result = q.export_recording(folder, tmp_path/'eegqc', protocol='v3', settings={})
    package = tmp_path/'eegqc'/('recording-'+result['recordings'][0]['recording_uuid'])
    session = b.read_json(next(package.rglob('session.json')))
    assert session['participant_id'] == '00000001' and session['paradigm_code'] == 'EMOVID-20261008'
    assert session['source_video_scope'] == scope
    assert session['session_id'] == b.read_json(folder/'metadata.json')['recording_uuid']
    assert session['source_session_number'] == 1
    edfs = list(package.rglob('*.edf'))
    assert len(edfs) == 1 and b.digest(edfs[0]) == b.digest(folder/'continuous_eeg.edf')
    assert b.read_json(next(package.rglob('*_eeg.json')))['RecordingDuration'] == 4.001
    with next(package.rglob('*_channels.tsv')).open() as handle:
        assert len(list(csv.DictReader(handle, delimiter='\t'))) == 32
    with next(package.rglob('*_events.tsv')).open() as handle:
        reader = csv.DictReader(handle, delimiter='\t')
        assert reader.fieldnames[:2] == ['onset', 'duration']
        assert sum(r['trial_type'] == 'video' for r in reader) == 1
    assert (package/'.bidsignore').read_text() == '**/session.json\n'
    retry = q.export_recording(folder, tmp_path/'eegqc', protocol='v3', settings={})
    assert retry['recordings'][0]['recording_uuid'] == session['session_id']
    assert len(list((tmp_path/'eegqc').glob('recording-*'))) == 1
    assert original == {p.name: b.digest(p) for p in folder.iterdir() if p.is_file()}


def test_later_eeg_free_ratings_never_change_sealed_package(tmp_path):
    folder = fixture(tmp_path)
    q.export_recording(folder, tmp_path/'eegqc', protocol='v3', settings={})
    # Deliberately lacks any EEG timing/identity; it must not even be read.
    (folder.parent/'emotion_rating_log.csv').write_text('valence_rating,arousal_rating\n7,4\n')
    result = q.export_recording(folder, tmp_path/'eegqc', protocol='v3', settings={})
    assert result['recordings'][0]['status'] == 'EXISTS_VERIFIED'


def test_v3_identity_preserves_strings_and_snapshot():
    m = dict(subject_id='00000001', num_sessions=45, protocol_version='emotion-v3',
        platform_participant_id='00000001', paradigm_code='EMOVID-20261008')
    assert q.identity_for(m, 'v3', {'paradigm_codes': {'v3': 'OTHER'}}) == ('00000001', 'EMOVID-20261008')
    m.update(subject_id=1, platform_participant_id=None)
    with pytest.raises(b.BidsExportError, match='8位'):
        q.identity_for(m, 'v3', {})
    m.update(subject_id='00000001', protocol_version='emotion-v2')
    with pytest.raises(b.BidsExportError, match='emotion-v3'):
        q.identity_for(m, 'v3', {})


def test_v3_official_offline_validation(tmp_path):
    folder = fixture(tmp_path)
    result = q.export_recording(folder, tmp_path/'eegqc', protocol='v3', settings={}, validate=True)
    assert result['recordings'][0]['official_validation']['official_validation'] == 'PASSED'


def test_readable_interrupted_one_sample_record_is_not_discarded(tmp_path):
    folder = fixture(tmp_path, reason='eeg_background_error', n=1)
    result = q.export_recording(folder, tmp_path/'eegqc', protocol='v3', settings={})
    package = Path(result['recordings'][0]['output'])
    session = b.read_json(next(package.rglob('session.json')))
    assert session['recording_status'] == 'interrupted'
    assert session['stop_reason'] == 'acquisition_error'
    assert b.read_json(next(package.rglob('*_eeg.json')))['RecordingDuration'] == .001
