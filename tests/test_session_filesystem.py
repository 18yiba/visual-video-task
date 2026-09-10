import csv
from pathlib import Path
import pytest

from video_eeg.utils.session_protocol import SessionManifest
from video_eeg.utils.session_integrity import inspect_session_files
from video_eeg.experiment.video_runner import load_config
from video_eeg.utils.video_library import load_video_library


PROJECT = Path(__file__).resolve().parents[1]


def test_real_formal_manifest_files_and_eligible_pool():
    config = load_config(PROJECT / 'video_eeg/config/video_config.yaml')
    config['_project_dir'] = str(PROJECT)
    root = load_video_library(config).root
    if not root.exists():
        pytest.skip('Integration test requires the separately distributed formal video corpus')
    manifest = SessionManifest.load(PROJECT / 'video_eeg/config/session_manifest.csv')
    report = inspect_session_files(manifest, root)
    with (PROJECT / 'video_eeg/config/formal_excluded_over_60s.csv').open(encoding='utf-8-sig') as handle:
        exclusions = {row['filename'] for row in csv.DictReader(handle)}
    assert report['missing'] == []
    assert report['duplicate_assignments'] == []
    assert set(report['unassigned']) == exclusions
    assert len({e.session_id for e in manifest.entries}) == 17
    assert all(e.video_duration_sec <= 60.000001 for e in manifest.entries)


def test_demo_uses_full_pool_not_leftover_smoke_directory():
    config = load_config(PROJECT / 'video_eeg/config/video_demo_config.yaml')
    config['_project_dir'] = str(PROJECT)
    library = load_video_library(config)
    if not library.root.exists():
        pytest.skip('Integration test requires the separately distributed formal video corpus')
    assert len(library.list_candidate_assets()) > 10
    assert library.root.name == 'videos'
