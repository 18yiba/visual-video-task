import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from video_eeg.experiment.emotion_v3_runner import EmotionV3Runner, BehaviorEvents, eeg_saved, base
from video_eeg.experiment.emotion_v3_runner import configure_emotion_only


def test_emotion_only_uses_separate_root_without_double_suffix():
    cfg = dict(protocol=dict(separate_emotion_ratings=True), storage=dict(records_dir='data/sourcedata/v3'))
    configure_emotion_only(cfg); configure_emotion_only(cfg)
    assert cfg['storage']['records_dir'] == 'data/sourcedata/v3_emotion_only'
    assert cfg['protocol']['attention_enabled'] is False
    assert cfg['protocol']['attention_tasks_per_session'] == 0


@pytest.fixture
def recorded(tmp_path):
    (tmp_path / 'continuous_eeg.npy').write_bytes(b'EEG')
    (tmp_path / 'metadata.json').write_text(json.dumps(dict(eeg_part=1,
        local_eeg_recorded=True, sample_count=100, eeg_file='continuous_eeg.npy')))
    return dict(video_id='v', video_completed_naturally=True, emotion_rating=dict(
        video_onset_sample_index=10, video_offset_sample_index=90, eeg_part=1,
        eeg_recording_dir=str(tmp_path), completed=False))


def test_rating_gate_requires_complete_playback_samples_and_saved_part(recorded, tmp_path):
    assert eeg_saved(recorded)
    recorded['video_completed_naturally'] = False
    assert not eeg_saved(recorded)
    recorded['video_completed_naturally'] = True
    recorded['emotion_rating']['video_offset_sample_index'] = 10
    assert not eeg_saved(recorded)
    recorded['emotion_rating']['video_offset_sample_index'] = 90
    recorded['emotion_rating']['eeg_part'] = 2
    assert not eeg_saved(recorded)
    recorded['emotion_rating']['eeg_part'] = 1
    (tmp_path / 'continuous_eeg.npy').unlink()
    assert not eeg_saved(recorded)


def test_reject_uncollected_before_replay_or_questions(recorded):
    r = object.__new__(EmotionV3Runner)
    r._replay = Mock(); r._choice_page = Mock()
    recorded['video_completed_naturally'] = False
    with pytest.raises(RuntimeError):
        r._rate_attempt(recorded)
    r._replay.assert_not_called(); r._choice_page.assert_not_called()


@pytest.mark.parametrize('interrupt', [False, True])
def test_behavior_resubmits_both_original_ratings_without_sample_indices(recorded, interrupt):
    r = object.__new__(EmotionV3Runner)
    r._event_times = {}; r.manager = BehaviorEvents(r)
    r._asset_by_id = {'v': 'asset'}
    r._choice_page = Mock(return_value='3'); r._replay = Mock()
    r._checkpoint = Mock(); r._write_rating_log = Mock(); r._write_emotion_list = Mock()
    pages = []
    def page(row, name, wording, anchors):
        pages.append(name)
        r.manager.emit(name)
        assert r._event_times[name]['sample_index'] is None
        if interrupt and name == 'arousal':
            raise base.ExperimentAbort()
        row[name + '_rating'] = 7
    r._rating_page = page
    if interrupt:
        with pytest.raises(base.ExperimentAbort):
            r._rate_attempt(recorded)
        assert recorded['emotion_rating']['interrupted']
        assert not recorded['emotion_rating']['completed']
    else:
        r._rate_attempt(recorded)
        assert recorded['emotion_rating']['completed']
    assert pages == ['valence', 'arousal']
    assert r.rating_max == 7
    r._replay.assert_called_once_with('asset', 2.)


def test_emotion_collection_has_no_rating_and_preserves_rest(monkeypatch):
    r = object.__new__(EmotionV3Runner)
    r.library = SimpleNamespace(rows={'v': {'trial_type': 'emotion'}})
    attempt = {'completed': False, 'emotion_rating': dict(video_onset_sample_index=1, video_offset_sample_index=10)}
    r.state = SimpleNamespace(video_attempts=[attempt], commit_completed_video=Mock())
    r._require_manager = Mock(); r.manager = Mock(); r._checkpoint = Mock()
    r._rating_page = Mock()
    rest = Mock()
    monkeypatch.setattr(base.VideoRunner, '_run_post_video_rest', rest)
    r._run_post_video_rest(trial_idx=1, asset=SimpleNamespace(asset_id='v'), record=Mock())
    assert attempt['completed']
    r._rating_page.assert_not_called(); rest.assert_called_once()
    r.state.commit_completed_video.assert_called_once_with('v', 0.)


def test_empty_eeg_does_not_commit(monkeypatch):
    r = object.__new__(EmotionV3Runner)
    r.library = SimpleNamespace(rows={'v': {'trial_type': 'emotion'}})
    r.state = SimpleNamespace(video_attempts=[{'emotion_rating': dict(
        video_onset_sample_index=0, video_offset_sample_index=0)}], commit_completed_video=Mock())
    r._require_manager = Mock()
    with pytest.raises(RuntimeError):
        r._run_post_video_rest(trial_idx=1, asset=SimpleNamespace(asset_id='v'), record=Mock())
    r.state.commit_completed_video.assert_not_called()
