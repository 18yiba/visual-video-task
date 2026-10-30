"""Migration tests use synthetic records only."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('migrate_records', Path(__file__).resolve().parents[1] / 'scripts/maintenance/migrate_records.py')
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / '.tmp'
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='migration-test-', dir=temp_root)
        assert Path(self.temp.name).resolve().is_relative_to(temp_root.resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / 'old/data'
        self.new = self.root / 'new/data'
        self.subject = self.record(self.old)

    def record(self, data, root='sourcedata/v2'):
        subject = data / root / '00000001'
        session = subject / 'session_01'
        session.mkdir(parents=True)
        (session / 'session_state.json').write_text(json.dumps({'protocol_hash': 'unchanged', 'completed': ['vid1']}))
        (session / 'question_bank_snapshot.json').write_bytes(b'{"original": true}')
        (session / 'eeg.edf').write_bytes(b'example\x00\xff')
        (session / 'facial.mp4').write_bytes(b'synthetic video')
        return subject

    def test_preview_writes_nothing(self):
        migration.migrate(self.old, self.new)
        self.assertFalse(self.new.exists())

    def test_copy_verified_and_original_unchanged(self):
        before = migration.inventory(self.subject)
        migration.migrate(self.old, self.new, True)
        self.assertEqual(before, migration.inventory(self.subject))
        self.assertEqual(before, migration.inventory(self.new / 'sourcedata/v2/00000001'))
        receipts = list((self.new / '_record_migrations').glob('*/receipt.json'))
        self.assertEqual(json.loads(receipts[0].read_text(encoding='utf-8'))['status'], 'verified')
        with self.assertRaisesRegex(ValueError, '禁止覆盖'):
            migration.migrate(self.old, self.new, True)

    def test_alias_conflict(self):
        self.record(self.new, 'video_emotion_eeg_runs/protocol_emotion_v2')
        with self.assertRaisesRegex(ValueError, '禁止覆盖'):
            migration.plan(self.old, self.new)
        self.record(self.old, 'sourcedata/emotion-v2')
        with self.assertRaisesRegex(ValueError, '多个根目录'):
            migration.plan(self.old, self.root / 'another')

    def test_unknown_and_nested_roots_rejected(self):
        self.record(self.old, 'sourcedata/imported/root_01')
        with self.assertRaisesRegex(ValueError, '未支持'):
            migration.plan(self.old, self.new)
        with self.assertRaisesRegex(ValueError, '互相包含'):
            migration.plan(self.old, self.old / 'nested')

    def test_changes_during_copy_keep_staging_only(self):
        original = migration.shutil.copyfileobj
        def changing(inp, out, **kwargs):
            original(inp, out, **kwargs)
            (self.subject / 'session_01/new_log.csv').write_text('changed')
        with patch.object(migration.shutil, 'copyfileobj', side_effect=changing):
            with self.assertRaisesRegex(ValueError, '发生变化'):
                migration.migrate(self.old, self.new, True)
        self.assertFalse((self.new / 'sourcedata/v2/00000001').exists())
        self.assertTrue((self.new / '_record_migrations/migration.lock').exists())

    def test_reparse_point_rejected(self):
        original = Path.lstat
        def fake_lstat(path):
            if path == self.subject:
                class Reparse:
                    st_mode = 0o40755
                    st_file_attributes = 0x400
                return Reparse()
            return original(path)
        with patch.object(Path, 'lstat', fake_lstat):
            with self.assertRaisesRegex(ValueError, 'junction'):
                migration.plan(self.old, self.new)

    def test_corrupt_copy_never_published(self):
        def corrupt(inp, out, **kwargs):
            out.write(b'corrupted')
        with patch.object(migration.shutil, 'copyfileobj', side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                migration.migrate(self.old, self.new, True)
        self.assertFalse((self.new / 'sourcedata').exists())

    def test_insufficient_space(self):
        class Usage:
            free = 0
        with patch.object(migration.shutil, 'disk_usage', return_value=Usage()):
            with self.assertRaisesRegex(ValueError, '空间不足'):
                migration.migrate(self.old, self.new, True)
        self.assertFalse((self.new / 'sourcedata').exists())

    def test_legacy_and_v3_keep_layout(self):
        for relative in ('video_question_complete_runs', 'sourcedata/v3_neuracle_emotion_only', 'sourcedata/v3_brainco'):
            self.record(self.old, relative)
        migration.migrate(self.old, self.new, True)
        for relative in migration.ROOTS:
            src = self.old / relative / '00000001'
            if src.exists():
                self.assertEqual(migration.inventory(src), migration.inventory(self.new / relative / '00000001'))


if __name__ == '__main__':
    unittest.main()
