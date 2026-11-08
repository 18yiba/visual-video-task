from datetime import datetime

import pytest

from video_eeg.storage.run_layout import file_prefix, reserve_run, resolve_run


def test_same_day_runs_are_reserved_without_overwriting(tmp_path):
    session = tmp_path / 'session_01'
    session.mkdir()
    now = datetime(2026, 11, 8)
    first = reserve_run(session, now=now)
    (first / 'session.json').write_text('original')
    second = reserve_run(session, now=now)
    assert first.name == 'run-26110801'
    assert second.name == 'run-26110802'
    assert (first / 'session.json').read_text() == 'original'


def test_names_preserve_subject_and_reject_unsafe_identifiers():
    assert file_prefix('00123456', 1, 'emotionv3', 2) == 'sub-00123456_ses-01_task-emotionv3_run-02'
    with pytest.raises(ValueError):
        file_prefix('../subject', 1, 'emotionv3', 1)


def test_resolution_stays_within_fixed_session(tmp_path):
    assert resolve_run(tmp_path, 'run-26110801') == tmp_path.resolve() / 'run-26110801'
    with pytest.raises(ValueError):
        resolve_run(tmp_path, '../run-26110801')
