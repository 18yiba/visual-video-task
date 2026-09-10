import csv
from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from video_eeg.experiment import ready_question_runner as ready
from video_eeg.utils.video_library import VideoAsset


class Stim:
    def __init__(self, *args, **kwargs):
        self.text = kwargs.get('text', '')
        self.pos = (0, 0)
    def draw(self):
        pass


class Window:
    def callOnFlip(self, callback, *args, **kwargs):
        callback(*args, **kwargs)
    def flip(self):
        pass


def runner_for_test(path, key):
    runner = object.__new__(ready.QuestionVideoRunner)
    runner.questions = {'a.mp4': {'question': '主要在做什么？',
                                'options': dict(A='跳舞', B='做饭', C='打球', D='画画'), 'answer': 'B'}}
    runner.question_bank_sha256 = 'bank'
    runner.question_rows = []
    runner.progress_dir = path
    runner.config = dict(subject_id='TEST', session_id=1)
    runner.manager = Mock()
    runner.win = Window()
    runner.keyboard = Mock()
    runner.keyboard.getKeys.return_value = [key]
    runner.message = Stim()
    runner.subtitle = Stim()
    runner._clear_keyboard = lambda: None
    return runner


class ReadyQuestionTests(unittest.TestCase):
    def test_choice_and_reaction_time_saved_without_showing_answer(self):
        with TemporaryDirectory() as tmp, patch.object(ready.base, 'visual', SimpleNamespace(TextStim=Stim)):
            runner = runner_for_test(Path(tmp), '2')
            row = runner._run_video_question(1, VideoAsset('a', 'a.mp4'), 1)
            self.assertEqual(row['response'], 'B')
            self.assertTrue(row['correct'])
            self.assertGreaterEqual(row['reaction_time_sec'], 0)
            with (Path(tmp) / 'video_question_log.csv').open(encoding='utf-8-sig') as f:
                self.assertEqual(next(csv.DictReader(f))['response'], 'B')
            self.assertNotIn('正确答案', runner.message.text)
            self.assertEqual(runner.manager.emit.call_args_list[0].args[0], 'attention_task_on')

    def test_escape_is_saved_and_never_commits_unanswered_video(self):
        with TemporaryDirectory() as tmp, patch.object(ready.base, 'visual', SimpleNamespace(TextStim=Stim)):
            runner = runner_for_test(Path(tmp), 'escape')
            runner.state = Mock(video_attempts=[{'question_completed': False}],
                                attention_schedule=[dict(video_id='a', attention_id=1)], completed_attention_ids=[],
                                attention_attempts=[], completed_net_video_duration_sec=0)
            runner._checkpoint = Mock()
            runner._write_attention_log = Mock()
            record = SimpleNamespace(attempt_id=1, planned_video_sec=5)
            with self.assertRaises(ready.base.ExperimentAbort):
                runner._run_post_video_rest(trial_idx=1, asset=VideoAsset('a', 'a.mp4'), record=record)
            runner.state.commit_completed_video.assert_not_called()
            self.assertTrue(runner.question_rows[0]['aborted'])
            self.assertEqual(runner.question_rows[0]['response'], '')

    def test_answer_commits_video_before_rest(self):
        runner = object.__new__(ready.QuestionVideoRunner)
        runner.state = Mock(video_attempts=[{'question_completed': False}],
                            attention_schedule=[dict(video_id='a', attention_id=1)], completed_attention_ids=[])
        runner._run_video_question = Mock()
        runner._checkpoint = Mock()
        runner._write_trial_log = Mock()
        with patch.object(ready.base.VideoRunner, '_run_post_video_rest'):
            runner._run_post_video_rest(trial_idx=1, asset=VideoAsset('a', 'a.mp4'),
                                       record=SimpleNamespace(attempt_id=1, planned_video_sec=5))
        runner.state.commit_completed_video.assert_called_once_with('a', 5.0)
        self.assertTrue(runner.state.video_attempts[0]['question_completed'])

    def test_natural_eof_does_not_commit_before_question(self):
        @dataclass
        class Record:
            asset_id: str = 'a'
            eeg_relative_onset_sec: float = 1
            eeg_relative_offset_sec: float = 6
        runner = object.__new__(ready.QuestionVideoRunner)
        runner.state = Mock(video_attempts=[])
        runner._checkpoint = Mock()
        runner._record_video_attempt(Record(), completed_naturally=True, skipped=False)
        runner.state.commit_completed_video.assert_not_called()
        self.assertFalse(runner.state.video_attempts[0]['question_completed'])

    def test_ready_library_cannot_sample_unanswered_videos(self):
        bank = {'a.mp4': dict(video_id='a', video_file='a.mp4', duration_sec=5)}
        library = ready.ReadyLibrary(Mock(), bank)
        self.assertEqual([a.rel_path for a in library.list_candidate_assets()], ['a.mp4'])

    def test_snapshot_and_session_coverage(self):
        root = ready.base.CONFIG_DIR / 'ready_questions_20260908'
        bank = ready.load_questions(root / 'question_bank.json')
        manifest = ready.base.SessionManifest.load(root / 'session_manifest.csv')
        self.assertEqual(len(bank), 2779)
        self.assertEqual({e.video_path for e in manifest.entries}, set(bank))
        for name in ['video_ready_config.yaml', 'video_ready_demo_config.yaml']:
            config = ready.base.load_config(ready.base.CONFIG_DIR / name)
            protocol = ready.base.VideoExperimentConfig.from_config(config)
            self.assertTrue(protocol.attention_enabled)
            self.assertEqual(protocol.attention_tasks_per_session, 3 if 'demo' in name else 18)

    def test_unselected_video_does_not_ask_question(self):
        runner = object.__new__(ready.QuestionVideoRunner)
        runner.state = Mock(video_attempts=[{}], attention_schedule=[dict(video_id='b', attention_id=1)],
                            completed_attention_ids=[])
        runner._run_video_question = Mock()
        runner._checkpoint = Mock()
        runner._write_trial_log = Mock()
        with patch.object(ready.base.VideoRunner, '_run_post_video_rest'):
            runner._run_post_video_rest(trial_idx=1, asset=VideoAsset('a', 'a.mp4'),
                                       record=SimpleNamespace(attempt_id=1, planned_video_sec=5))
        runner._run_video_question.assert_not_called()
        runner.state.commit_completed_video.assert_called_once_with('a', 5.0)

    def test_full_manifest_has_18_distinct_questions_and_repeatable_resume(self):
        from video_eeg.utils.session_protocol import build_video_question_schedule, SessionState
        import random
        bank = ready.load_questions(ready.base.CONFIG_DIR / 'ready_questions_20260908/question_bank.json')
        manifest = ready.base.SessionManifest.load(ready.base.CONFIG_DIR / 'session_manifest.csv')
        for session in range(1, 18):
            assets = manifest.session_assets(session)
            random.Random(session).shuffle(assets)
            schedule = build_video_question_schedule(assets, bank, random_seed=session)
            self.assertEqual(len(schedule), 18)
            self.assertEqual(len({q['video_id'] for q in schedule}), 18)
            self.assertEqual(schedule, build_video_question_schedule(assets, bank, random_seed=session))
            self.assertNotEqual(schedule, build_video_question_schedule(assets, bank, random_seed=session + 100))
            for q in schedule:
                self.assertEqual(assets[q['after_video_number'] - 1].rel_path, q['video_file'])
                self.assertEqual(q['question_text'], bank[q['video_file']]['question'])
            state = SessionState.new(subject_id='CHECK', session_id=session, manifest=manifest,
                assets=assets, random_seed=session, attention_task_count=18,
                rest_min_minutes=30, rest_max_minutes=45, questions=bank)
            restored = SessionState.from_mapping(json.loads(json.dumps(state.to_mapping())))
            self.assertEqual(restored.attention_schedule, state.attention_schedule)
            self.assertEqual(restored.attention_task_type, 'video_mcq')
            selected = restored.attention_schedule[0]['video_id']
            restored.requeue_skipped_video(selected)
            self.assertEqual(restored.queue_video_ids[-1], selected)
            self.assertEqual(restored.attention_schedule, state.attention_schedule)

    def test_insufficient_bank_fails_instead_of_falling_back_to_arithmetic(self):
        from video_eeg.utils.session_protocol import build_video_question_schedule
        with self.assertRaises(ValueError):
            build_video_question_schedule([VideoAsset('a', 'a.mp4', 5)], {}, task_count=1)

    def test_session_skip_resume_and_exactly_18_completed_checks(self):
        from video_eeg.utils.session_protocol import SessionState, build_duration_balanced_manifest
        assets = [VideoAsset(str(i), f'{i}.mp4', 5) for i in range(40)]
        bank = {a.rel_path: dict(question='Q', options=dict(A='a', B='b', C='c', D='d'), answer='A')
                for a in assets[:30]}
        manifest = build_duration_balanced_manifest(assets, session_count=1)
        runner = object.__new__(ready.QuestionVideoRunner)
        runner.state = SessionState.new(subject_id='TEST', session_id=1, manifest=manifest,
            assets=assets, random_seed=42, attention_task_count=18,
            rest_min_minutes=30, rest_max_minutes=45, questions=bank)
        runner.protocol = SimpleNamespace(attention_tasks_per_session=18)
        runner._run_video_question = Mock()
        runner._checkpoint = Mock()
        runner._write_trial_log = Mock()
        skipped = runner.state.attention_schedule[0]['video_id']
        runner.state.requeue_skipped_video(skipped)
        by_id = {a.asset_id: a for a in assets}
        with patch.object(ready.base.VideoRunner, '_run_post_video_rest'):
            while runner.state.queue_video_ids:
                asset = by_id[runner.state.queue_video_ids[0]]
                runner.state.video_attempts.append({})
                runner._run_post_video_rest(trial_idx=len(runner.state.video_attempts), asset=asset,
                    record=SimpleNamespace(attempt_id=1, planned_video_sec=5))
                # Resume from the checkpoint between every pair of videos.
                runner.state = SessionState.from_mapping(runner.state.to_mapping())
        runner._run_due_attention_tasks(force_remaining=True)
        self.assertEqual(runner.state.completed_attention_count, 18)
        self.assertEqual(runner._run_video_question.call_count, 18)
        self.assertEqual(runner._run_video_question.call_args.args[1].asset_id, skipped)
        self.assertEqual(len(runner.state.completed_video_ids), 40)


if __name__ == '__main__':
    unittest.main()
