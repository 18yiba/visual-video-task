from collections import Counter
from pathlib import Path

from video_eeg.experiment.video_runner import load_config, VideoExperimentConfig, startup_dialog, parse_args
from video_eeg.experiment.ready_question_runner import load_questions
from video_eeg.utils.session_protocol import SessionManifest, SessionState, split_manifest_sessions, load_state, save_state_atomic

ROOT = Path(__file__).resolve().parents[1]


def test_halves_preserve_legacy_membership_duration_diversity_and_ninety_minute_target():
    legacy = SessionManifest.load(ROOT / 'video_eeg/config/session_manifest.csv', session_count=17)
    current = SessionManifest.load(ROOT / 'video_eeg/config/session_manifest_34.csv', session_count=34)
    assert split_manifest_sessions(legacy).content_hash == current.content_hash
    assert len(current.entries) == len(set(current.video_ids)) == 7949
    assert set(current.video_ids) == set(legacy.video_ids)
    for old_id in range(1, 18):
        halves = current.session_entries(old_id * 2 - 1) + current.session_entries(old_id * 2)
        assert {e.video_id for e in halves} == {e.video_id for e in legacy.session_entries(old_id)}
    for sid in range(1, 35):
        assert 88 <= current.session_duration_sec(sid) / 60 <= 90
        buckets = Counter(e.duration_bucket for e in current.session_entries(sid))
        assert set(buckets) == {'very_short', 'short', 'medium', 'long', 'very_long'}
        assert min(buckets.values()) >= 46


def test_new_sessions_have_18_bound_checks_random_order_and_stable_resume(tmp_path):
    manifest = SessionManifest.load(ROOT / 'video_eeg/config/session_manifest_34.csv', session_count=34)
    questions = load_questions(ROOT / 'video_eeg/config/complete_questions_20260908/question_bank.json')
    for sid in range(1, 35):
        def new(seed):
            return SessionState.new(subject_id='TEST', session_id=sid, manifest=manifest,
                assets=manifest.session_assets(sid), random_seed=seed, attention_task_count=18,
                rest_min_minutes=30, rest_max_minutes=45, questions=questions)
        a, b = new(123), new(456)
        assert a.queue_video_ids != b.queue_video_ids
        assert set(a.queue_video_ids) == set(b.queue_video_ids) == {e.video_id for e in manifest.session_entries(sid)}
        assert len({q['video_id'] for q in a.attention_schedule}) == 18
        for question in a.attention_schedule:
            assert a.queue_video_ids[question['after_video_number']-1] == question['video_id']
        path = tmp_path / f'{sid}.json'
        save_state_atomic(path, a)
        restored = load_state(path)
        assert restored.queue_video_ids == a.queue_video_ids
        assert restored.attention_schedule == a.attention_schedule


def test_legacy_17_entry_keeps_old_records_and_manifest():
    current = load_config(ROOT / 'video_eeg/config/video_config.yaml')
    legacy = load_config(ROOT / 'video_eeg/config/video_legacy_17_config.yaml')
    assert current['protocol']['num_sessions'] == 34
    assert legacy['protocol']['num_sessions'] == 17
    assert legacy['protocol']['session_manifest_path'].endswith('/session_manifest.csv')
    assert legacy['storage']['records_dir'] == 'data/video_question_complete_runs'
    assert current['storage']['records_dir'] == 'data/video_question_complete_runs/protocol_34sessions'
    assert current['protocol']['question_bank_path'] == legacy['protocol']['question_bank_path']
