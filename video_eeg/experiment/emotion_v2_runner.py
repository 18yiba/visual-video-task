"""Versioned seven-point emotion protocol with liking, video MCQ and fatigue."""
from __future__ import annotations
import hashlib
import json
import random
import time
from pathlib import Path
from video_eeg.experiment.emotion_runner import EmotionVideoRunner, base
from video_eeg.experiment.ready_question_runner import load_questions, response_letter
from video_eeg.utils.emotion_protocol import parse_rating

FATIGUE_WORDING = '当前您的疲劳程度是？'
SEVEN_POINT_FATIGUE_OPTIONS = {
    '1': '几乎不疲劳',
    '2': '轻微疲劳',
    '3': '较轻疲劳',
    '4': '中等疲劳',
    '5': '较重疲劳，但不需要额外努力就能继续观看',
    '6': '很疲劳，需要付出一定努力才能继续观看',
    '7': '非常疲劳，需要付出很大努力才能继续观看',
}
FATIGUE_OPTIONS = {
    '1': '几乎不疲劳',
    '2': '轻度疲劳',
    '3': '中等疲劳，但不需要额外努力就能继续观看',
    '4': '较重疲劳，需要付出一定努力才能继续观看',
    '5': '非常疲劳，完全无法继续观看',
}
BINARY_FATIGUE_WORDING = '请判断您此刻的精神状态。'
BINARY_FATIGUE_OPTIONS = {'f': '未感到明显的精神疲劳', 'j': '已感到明显的精神疲劳'}
LIKING_WORDING = '总体而言，您是否喜欢刚才这段视频？'
LIKING_OPTIONS = {'f': '不喜欢', 'j': '喜欢'}
RATING_PAGES_7 = (
    ('valence', '请评价刚才这段视频带给您的主观情绪感受。',
     '1 非常不愉快       4 中性       7 非常愉快'),
    ('arousal', '请评价刚才这段视频引起的情绪唤醒程度。',
     '1 非常平静／几乎没有被激活\n4 中等\n7 非常激动／强烈被激活'),
)


def fatigue_contract_hash(manifest_hash,interval,scale):
    """Preserve published binary/seven-point contracts for in-progress Sessions."""
    contract=dict(version='emotion-v2',scale=7,interval=float(interval),liking=LIKING_OPTIONS,
        fatigue=BINARY_FATIGUE_OPTIONS if scale==2 else SEVEN_POINT_FATIGUE_OPTIONS if scale==7 else FATIGUE_OPTIONS,
        fatigue_wording=BINARY_FATIGUE_WORDING if scale==2 else FATIGUE_WORDING)
    if scale in (5,7):
        contract.update(fatigue_scale_min=1,fatigue_scale_max=scale,
                        fatigue_measure=f'research_adapted_fatigue_{scale}point_v1')
    return manifest_hash+':'+hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest()


def session_fatigue_scale(config,protocol,interval):
    root=base._records_dir(config)/str(config.get('subject_id','S001'))
    if config.get('demo_mode'):root=root/f'run_{protocol.random_seed}'
    saved=base.load_state(root/f"session_{int(config.get('session_id',1)):02d}"/'session_state.json')
    for scale in (2,7):
        if saved is not None and saved.manifest_hash==fatigue_contract_hash(config['session_manifest_hash'],interval,scale):
            return scale
    return 5  # Unknown or changed contracts still fail the normal resume checks.

def alarm_schedule(rows, order, questions, count, interval_sec, seed):
    """Bind one nearby ordinary EOF to each net-time target; persist once."""
    rng=random.Random(seed)
    elapsed=0.; candidates=[]
    for video_id in order:
        row=rows[video_id]; elapsed+=float(row['video_duration_sec'])
        if row['trial_type']=='ordinary' and row['video_path'] in questions:
            candidates.append((video_id,elapsed))
    if len(candidates)<count:raise ValueError('Not enough ordinary videos with questions')
    selected=[]
    for i in range(1,count+1):
        target=min(i*interval_sec,elapsed)
        jitter=rng.uniform(-45.,45.) if interval_sec>=120 else 0.
        chosen=min(candidates,key=lambda c:abs(c[1]-min(elapsed,target+jitter)))
        candidates.remove(chosen)
        selected.append(dict(attention_id=i,video_id=chosen[0],target_net_sec=target,
                             planned_trigger_net_sec=chosen[1],task_type='video_mcq_fatigue'))
    return sorted(selected,key=lambda r:r['planned_trigger_net_sec'])

class EmotionV2Runner(EmotionVideoRunner):
    task_type='emotion_v2_mcq_fatigue_liking_7'
    protocol_version='emotion-v2'
    rating_max=7
    rating_pages=RATING_PAGES_7
    ordinary_behavior_required=True
    fatigue_scale_max=5

    def __init__(self, **kwargs):
        cfg=kwargs['config']; proto=cfg['protocol']
        if int(proto.get('rating_scale_max',7))!=7:
            raise ValueError('Emotion v2 fixes rating_scale_max at 7; use legacy v1 for nine-point recordings')
        if not kwargs['protocol'].attention_enabled or kwargs['protocol'].attention_tasks_per_session<1:
            raise ValueError('Emotion v2 requires video content checks')
        self.interval_sec=float(proto.get('alarm_interval_net_sec',600))
        if self.interval_sec<=0:raise ValueError('alarm_interval_net_sec must be positive')
        if cfg.get('practice_materials'):
            q=dict(video_file='practice_0.mp4',question='刚才练习视频中移动的图形是什么？',
                   options=dict(A='圆形',B='三角形',C='正方形',D='五角星'),answer='A',
                   status='ready',source='synthetic_practice',review_status='practice_only')
            bank={q['video_file']:q}; raw=json.dumps({'questions':[q]},ensure_ascii=False).encode()
        else:
            path=Path(cfg['_project_dir'])/proto['question_bank_path']
            raw=path.read_bytes(); bank=load_questions(path)
        self.question_bank_sha256=hashlib.sha256(raw).hexdigest()
        self.questions={r['video_path']:bank[Path(r['video_path']).name]
                        for r in kwargs['library'].rows.values()
                        if r['trial_type']=='ordinary' and Path(r['video_path']).name in bank}
        self.fatigue_scale_max=session_fatigue_scale(cfg,kwargs['protocol'],self.interval_sec)
        cfg['session_manifest_hash']=fatigue_contract_hash(cfg['session_manifest_hash'],self.interval_sec,self.fatigue_scale_max)
        cfg['fatigue_measure']=self._fatigue_metadata()
        if self.fatigue_scale_max!=5:
            print(f'本Session已有{self.fatigue_scale_max}档疲劳进度，将保持原量尺续跑；下一个新Session使用1–5点评分。',flush=True)
        super().__init__(**kwargs)
        snapshot=self.progress_dir/'question_bank_snapshot.json'
        if snapshot.exists():
            if snapshot.read_bytes()!=raw:raise RuntimeError('Saved question snapshot differs; restore original bank')
        else:
            with snapshot.open('xb') as f:f.write(raw)

    def _initialize_new_state(self):
        super()._initialize_new_state()
        self.state.attention_schedule=alarm_schedule(self.library.rows,self.state.queue_video_ids,self.questions,
            self.protocol.attention_tasks_per_session,self.interval_sec,self.state.random_seed+7919)

    def _fatigue_options(self):
        return SEVEN_POINT_FATIGUE_OPTIONS if self.fatigue_scale_max==7 else FATIGUE_OPTIONS

    def _fatigue_metadata(self):
        binary=self.fatigue_scale_max==2
        return dict(fatigue_wording=BINARY_FATIGUE_WORDING if binary else FATIGUE_WORDING,
            fatigue_scale_min=0 if binary else 1,fatigue_scale_max=1 if binary else self.fatigue_scale_max,
            fatigue_measure='research_adapted_binary_state_v1' if binary else f'research_adapted_fatigue_{self.fatigue_scale_max}point_v1',
            fatigue_key_map='F=0 no noticeable mental fatigue; J=1 noticeable mental fatigue' if binary else '; '.join(f'{k}={v}' for k,v in self._fatigue_options().items()),
            fatigue_scale_type='binary' if binary else 'seven_point' if self.fatigue_scale_max==7 else 'five_point')

    def _show_instructions(self):
        fatigue_instruction=('抽查下一页仍使用本Session原疲劳题：F 未感到明显精神疲劳，J 已感到明显精神疲劳。\n\n'
            if self.fatigue_scale_max==2 else f'抽查下一页请评价当前疲劳程度：按数字1–{self.fatigue_scale_max}，1 几乎不疲劳，{self.fatigue_scale_max} {self._fatigue_options()[str(self.fatigue_scale_max)]}。\n\n')
        self._show_text('本实验连续记录脑电，请自然观看视频并聆听声音，尽量保持坐姿稳定。\n\n'
          '普通视频后请判断是否喜欢：F 不喜欢，J 喜欢。\n'
          '约每10分钟净视频有一道内容抽查，请按1–4或A–D作答。\n'
          +fatigue_instruction+
          '情绪视频后依次评价情绪感受和唤醒程度：按数字1–7，主观评价没有正确答案。\n'
          '所有作答不限时。短休息空格继续；长休息F继续、J保存退出。\n'
          'S暂时跳过视频后会重播，Esc保存退出。未完成的视频及其问题下次完整重做。\n\n按空格继续。')

    def _run_due_attention_tasks(self, *, force_remaining=False):
        if force_remaining and self.state.completed_attention_count!=self.protocol.attention_tasks_per_session:
            raise RuntimeError('Some bound video checks remain incomplete')

    def _choice_page(self, row, prefix, wording, options, keys, event_prefix):
        measure=self._fatigue_metadata() if prefix=='fatigue' else {}
        self._clear_keyboard()
        self.message.pos=(0,0);self.message.height=.033
        self.message.text=wording+'\n\n'+'\n\n'.join(options)+'\n\n答题不限时；Esc 保存退出。'
        self.message.draw()
        if hasattr(self.keyboard,'clock'):self.win.callOnFlip(self.keyboard.clock.reset)
        self.win.callOnFlip(self.manager.emit,event_prefix+'_ONSET',**measure)
        self.win.flip()
        stamp=self._event_times[event_prefix+'_ONSET']
        row.update({prefix+'_onset_'+k:v for k,v in stamp.items()})
        self._checkpoint(prefix+'_onset')
        released=not hasattr(self.keyboard,'getState') or not any(self.keyboard.getState(keys))
        while True:
            self._require_manager()
            presses=self.keyboard.getKeys(['escape']+keys,waitRelease=False,clear=True)
            if any(str(getattr(k,'name',k)).lower()=='escape' for k in presses):raise base.ExperimentAbort()
            if not released:
                released=not any(self.keyboard.getState(keys));base.core.wait(.005);continue
            for key in presses:
                name=str(getattr(key,'name',key)).lower()
                if name not in keys:continue
                detected=time.perf_counter();rt=getattr(key,'rt',None)
                rt=max(0.,float(rt)) if rt is not None else max(0.,detected-stamp['monotonic_sec'])
                score=({'fatigued':int(name=='j')} if self.fatigue_scale_max==2 else
                       {'fatigue_rating':parse_rating(name,self.fatigue_scale_max)}) if prefix=='fatigue' else {}
                self.manager.emit(event_prefix+'_RESPONSE',response_key=name,response_rt_sec=rt,
                                  response_monotonic_sec=stamp['monotonic_sec']+rt,**measure,**score)
                row.update(score)
                row.update({prefix+'_key':name,prefix+'_rt_sec':rt,
                            prefix+'_response_monotonic_sec':stamp['monotonic_sec']+rt,
                            prefix+'_response_detected_monotonic_sec':detected,
                            prefix+'_response_sample_index':self._event_times[event_prefix+'_RESPONSE']['sample_index'],
                            prefix+'_response_timestamp_unix_sec':self._event_times[event_prefix+'_RESPONSE']['timestamp_unix_sec']})
                self._checkpoint(prefix+'_response');return name
            base.core.wait(.005)

    def _run_post_video_rest(self, *, trial_idx, asset, record):
        if self.library.rows[asset.asset_id]['trial_type']=='emotion':
            return super()._run_post_video_rest(trial_idx=trial_idx,asset=asset,record=record)
        attempt=self.state.video_attempts[-1]
        item=next((x for x in self.state.attention_schedule if x['video_id']==asset.asset_id),None)
        behavior=dict(protocol_version=self.protocol_version,subject_id=self.state.subject_id,
            session_id=self.state.session_id,trial_id=trial_idx,attempt_id=record.attempt_id,
            video_id=asset.asset_id,video_path=asset.rel_path,eeg_part=record.eeg_part,
            eeg_recording_dir=str(self.manager.session_dir),completed=False,interrupted=False,
            alarm_required=item is not None,liking_wording=LIKING_WORDING,
            liking_key_map='F=0 dislike; J=1 like')
        attempt['ordinary_behavior']=behavior
        try:
            key=self._choice_page(behavior,'liking',LIKING_WORDING,
                ['F  不喜欢','J  喜欢'],['f','j'],'LIKING')
            behavior['liked']=int(key=='j')
            self._checkpoint('liking_answered')
            if item is not None:
                q=self.questions[asset.rel_path]
                behavior.update(attention_id=item['attention_id'],question=q['question'],
                    question_bank_sha256=self.question_bank_sha256,correct_answer=q['answer'],
                    question_review_status=q.get('review_status',q.get('status','unspecified')),
                    question_source=q.get('source','unspecified'),
                    **{f'option_{k}':v for k,v in q['options'].items()},
                    target_net_sec=item['target_net_sec'],planned_trigger_net_sec=item['planned_trigger_net_sec'],
                    actual_trigger_net_sec=self.state.completed_net_video_duration_sec)
                key=self._choice_page(behavior,'alarm',
                    '请根据刚才的视频内容选择最符合的一项。\n\n'+q['question'],
                    [f'{i+1} / {k}    {q["options"][k]}' for i,k in enumerate('ABCD')],
                    list('1234abcd'),'ALARM')
                behavior.update(response=response_letter(key),correct=response_letter(key)==q['answer'])
                behavior.update(self._fatigue_metadata())
                if self.fatigue_scale_max==2:
                    key=self._choice_page(behavior,'fatigue',BINARY_FATIGUE_WORDING,
                        ['F  '+BINARY_FATIGUE_OPTIONS['f'],'J  '+BINARY_FATIGUE_OPTIONS['j']],['f','j'],'FATIGUE')
                    behavior['fatigued']=int(key=='j')
                else:
                    key=self._choice_page(behavior,'fatigue',FATIGUE_WORDING,
                        [f'{k}  {v}' for k,v in self._fatigue_options().items()],
                        [str(i) for i in range(1,self.fatigue_scale_max+1)]+[f'num_{i}' for i in range(1,self.fatigue_scale_max+1)],'FATIGUE')
                    behavior['fatigue_rating']=parse_rating(key,self.fatigue_scale_max)
            self.manager.emit('trial_end',completed=True,ratings_completed=True,status='completed')
            behavior['completed']=True;attempt['completed']=True
            if item is not None:self.state.completed_attention_ids.append(item['attention_id'])
            self.state.commit_completed_video(asset.asset_id,0.)
            self._checkpoint('ordinary_behavior_completed')
        except BaseException:
            behavior['interrupted']=True
            if not behavior['completed']:self.state.preserve_aborted_video(asset.asset_id)
            self._checkpoint('ordinary_behavior_interrupted')
            raise
        finally:
            self._write_attention_log();self._write_trial_log()
        return base.VideoRunner._run_post_video_rest(self,trial_idx=trial_idx,asset=asset,record=record)

    def _write_attention_log(self):
        rows=[r['ordinary_behavior'] for r in self.state.video_attempts if 'ordinary_behavior' in r]
        self._write_csv('ordinary_behavior_log.csv',rows)
        self._write_csv('video_liking_log.csv',rows)
        checks=[r for r in rows if r['alarm_required']]
        self._write_csv('video_question_log.csv',checks)
        self._write_csv('fatigue_log.csv',[r for r in checks if 'fatigue_onset_monotonic_sec' in r])

    def _write_trial_log(self):
        self._write_csv('trial_log.csv',[{k:v for k,v in r.items() if k not in {'emotion_rating','ordinary_behavior'}}
                                      for r in self.state.video_attempts])
