"""Scheduled checks about the immediately preceding video, with resumable logs."""
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import time

from video_eeg.experiment import video_runner as base
from video_eeg.utils.video_library import VideoAsset


def load_questions(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    questions = {}
    for q in data['questions']:
        name = q['video_file']
        if (q.get('status') not in {'ready', 'generated_unreviewed'} or not q.get('question') or
                set(q.get('options', {})) != set('ABCD') or q.get('answer') not in set('ABCD') or
                len(set(q['options'].values())) != 4 or name in questions):
            raise ValueError(f'题库包含结构不合规或重复的视频：{name}')
        questions[name] = q
    if not questions:
        raise ValueError('可用题库为空')
    return questions


def question_path(config):
    return base.PROJECT_ROOT / config['protocol']['question_bank_path']


def response_letter(key):
    return dict(zip('1234', 'ABCD')).get(key, key.upper() if key.lower() in 'abcd' and len(key) == 1 else '')


class ReadyLibrary:
    def __init__(self, library, questions):
        self.base = library
        self.questions = questions

    def __getattr__(self, name):
        return getattr(self.base, name)

    def list_assets(self):
        return [VideoAsset(q['video_id'], q['video_file'], q['duration_sec'], duration_status='valid')
                for q in self.questions.values()]

    list_candidate_assets = list_assets


class QuestionVideoRunner(base.VideoRunner):
    def __init__(self, **kwargs):
        config = kwargs['config']
        path = question_path(config)
        self.questions = load_questions(path)
        self.question_bank_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if not kwargs['protocol'].attention_enabled or not kwargs['protocol'].attention_tasks_per_session:
            raise ValueError('视频抽查需要启用 attention_enabled 并设置抽查次数')
        super().__init__(**kwargs)
        self.question_rows = []
        path = self.progress_dir / 'video_question_log.csv'
        if path.exists():
            with path.open(encoding='utf-8-sig', newline='') as stream:
                self.question_rows = list(csv.DictReader(stream))
            if any(r['question_bank_sha256'] != self.question_bank_sha256 for r in self.question_rows):
                raise ValueError('续跑使用的题库与原实验不同，请使用新的被试编号')
        snapshot = self.progress_dir / 'question_bank_snapshot.json'
        if snapshot.exists() and hashlib.sha256(snapshot.read_bytes()).hexdigest() != self.question_bank_sha256:
            raise ValueError('续跑题库快照不一致')
        snapshot.write_bytes(question_path(config).read_bytes())
        # The atomic Session checkpoint is authoritative if CSV export was
        # interrupted. It also retains answered attempts before a crash/replay.
        self.question_rows = list(self.state.attention_attempts)
        self._active_attention_item = None

    def _record_video_attempt(self, record, *, completed_naturally, skipped):
        if not completed_naturally:
            return super()._record_video_attempt(record, completed_naturally=False, skipped=skipped)
        # Keep this video queued until its question is answered. An Esc/crash on
        # the question page must replay the video on resume, not silently skip it.
        self.state.video_attempts.append({
            **asdict(record), 'video_id': record.asset_id, 'completed': True,
            'question_completed': False,
            'image_onset': record.eeg_relative_onset_sec,
            'image_offset': record.eeg_relative_offset_sec})
        self._checkpoint('video_completed_waiting_for_question')

    def _run_post_video_rest(self, *, trial_idx, asset, record):
        item = next((item for item in self.state.attention_schedule
                     if item['video_id'] == asset.asset_id
                     and item['attention_id'] not in self.state.completed_attention_ids), None)
        if item is not None:
            self._active_attention_item = item
            try:
                self._run_video_question(trial_idx, asset, record.attempt_id)
            finally:
                self._active_attention_item = None
            self.state.completed_attention_ids.append(item['attention_id'])
        self.state.video_attempts[-1]['question_required'] = item is not None
        self.state.video_attempts[-1]['question_completed'] = item is not None
        self.state.commit_completed_video(asset.asset_id, float(record.planned_video_sec or 0.0))
        self._checkpoint('video_question_completed')
        self._write_trial_log()
        return super()._run_post_video_rest(trial_idx=trial_idx, asset=asset, record=record)

    def _run_due_attention_tasks(self, *, force_remaining=False):
        # Questions run before committing their own video, never after another
        # video or as a batch at Session end. Skips retain the original binding.
        if force_remaining and self.state.completed_attention_count != self.protocol.attention_tasks_per_session:
            raise RuntimeError('视频抽查未全部完成，不能将 Session 标记为完成')

    def _run_video_question(self, trial_idx, asset, attempt_id):
        q = self.questions[asset.rel_path]
        item = getattr(self, '_active_attention_item', None)
        attention_id = item['attention_id'] if item else None
        manager = self._require_manager()
        self._clear_keyboard()
        base.visual.TextStim(
            self.win, text='请根据刚才的视频内容选择最符合的一项，答题不限时。',
            pos=(0, 0.43), height=0.025, wrapWidth=1.4,
            font=base.FONT_NAME, color=base.MUTED).draw()
        self.message.text = q['question']
        self.message.height = 0.045
        self.message.pos = (0, 0.30)
        self.message.draw()
        for index, letter in enumerate('ABCD'):
            base.visual.TextStim(
                self.win, text=f'{index + 1} / {letter}    {q["options"][letter]}',
                pos=(0, 0.12 - index * 0.11), height=0.04, wrapWidth=1.4,
                font=base.FONT_NAME, color=base.FOREGROUND).draw()
        self.subtitle.text = '请选择 1、2、3、4（或 A、B、C、D）　　Esc 退出并保存'
        self.subtitle.pos = (0, -0.38)
        self.subtitle.draw()
        onset = []
        self.win.callOnFlip(lambda: onset.append(time.perf_counter()))
        self.win.callOnFlip(manager.emit, 'attention_task_on', task_type='video_mcq',
                            attention_id=attention_id, attempt_id=attempt_id,
                            trial_idx=trial_idx, video_name=asset.asset_id,
                            stim_file=asset.rel_path, question=q['question'])
        self.win.flip()
        pressed = ''
        answer = ''
        while not pressed:
            manager.raise_if_background_failed()
            keys = self.keyboard.getKeys(['escape', '1', '2', '3', '4', 'a', 'b', 'c', 'd'],
                                         waitRelease=False, clear=True)
            names = [str(getattr(k, 'name', k)).lower() for k in keys]
            if 'escape' in names:
                pressed = 'escape'
            else:
                pressed = next((k for k in names if response_letter(k)), '')
            if not pressed:
                base.core.wait(0.005)
        offset = time.perf_counter()
        answer = response_letter(pressed)
        row = dict(subject_id=self.config['subject_id'], session_id=self.config['session_id'],
                   attention_id=attention_id, task_type='video_mcq',
                   trial_idx=trial_idx, attempt_id=attempt_id, video_id=asset.asset_id,
                   video_file=asset.rel_path, question=q['question'],
                   **{f'option_{k}': v for k, v in q['options'].items()},
                   correct_answer=q['answer'], response=answer, response_key=pressed,
                   correct=(answer == q['answer']) if answer else '',
                   reaction_time_sec=offset - onset[0] if answer else '',
                   question_onset_monotonic_sec=onset[0], response_monotonic_sec=offset,
                   response_timestamp=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                   aborted=not bool(answer), question_bank_sha256=self.question_bank_sha256,
                   question_review_status=q.get('review_status', q.get('status', 'unspecified')),
                   question_source=q.get('source', 'unspecified'))
        self.win.callOnFlip(manager.emit, 'attention_response', task_type='video_mcq',
                            attention_id=attention_id, attempt_id=attempt_id,
                            trial_idx=trial_idx, video_name=asset.asset_id, response=answer,
                            correct=row['correct'], response_rt_sec=row['reaction_time_sec'],
                            response_monotonic_sec=offset, aborted=not bool(answer))
        self.win.flip()
        if item is not None:
            self.state.attention_attempts.append({**item, **row,
                'actual_trigger_net_time': self.state.completed_net_video_duration_sec +
                    float(asset.duration_sec or 0),
                'response_correct': row['correct'], 'completed': bool(answer)})
            # Completion and video commit are saved together by the caller.
            self._checkpoint('attention_answer_recorded' if answer else 'attention_aborted')
            self._write_attention_log()
        self.question_rows.append(row)
        path = self.progress_dir / 'video_question_log.csv'
        temp = path.with_suffix('.csv.tmp')
        with temp.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=sorted({k for r in self.question_rows for k in r}))
            writer.writeheader()
            writer.writerows(self.question_rows)
        temp.replace(path)
        self.subtitle.pos = (0, -0.10)
        if not answer:
            raise base.ExperimentAbort()
        return row


def main(argv=None):
    original_demo = base.DEMO_CONFIG_FILENAME
    original_default = base.DEFAULT_CONFIG_FILENAME
    try:
        base.DEMO_CONFIG_FILENAME = 'video_ready_demo_config.yaml'
        base.DEFAULT_CONFIG_FILENAME = 'video_ready_config.yaml'
        return base.main(argv)
    finally:
        base.DEMO_CONFIG_FILENAME = original_demo
        base.DEFAULT_CONFIG_FILENAME = original_default


if __name__ == '__main__':
    raise SystemExit(main())
