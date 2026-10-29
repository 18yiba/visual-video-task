"""Standard-library checks for source deployment, without device or GUI imports."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from video_eeg import cli
from video_eeg.paths import PROJECT_ROOT, resolve_project_path


class TemplateLayoutTests(unittest.TestCase):
    def test_protocol_resource_paths_migrate_without_a_root_package_directory(self):
        self.assertFalse((PROJECT_ROOT / 'video_eeg').exists())
        self.assertEqual(
            resolve_project_path('video_eeg/config/session_manifest.csv'),
            PROJECT_ROOT / 'src/video_eeg/config/session_manifest.csv',
        )

    def test_validate_does_not_import_runtime_or_write_records(self):
        result = subprocess.run([sys.executable, '-I', str(PROJECT_ROOT/'main.py'), '--validate'],
                                cwd=PROJECT_ROOT.parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['public_versions'], ['v1', 'v2'])
        module_result = subprocess.run([sys.executable, '-m', 'src', '--validate'],
                                       cwd=PROJECT_ROOT, capture_output=True, text=True)
        self.assertEqual(module_result.returncode, 0, module_result.stderr)
        self.assertEqual(json.loads(module_result.stdout)['public_versions'], ['v1', 'v2'])

    def test_config_rejects_unknown_keys_and_unsupported_values(self):
        valid_sections = '\n[experiment]\nproject="visual-video-task"\nidentity="EMOVID-20261008"\n[device]\nsupported=["emotivpro"]\n[storage]\nparticipant_data_root="data/sourcedata"\nmaterials="NAS"\n'
        cases = [
            'schema_version=1\n[launcher]\nprotocol="v2"\nmode="demo"\ntypo=true',
            'schema_version=1\n[launcher]\nprotocol="v3"\nmode="demo"',
            'schema_version=1\n[launcher]\nprotocol="v2"\nmode="dummy"',
            'schema_version=true\n[launcher]\nprotocol="v2"\nmode="demo"',
            'schema_version=1\n[launchre]\nprotocol="v2"\nmode="demo"',
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'test.toml'
            path.write_text('schema_version=1\n[launcher]\nprotocol="v2"\nmode="demo"' + valid_sections, encoding='utf-8')
            self.assertEqual(cli.load_settings(path)['experiment']['identity'], 'EMOVID-20261008')
            for content in cases:
                with self.subTest(content=content):
                    path.write_text(content + valid_sections, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        cli.load_settings(path)

    def test_config_requires_nonempty_template_sections_and_rejects_unknown_fields(self):
        content = ('schema_version=1\n[launcher]\nprotocol="v2"\nmode="demo"\n'
                   '[experiment]\nproject="visual-video-task"\nidentity="EMOVID-20261008"\n'
                   '[device]\nsupported=["neuracle"]\n'
                   '[storage]\nparticipant_data_root="data/sourcedata"\nmaterials="NAS"\n')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'test.toml'
            for malformed in (content.replace('[device]\nsupported=["neuracle"]', '[device]'),
                              content.replace('identity="EMOVID-20261008"', 'identity="AVEEG-20260923"'),
                              content + '\n[storage.extra]\nvalue="x"'):
                path.write_text(malformed, encoding='utf-8')
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
            self.assertEqual(cli.main(['--paradigm', 'v2', '--mode', 'demo', '--no-dialog']), 0)
            self.assertEqual(calls[-1], ('v2', 'demo', ['--no-dialog']))
            self.assertEqual(cli.main(['--protocol', 'v2', '--mode', 'demo', '--no-dialog']), 0)
            self.assertEqual(calls[-1], ('v2', 'demo', ['--no-dialog']))
            self.assertEqual(cli.main(['--protocol', 'v1', '--mode', 'formal', '--device', 'neuracle']), 0)
            self.assertEqual(calls[-1], ('v1', 'formal', ['--device-type', 'neuracle']))
            self.assertEqual(cli.main(['--run']), 0)
            self.assertEqual(calls[-1], ('v2', 'demo', []))

    def test_v3_routes_explicit_phase_and_device_without_hardware(self):
        calls = []
        launcher = types.ModuleType('launch_emotion_v3')
        launcher.launch_direct = lambda *args: calls.append(args) or 0
        with patch.dict(sys.modules, {'launch_emotion_v3': launcher}):
            self.assertEqual(cli.main(['--paradigm', 'v3', '--phase', 'acquisition',
                                       '--device', 'neuracle', '--subject-id', '12345678']), 0)
            self.assertEqual(calls[-1], ('acquisition', 'neuracle', ['--subject-id', '12345678']))
            self.assertEqual(cli.main(['--protocol', 'v3', '--phase', 'behavior-rating',
                                       '--device', 'emotivpro']), 0)
            self.assertEqual(calls[-1], ('behavior-rating', 'emotivpro', []))
            self.assertEqual(cli.main(['--protocol', 'v3', '--phase', 'acquisition',
                                       '--device', 'brainco', '--subject-id', '12345678']), 0)
            self.assertEqual(calls[-1], ('acquisition', 'brainco', ['--subject-id', '12345678']))

    def test_v3_compatibility_args_default_to_acquisition(self):
        calls = []
        launcher = types.ModuleType('launch_emotion_v3')
        launcher.launch_direct = lambda *args: calls.append(args) or 0
        with patch.dict(sys.modules, {'launch_emotion_v3': launcher}):
            self.assertEqual(cli.main(['--protocol', 'v3', '--device', 'emotivpro',
                                       '--subject-id', '12345678']), 0)
        self.assertEqual(calls[0], ('acquisition', 'emotivpro', ['--subject-id', '12345678']))

    def test_bat_device_route_without_phase_opens_v3_console(self):
        calls = []
        launcher = types.ModuleType('launch_emotion_v3')
        launcher.main = lambda argv=None: calls.append(os.environ.get('VIDEO_EEG_BACKEND')) or 0
        with patch.dict(sys.modules, {'launch_emotion_v3': launcher}):
            self.assertEqual(cli.main(['--protocol', 'v3', '--device', 'neuracle']), 0)
        self.assertEqual(calls, ['neuracle'])

    def test_brainco_bat_route_opens_v3_console(self):
        calls = []
        launcher = types.ModuleType('launch_emotion_v3')
        launcher.main = lambda argv=None: calls.append(os.environ.get('VIDEO_EEG_BACKEND')) or 0
        with patch.dict(sys.modules, {'launch_emotion_v3': launcher}):
            self.assertEqual(cli.main(['--protocol', 'v3', '--device', 'brainco']), 0)
        self.assertEqual(calls, ['brainco'])

    def test_local_toml_is_used_without_rewriting_it(self):
        module = types.ModuleType('launch_experiment')
        module.choose = lambda **kwargs: None
        calls = []
        module.launch = lambda *args: calls.append(args) or 0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'experiment.local.toml'
            path.write_text((PROJECT_ROOT/'config/config.toml').read_text(encoding='utf-8').replace('protocol = "v2"', 'protocol = "v1"').replace('mode = "demo"', 'mode = "formal"'), encoding='utf-8')
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
            layout = json.loads((PROJECT_ROOT/'scripts/repository_layout.json').read_text(encoding='utf-8'))
            self.assertTrue(set(layout['template_layout']['required_files']).issubset(names))
            self.assertNotIn('.dvc/config.local', names)
            self.assertFalse(any(path.startswith('assets/stimuli/') for path in names))
            self.assertIn('src/video_eeg/experiment/video_runner.py', names)
            for entry in ('run_emotion_v3.bat', 'run_neuracle_v3.bat', 'run_brainco_v3.bat', 'rating_emotion_v3.bat'):
                self.assertIn(entry, names)
                self.assertEqual((target/entry).read_bytes(), (PROJECT_ROOT/entry).read_bytes())
            self.assertNotIn('video_eeg/experiment/video_runner.py', names)
            self.assertNotIn('src/video_eeg/utils/preprocessing.py', names)
            for row in manifest:
                self.assertFalse(row['path'].endswith(('.local.toml', '.local.json', '.local.yaml', '.local.yml')))
                if row['path'].startswith('src/video_eeg/config/'):
                    self.assertEqual(hashlib.sha256((target/row['path']).read_bytes()).hexdigest(), row['sha256'])
            self.assertNotIn('video_eeg/__init__.py', names)
            self.assertFalse(any(path.startswith('video_eeg/') for path in names))
            self.assertIn('video_eeg.py', names)
            result = subprocess.run([sys.executable, '-I', str(target/'main.py'), '--validate'],
                                    cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            module_result = subprocess.run([sys.executable, '-m', 'src', '--validate'],
                                           cwd=target, capture_output=True, text=True)
            self.assertEqual(module_result.returncode, 0, module_result.stderr)
            self.assertEqual(json.loads(module_result.stdout)['public_versions'], ['v1', 'v2'])
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
