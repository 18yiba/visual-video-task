"""Project identity and obsolete-install checks without devices or NAS."""
import configparser
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.project_metadata import load_project_metadata


def load_script(name):
    path = ROOT / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProjectMetadataTests(unittest.TestCase):
    def test_project_id_matches_read_only_dvc_remote(self):
        metadata = load_project_metadata()
        self.assertEqual(metadata.unique_name, 'EMOVID-20261008')
        config = configparser.ConfigParser()
        config.read(ROOT / '.dvc/config', encoding='utf-8')
        remote_section = next(section for section in config.sections()
                              if section.strip("'") == 'remote "nas"')
        remote = config[remote_section]
        self.assertEqual(remote['url'], f's3://oi-task-assets/{metadata.unique_name}/dvc')
        self.assertEqual(remote['allow_anonymous_login'], 'true')
        self.assertEqual(remote['ssl_verify'], 'true')

    def test_metadata_rejects_bad_shape_date_and_template_identity(self):
        cases = (
            'full_name="Video"',
            'full_name="Video"\nunique_name="emovid-20261008"\ndescription="Capture"',
            'full_name="Video"\nunique_name="TOOLONG-20261008"\ndescription="Capture"',
            'full_name="Video"\nunique_name="EMO-20260230"\ndescription="Capture"',
            'full_name="Video"\nunique_name="ACQTPL-20261022"\ndescription="Capture"',
            'full_name="Video"\nunique_name="EMO-20261008"\ndescription=""',
            'full_name="Video"\nunique_name="EMO-20261008"\ndescription="Capture"\nextra=1',
        )
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            path = Path(directory) / 'metadata.toml'
            for text in cases:
                path.write_text(text, encoding='utf-8')
                with self.subTest(text=text), self.assertRaises(ValueError):
                    load_project_metadata(path)

    def test_invalid_metadata_stops_before_dvc_mutation(self):
        tool = load_script('configure_assets')
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            root = Path(directory)
            (root / '.dvc').mkdir()
            (root / '.dvc/config').write_text('original', encoding='utf-8')
            (root / 'metadata.toml').write_text('bad = true', encoding='utf-8')
            with patch.object(tool, 'ROOT', root), patch.object(tool.subprocess, 'run') as run:
                with self.assertRaises(SystemExit):
                    tool.main([])
            run.assert_not_called()
            self.assertEqual((root / '.dvc/config').read_text(), 'original')

    def test_dvc_configure_sets_validated_prefix_without_push_or_gc(self):
        tool = load_script('configure_assets')
        with patch.object(tool.subprocess, 'run') as run:
            self.assertEqual(tool.main(['--profile', 'lab-assets']), 0)
        calls = [call.args[0][3:] for call in run.call_args_list]
        self.assertIn(['remote', 'add', '--force', '--default', 'nas',
                       's3://oi-task-assets/EMOVID-20261008/dvc'], calls)
        self.assertIn(['remote', 'modify', 'nas', 'allow_anonymous_login', 'true'], calls)
        self.assertIn(['remote', 'modify', '--local', 'nas', 'allow_anonymous_login', 'false'], calls)
        self.assertFalse(any('push' in args or 'gc' in args for args in calls))

    def test_source_check_allows_dependency_pth_but_detects_project_alias(self):
        check = load_script('check_source_environment')
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            site = Path(directory)
            harmless = site / 'vendor-runtime.pth'
            harmless.write_text('vendor', encoding='utf-8')
            self.assertEqual(check.project_installations(site), [])
            legacy = site / '__editable__.video_eeg.pth'
            legacy.write_text('old', encoding='utf-8')
            self.assertIn(legacy.name, check.project_installations(site))
            self.assertEqual(legacy.read_text(), 'old')
            legacy.unlink()
            egg_link = site / 'acq_task.egg-link'
            egg_link.write_text('old', encoding='utf-8')
            self.assertIn(egg_link.name, check.project_installations(site))

    def test_source_check_detects_only_project_distributions_and_entrypoints(self):
        check = load_script('check_source_environment')

        class Dist:
            def __init__(self, name, entries=()):
                self.metadata = {'Name': name}
                self.version = '1.0'
                self.entry_points = [type('Entry', (), {'name': item}) for item in entries]

        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            site = Path(directory)
            with patch.object(check.importlib.metadata, 'distributions', return_value=[
                    Dist('video_eeg'), Dist('acq_task_template'),
                    Dist('third-party', ['acq-task']),
                    Dist('unrelated', ['unrelated-cli'])]):
                found = check.project_installations(site)
            self.assertIn('video-eeg 1.0', found)
            self.assertIn('acq-task-template 1.0', found)
            self.assertIn('third-party console entry', found)
            self.assertNotIn('unrelated 1.0', found)

    def test_windows_bundle_rejects_project_editable_alias(self):
        builder = load_script('build_windows_release')
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            site = Path(directory)
            (site / '__editable__.acq_task.pth').write_text('old', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'Do not bundle project aliases'):
                builder.assert_no_project_installations(site)


if __name__ == '__main__':
    unittest.main()
