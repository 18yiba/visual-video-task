"""Standard-library checks for source deployment, without device or GUI imports."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from video_eeg import cli
from video_eeg.paths import PROJECT_ROOT


class TemplateLayoutTests(unittest.TestCase):
    def test_validate_does_not_import_runtime_or_write_records(self):
        result = subprocess.run([sys.executable, '-I', str(PROJECT_ROOT/'main.py'), '--validate'],
                                cwd=PROJECT_ROOT.parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['public_versions'], ['v1', 'v2'])

    def test_config_rejects_unknown_keys_and_unsupported_values(self):
        cases = [
            'schema_version=1\n[launcher]\nprotocol="v2"\nmode="demo"\ntypo=true',
            'schema_version=1\n[launcher]\nprotocol="v3"\nmode="demo"',
            'schema_version=1\n[launcher]\nprotocol="v2"\nmode="dummy"',
            'schema_version=true\n[launcher]\nprotocol="v2"\nmode="demo"',
            'schema_version=1\n[launchre]\nprotocol="v2"\nmode="demo"',
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'test.toml'
            for content in cases:
                with self.subTest(content=content):
                    path.write_text(content, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        cli.load_settings(path)

    def test_default_launch_is_demo_and_preserves_runner_arguments(self):
        calls = []
        module = types.ModuleType('launch_experiment')
        module.choose = lambda **kwargs: calls.append(kwargs) or ('v1', 'demo')
        module.launch = lambda *args: calls.append(args) or 0
        with patch.dict(sys.modules, {'launch_experiment': module}):
            self.assertEqual(cli.main([]), 0)
            self.assertEqual(calls[0], {'default_protocol': 'v2', 'default_mode': 'demo'})
            self.assertEqual(cli.main(['--protocol', 'v2', '--mode', 'demo', '--no-dialog']), 0)
            self.assertEqual(calls[-1], ('v2', 'demo', ['--no-dialog']))
            self.assertEqual(cli.main(['--run']), 0)
            self.assertEqual(calls[-1], ('v2', 'demo', []))

    def test_local_toml_is_used_without_rewriting_it(self):
        module = types.ModuleType('launch_experiment')
        module.choose = lambda **kwargs: None
        calls = []
        module.launch = lambda *args: calls.append(args) or 0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'experiment.local.toml'
            path.write_text('schema_version=1\n[launcher]\nprotocol="v1"\nmode="formal"', encoding='utf-8')
            before = path.read_bytes()
            with patch.dict(sys.modules, {'launch_experiment': module}):
                self.assertEqual(cli.main(['--config', str(path), '--run']), 0)
            self.assertEqual(calls, [('v1', 'formal', [])])
            self.assertEqual(path.read_bytes(), before)

    def test_source_release_is_relocatable_and_preserves_protocol_bytes(self):
        spec = importlib.util.spec_from_file_location('template_release', PROJECT_ROOT/'scripts/maintenance/build_release.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'source'
            manifest = builder.build(target)
            names = {row['path'] for row in manifest}
            self.assertIn('src/video_eeg/experiment/video_runner.py', names)
            for entry in ('run_emotion_v3.bat', 'run_neuracle_v3.bat'):
                self.assertIn(entry, names)
                self.assertEqual((target/entry).read_bytes(), (PROJECT_ROOT/entry).read_bytes())
            self.assertNotIn('video_eeg/experiment/video_runner.py', names)
            self.assertNotIn('src/video_eeg/utils/preprocessing.py', names)
            for row in manifest:
                self.assertFalse(row['path'].endswith(('.local.toml', '.local.json', '.local.yaml', '.local.yml')))
                if row['path'].startswith('video_eeg/config/'):
                    self.assertEqual(hashlib.sha256((target/row['path']).read_bytes()).hexdigest(), row['sha256'])
            result = subprocess.run([sys.executable, '-I', str(target/'main.py'), '--validate'],
                                    cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([sys.executable, '-I', '-c',
                                     'import sys;sys.path.insert(0,sys.argv[1]);from video_eeg.paths import PROJECT_ROOT;print(PROJECT_ROOT)', str(target)],
                                    cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()), target.resolve())

    def test_release_excludes_private_launcher_overrides(self):
        spec = importlib.util.spec_from_file_location('template_private_release', PROJECT_ROOT/'scripts/maintenance/build_release.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'scripts').mkdir()
            (root/'scripts/repository_layout.json').write_text('{"retired":[]}', encoding='utf-8')
            (root/'config').mkdir()
            for name in ('config.toml', 'experiment.local.toml', 'device.local.yaml', 'mapping.local.json'):
                (root/'config'/name).write_text('', encoding='utf-8')
            with patch.object(builder, 'ROOT', root):
                names = {p.name for p in builder.source_files()}
            self.assertIn('config.toml', names)
            self.assertFalse(any('.local.' in name for name in names))


if __name__ == '__main__':
    unittest.main()
