from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import unittest

from video_eeg.experiment.ready_question_runner import load_questions
from video_eeg.utils.video_library import load_video_library
from video_eeg.utils.session_protocol import SessionManifest, build_video_question_schedule

ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_complete_snapshot_is_structurally_valid_and_covers_18_checks_per_session(self):
        bank = load_questions(ROOT / 'video_eeg/config/complete_questions_20260908/question_bank.json')
        self.assertEqual(len(bank), 7993)
        self.assertEqual(sum(q['status'] == 'generated_unreviewed' for q in bank.values()), 5214)
        manifest = SessionManifest.load(ROOT / 'video_eeg/config/session_manifest_34.csv', session_count=34)
        self.assertEqual({e.video_path for e in manifest.entries} - set(bank),
                         {'5728.mp4', '6722.mp4', '6883.mp4'})
        for session in range(1, 35):
            schedule = build_video_question_schedule(manifest.session_assets(session), bank, random_seed=session)
            self.assertEqual(len({q['video_id'] for q in schedule}), 18)

    def test_standalone_material_path_fallback_and_explicit_path_respected(self):
        with TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project'
            materials = project / 'stimuli/videos'
            materials.mkdir(parents=True)
            (materials / '0001.mp4').write_bytes(b'path-resolution-only')
            config = dict(_project_dir=str(project), protocol=dict(video_library_dir='../video_materials/formal_v1/videos'))
            self.assertEqual(load_video_library(config).root, materials.resolve())
            config['protocol']['video_library_dir'] = 'operator_custom_path'
            self.assertEqual(load_video_library(config).root, project / 'operator_custom_path')

    def test_release_allowlist_excludes_data_media_and_credentials(self):
        path = ROOT / 'scripts/build_release.py'
        spec = importlib.util.spec_from_file_location('release_builder', path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        files = [p.relative_to(ROOT) for p in builder.source_files()]
        self.assertIn(Path('scripts/install_lab_env_uv.ps1'), files)
        self.assertIn(Path('AGENTS.md'), files)
        self.assertIn(Path('vendor/eeg-bids-converter/LICENSE'), files)
        for p in files:
            if p.as_posix() in builder.PLACEHOLDERS:
                self.assertEqual((ROOT / p).read_bytes(), b'')
                continue
            self.assertNotIn(p.parts[0], {'data', 'stimuli', '.venv', '.runtime', 'logs'})
            self.assertNotIn(p.suffix, {'.npy', '.mp4', '.exe', '.log', '.env'})


if __name__ == '__main__':
    unittest.main()
