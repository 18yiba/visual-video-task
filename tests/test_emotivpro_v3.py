import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import edfio
import numpy as np
import pytest

from video_eeg.experiment.emotion_v3_runner import EmotionV3Runner, eeg_saved, base


def test_external_video_finishes_without_fabricating_samples(monkeypatch):
    r = object.__new__(EmotionV3Runner)
    r.config = {'device_type': 'emotivpro'}
    r.library = SimpleNamespace(rows={'v': {'trial_type': 'emotion'}})
    row = dict(video_onset_sample_index=None, video_offset_sample_index=None,
               video_onset_unix_sec=10., video_offset_unix_sec=12.)
    attempt = dict(video_completed_naturally=True, completed=False, emotion_rating=row)
    r.state = SimpleNamespace(video_attempts=[attempt], commit_completed_video=Mock())
    r._require_manager = Mock(); r.manager = Mock(); r._checkpoint = Mock()
    monkeypatch.setattr(base.VideoRunner, '_run_post_video_rest', Mock())
    r._run_post_video_rest(trial_idx=1, asset=SimpleNamespace(asset_id='v'), record=Mock())
    assert attempt['completed']
    assert row['eeg_recording_mode'] == 'emotivpro_external'
    assert row['video_onset_sample_index'] is None
    assert not eeg_saved(attempt)  # Serial success is not proof of saved EEG.


def test_external_rating_gate_requires_explicit_saved_edf_and_matching_part(tmp_path):
    from video_eeg.utils.emotivpro_recording import confirm_recording
    run = tmp_path/'run'; run.mkdir()
    metadata = dict(eeg_recording_mode='emotivpro_external', eeg_part=1,
                    recording_uuid='record-1', local_eeg_recorded=False,
                    subject_id='00000001', session_id=1, serial_write_error=None)
    meta = run/'metadata.json'; meta.write_text(json.dumps(metadata))
    eeg = tmp_path/'export.edf'
    edfio.Edf([edfio.EdfSignal(np.zeros(128), 128, label='EEG F3', physical_range=(-100, 100))]).write(eeg)
    row = dict(eeg_recording_mode='emotivpro_external', eeg_part=1,
               eeg_recording_dir=str(run), video_onset_unix_sec=10., video_offset_unix_sec=12.,
               video_onset_sample_index=None, video_offset_sample_index=None)
    attempt = dict(video_completed_naturally=True, emotion_rating=row)
    assert not eeg_saved(attempt)
    with pytest.raises(ValueError, match='确认'):
        confirm_recording(meta, eeg, operator_confirmed=False)
    original = meta.read_bytes()
    confirm_recording(meta, eeg, operator_confirmed=True)
    assert meta.read_bytes() == original
    assert eeg_saved(attempt)
    row['eeg_part'] = 2
    assert not eeg_saved(attempt)
    row['eeg_part'] = 1
    attempt['video_completed_naturally'] = False
    assert not eeg_saved(attempt)
    attempt['video_completed_naturally'] = True
    eeg.unlink()
    assert not eeg_saved(attempt)


def test_emotiv_configuration_changes_only_device_settings():
    from video_eeg.utils.emotivpro_recording import configure
    cfg = dict(device_type='brainco', protocol={'seed': 99}, storage={'records_dir': 'original'},
               device={'trigger_serial_port': 'OLD'}, subject_id='001', sfreq=1000)
    before = copy.deepcopy(cfg)
    configure(cfg, 'COM42')
    assert cfg['device_type'] == 'emotivpro'
    assert cfg['device']['emotivpro_serial_port'] == 'COM42'
    assert all(cfg[k] == v for k, v in before.items() if k not in {'device', 'device_type'})


def test_external_mode_never_exports_using_brainco_profile(tmp_path):
    from video_eeg.utils.eegqc_export import after_recording
    assert 'EmotivPRO' in after_recording(tmp_path, {'device_type': 'emotivpro'})
