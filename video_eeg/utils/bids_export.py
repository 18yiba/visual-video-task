"""Offline EEG-BIDS export of saved video recordings; source files are read-only.

Each acquisition/part is a separate recording.  Samples are never concatenated,
resampled, filtered, padded or repaired.  A failed export cannot change progress.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
VERSION = '1.0.4'
TABLES = ('trial_log.csv', 'emotion_rating_log.csv', 'ordinary_behavior_log.csv',
          'video_liking_log.csv', 'video_question_log.csv', 'fatigue_log.csv',
          'attention_log.csv', 'rest_log.csv')
PAIRS = {'video_on': 'video_off', 'EMOTION_VIDEO_ONSET': 'EMOTION_VIDEO_OFFSET',
         'fixation_on': 'fixation_off', 'break_start': 'break_end',
         'SHORT_REST_ONSET': 'SHORT_REST_OFFSET', 'rest_start': 'rest_end',
         'VALENCE_RATING_ONSET': 'VALENCE_RATING_RESPONSE',
         'AROUSAL_RATING_ONSET': 'AROUSAL_RATING_RESPONSE',
         'LIKING_ONSET': 'LIKING_RESPONSE', 'ALARM_ONSET': 'ALARM_RESPONSE',
         'FATIGUE_ONSET': 'FATIGUE_RESPONSE', 'attention_task_on': 'attention_response'}
COLUMNS = ('onset', 'duration', 'trial_type', 'sample', 'response_time', 'response',
           'rating', 'valence', 'arousal', 'liked', 'fatigue_rating', 'fatigue_scale_min',
           'fatigue_scale_max', 'fatigue_scale_type', 'correct', 'completed',
           'video_id', 'video_category', 'trial_id', 'attempt_id', 'source_table',
           'source_elapsed_time', 'eeg_available', 'quality_note', 'source_details')


class BidsExportError(ValueError):
    pass


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def no_links(path):
    path = Path(path).absolute()
    for p in (path, *path.parents):
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise BidsExportError('不支持链接或 junction：'+str(p))
    return path.resolve()


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def cell(value):
    if value is None or value == '':
        return 'n/a'
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return format(value, '.12g') if math.isfinite(value) else 'n/a'
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return str(value).replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')


def write_tsv(path, rows, fields):
    with Path(path).open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: cell(row.get(key)) for key in fields})


def safe_details(row):
    # Retain source variables, but do not export identifying machine paths.
    result = {}
    for key, value in row.items():
        if isinstance(value, str) and (re.match(r'^[A-Za-z]:[\\/]', value) or value.startswith('\\\\')):
            value = value.replace('\\', '/').rsplit('/', 1)[-1]
        result[key] = value
    return result


def profile_for(metadata, source_rows, profile=None):
    if metadata.get('eeg_format') == 'EDF':
        from video_eeg.storage.native_edf import REVISION, CHANNEL_NAMES
        native = metadata.get('native_edf_profile', {})
        if (metadata.get('device_type') not in {'brainco', 'brainco_lsl'} or source_rows != 32 or
                native.get('revision') != REVISION or native.get('channel_names') != list(CHANNEL_NAMES)):
            raise BidsExportError('Native EDF device/channel contract mismatch.')
        return native
    if profile is None:
        profile = read_json(ROOT/'video_eeg/config/bids_profile.json')
    if metadata.get('device_type', '').lower() != profile['device_type']:
        raise BidsExportError('设备不匹配；请使用对应设备的真实 BIDS 通道/单位配置。')
    names = profile['channel_names']
    if not names or len(set(names)) != len(names) or source_rows != len(names)+1:
        raise BidsExportError('通道数/名称与已确认配置不符，未猜测通道顺序。')
    if profile.get('sample_counter_row') != 0 or profile.get('unit') != 'uV':
        raise BidsExportError('当前导出器仅支持已确认的首行计数、EEG单位uV配置。')
    if any(not re.fullmatch(r'[A-Za-z0-9]+', str(name)) for name in names):
        raise BidsExportError('通道名称必须为非重复字母/数字标签。')
    return profile


def load_signal(path, metadata):
    if metadata.get('eeg_format') == 'EDF':
        if path.suffix.lower() != '.edf':
            raise BidsExportError('EDF metadata requires an EDF source file.')
        from video_eeg.storage.native_edf import read_edf
        return read_edf(path, metadata)
    return np.load(path, mmap_mode='r', allow_pickle=False)


def recording_files(directory):
    directory = no_links(directory)
    return sorted(no_links(p) for p in directory.glob('metadata*.json'))


def discover(source):
    source = no_links(source)
    result = []
    for folder, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'bids', 'bids_demo', '__pycache__'}]
        for d in dirs:
            no_links(Path(folder)/d)
        if 'metadata.json' in files:
            result.append(Path(folder))
    return sorted(set(result))


def stamp_of(directory, metadata):
    value = metadata.get('session_stamp') or metadata.get('timestamp_label') or Path(directory).name
    match = re.search(r'(\d{8})[_T](\d{6})', str(value))
    if not match:
        raise BidsExportError('缺少可靠采集时间戳，不能自动建立录制映射。')
    stamp = match[1]+'T'+match[2]
    start = datetime.strptime(stamp, '%Y%m%dT%H%M%S').replace(tzinfo=timezone(timedelta(hours=8))).timestamp()
    return stamp, start


def select_tables(directory, metadata, events, part, *, ignore_tables=()):
    """Select cumulative behavior by recording identity/time, never part alone."""
    directory = Path(directory)
    stamp, start = stamp_of(directory, metadata)
    elapsed = max((number(e.get('relative_time_sec')) or 0 for e in events), default=0)
    end = start + elapsed + 5
    multiple_parts = len(recording_files(directory)) > 1
    unix_times = [number(e.get('payload', {}).get('timestamp_unix_sec')) for e in events]
    unix_times = [x for x in unix_times if x is not None]
    if multiple_parts and unix_times:
        start, end = min(unix_times)-2, max(unix_times)+2
    for sibling in directory.parent.iterdir():
        if sibling.is_dir() and (sibling/'metadata.json').is_file():
            _, sibling_start = stamp_of(sibling, read_json(sibling/'metadata.json'))
            if sibling_start > start:
                end = min(end, sibling_start)
    selected = {}
    for name in TABLES:
        if name in ignore_tables:
            continue
        candidates = [directory.parent/name, directory/name]
        # A recovery CSV may contain newer data than the locked original. Do not guess.
        for candidate in candidates:
            if list(candidate.parent.glob(candidate.stem+'.recovered_*.csv')):
                raise BidsExportError('发现恢复CSV，请先核对原表与恢复表后重导出：'+name)
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            continue
        path = no_links(path)
        rows = []
        with path.open(encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                row_part = number(row.get('eeg_part'))
                if row_part is not None and row_part != part:
                    continue
                ref = row.get('eeg_recording_dir', '')
                if ref:
                    match = re.search(r'(\d{8})[_T](\d{6})(?:[/\\]?$)', ref)
                    belongs = bool(match and match[1]+'T'+match[2] == stamp)
                else:
                    t = next((number(row.get(key)) for key in ('started_at_unix_sec', 'video_onset_unix_sec',
                             'page_onset_timestamp_unix_sec', 'onset_timestamp_unix_sec')
                              if number(row.get(key)) is not None), None)
                    if t is None:
                        for key in ('timestamp', 'page_onset_timestamp', 'response_timestamp'):
                            try:
                                dt = datetime.fromisoformat(row.get(key, ''))
                                t = dt.replace(tzinfo=dt.tzinfo or timezone(timedelta(hours=8))).timestamp()
                                break
                            except ValueError:
                                pass
                    if t is None:
                        # Rows without an identity/time cannot be assigned across resumptions.
                        raise BidsExportError('行为表缺少可核对的采集归属/绝对时间：'+name)
                    belongs = start-2 <= t < end
                if belongs and multiple_parts and row_part is None:
                    raise BidsExportError('多段采集的行为行缺少eeg_part，不能可靠分配；保留原表供人工核对：'+name)
                if belongs:
                    rows.append(safe_details(row))
        selected[name] = rows
    return selected


def same_trial(a, b):
    pa, pb = a.get('payload', {}), b.get('payload', {})
    for aliases in (('trial_id', 'trial_idx'), ('video_id', 'video_name'), ('attempt_id',)):
        va = next((pa[k] for k in aliases if k in pa), None)
        vb = next((pb[k] for k in aliases if k in pb), None)
        if va is not None and vb is not None and str(va) != str(vb):
            return False
    return True


def behavior_fields(payload):
    result = {}
    aliases = {'video_id': ('video_id', 'video_name', 'asset_id'), 'video_category': ('trial_type',),
               'trial_id': ('trial_id', 'trial_idx'), 'response_time': ('rt_sec', 'reaction_time_sec'),
               'valence': ('valence_rating',), 'arousal': ('arousal_rating',),
               'response': ('response', 'key', 'rating_key')}
    for field in COLUMNS:
        if field in payload and field not in ('onset', 'duration', 'sample', 'trial_type', 'source_details'):
            result[field] = payload[field]
    for field, names in aliases.items():
        for name in names:
            if payload.get(name) not in (None, ''):
                result[field] = payload[name]
                break
    return result


def build_events(events, tables, n_samples, sfreq):
    output, quality = [], []
    freeze_from = None
    for i, (a, b) in enumerate(zip(events, events[1:])):
        ia, ib = number(a.get('sample_index')), number(b.get('sample_index'))
        ta, tb = number(a.get('relative_time_sec')), number(b.get('relative_time_sec'))
        if None not in (ia, ib, ta, tb) and tb-ta > 2 and ia == ib:
            quality.append({'code': 'SAMPLE_FREEZE', 'event_start': i, 'event_end': i+1,
                            'elapsed_seconds': tb-ta, 'sample_index': ia})
            if ia == n_samples:
                freeze_from = min(freeze_from if freeze_from is not None else i, i)
    for i, event in enumerate(events):
        name = str(event.get('name', 'unknown'))
        payload = event.get('payload') or {}
        sample = number(event.get('sample_index'))
        valid = sample is not None and sample.is_integer() and 0 <= sample <= n_samples
        valid = valid and payload.get('eeg_available') is not False and not (freeze_from is not None and i >= freeze_from)
        duration = 0.0
        note = ''
        if name in PAIRS:
            matched = None
            for later in events[i+1:]:
                if later.get('name') == name and same_trial(event, later):
                    break
                if later.get('name') == PAIRS[name] and same_trial(event, later):
                    matched = later
                    break
            if matched is None:
                duration = None
                note = 'missing_offset'
            else:
                off = number(matched.get('sample_index'))
                if sample is None or off is None or off < sample or off > n_samples:
                    duration = None
                    valid = False
                    note = 'invalid_sample_boundary'
                else:
                    duration = (off-sample)/sfreq
                    wall = (number(matched.get('relative_time_sec')) or 0)-(number(event.get('relative_time_sec')) or 0)
                    if wall > 2 and off == sample:
                        valid = False
                        note = 'no_eeg_samples_during_interval'
                    elif wall-duration > 2:
                        note = 'possible_acquisition_gap'
                        quality.append({'code': 'TIMING_GAP', 'event_start': i, 'wall_minus_samples_seconds': wall-duration})
        if not valid:
            note = note or 'unavailable_eeg_timing'
            quality.append({'code': 'UNAVAILABLE_EVENT_TIMING', 'event_index': i, 'name': name})
        row = dict(onset=sample/sfreq if valid else None, duration=duration if valid else None,
                   trial_type=name, sample=int(sample) if valid else None,
                   source_elapsed_time=event.get('relative_time_sec'), eeg_available=valid,
                   source_event_index=i,
                   source_table='events.json', quality_note=note,
                   source_details=safe_details(payload))
        row.update(behavior_fields(payload))
        # Never allow payload fields to override the timing assessment.
        row['eeg_available'] = valid
        row['quality_note'] = note
        output.append(row)
    for table, rows in tables.items():
        for source_row in rows:
            row = behavior_fields(source_row)
            trial = row.get('trial_id')
            matches = [r for r in output if r.get('source_table') == 'events.json'
                       and r['trial_type'] in ('video_on', 'EMOTION_VIDEO_ONSET')
                       and str(r.get('trial_id')) == str(trial)
                       and (row.get('attempt_id') in (None, '') or str(r.get('attempt_id')) == str(row['attempt_id']))
                       and (row.get('video_id') in (None, '') or str(r.get('video_id')) == str(row['video_id']))] if trial is not None else []
            # Summary rows describe the attempt; their onset is its video onset.
            anchor = matches[0] if len(matches) == 1 else None
            row.update(onset=anchor['onset'] if anchor else None, duration=0.0 if anchor else None,
                       trial_type='behavior_summary', sample=anchor['sample'] if anchor else None,
                       source_table=table, source_details=source_row,
                       eeg_available=bool(anchor and anchor['eeg_available']),
                       quality_note='' if anchor else 'summary_without_unique_video_anchor')
            output.append(row)
    output.sort(key=lambda r: (r['onset'] is None, r['onset'] if r['onset'] is not None else 0))
    return output, quality


def write_brainvision(folder, prefix, data, sfreq, names):
    """BrainVision Core float32 multiplexed, native uV and resolution 1 uV."""
    with (folder/(prefix+'.eeg')).open('xb') as f:
        for offset in range(0, data.shape[1], 65536):
            block = np.asarray(data[1:, offset:offset+65536], dtype='<f4')
            if not np.isfinite(block).all():
                raise BidsExportError('EEG含NaN/Inf；原始数据保留，不自动填充。')
            f.write(block.T.copy(order='C').tobytes())
    common = f'DataFile={prefix}.eeg\nMarkerFile={prefix}.vmrk\nDataFormat=BINARY\nDataOrientation=MULTIPLEXED\nNumberOfChannels={len(names)}\nSamplingInterval={1000000/sfreq:.12g}\n'
    channels = '\n'.join(f'Ch{i}={name},,1,µV' for i, name in enumerate(names, 1))
    (folder/(prefix+'.vhdr')).write_text('Brain Vision Data Exchange Header File Version 1.0\n\n[Common Infos]\nCodepage=UTF-8\n'+common+'\n[Binary Infos]\nBinaryFormat=IEEE_FLOAT_32\n\n[Channel Infos]\n'+channels+'\n', encoding='utf-8')
    (folder/(prefix+'.vmrk')).write_text('Brain Vision Data Exchange Marker File, Version 1.0\n\n[Common Infos]\nCodepage=UTF-8\nDataFile='+prefix+'.eeg\n\n[Marker Infos]\nMk1=New Segment,,1,1,0\n', encoding='utf-8')


@contextmanager
def dataset_lock(root):
    lock = root.parent/('.'+root.name+'.export.lock')
    try:
        handle = lock.open('x', encoding='utf-8')
    except FileExistsError as exc:
        raise BidsExportError('已有BIDS导出在运行，或存在中断锁；请核对：'+str(lock)) from exc
    try:
        handle.write(str(os.getpid())); handle.close()
        yield
    finally:
        lock.unlink()


def init_dataset(root, protocol):
    desc = root/'dataset_description.json'
    if desc.exists():
        old = read_json(desc)
        if old.get('SourceProtocol') != protocol or old.get('GeneratedBy', [{}])[0].get('Name') != 'visual-video-task':
            raise BidsExportError('输出目录已有其他数据集，不合并或覆盖。')
        return
    if root.exists() and any(root.iterdir()):
        raise BidsExportError('请选择空目录或本导出器建立的BIDS数据集。')
    root.mkdir(parents=True, exist_ok=True)
    write_json(desc, {'Name': 'Video EEG '+protocol, 'BIDSVersion': '1.11.1', 'DatasetType': 'raw',
                      'SourceProtocol': protocol, 'GeneratedBy': [{'Name': 'visual-video-task', 'Version': VERSION}],
                      'ReferencesAndLinks': ['https://github.com/18yiba/visual-video-task']})
    (root/'README').write_text('Video EEG '+protocol+'\n\nRaw samples exported without filtering/resampling. Source NPY, event JSON, behavior CSV and recovery state remain unchanged outside this dataset.\nEach acq/run is a separate acquisition segment; ses is the original paradigm Session group, which can span dates.\nEEG timing uses segment-local sample indices / sampling frequency. Unavailable timing is n/a; inspect quality_note and code/exports receipts.\nBehavior summary rows preserve each source table and may contain redundant views of the same trial. They are not additional trials. All event payloads and behavioral source variables are in source_details.\nOriginal stimulus IDs are recorded in video_id/source_details. Stimulus binaries are not copied, and no misleading stim_file paths are emitted.\nThe first source row is a validated sample counter, retained only in the source NPY. Remaining 31 rows are EEG in uV, IO reference per the lab-confirmed profile.\nNo electrode coordinates, demographics, license, or channel quality assessments were invented.\n', encoding='utf-8')
    write_json(root/'participants.json', {'participant_id': {'Description': 'Source participant label, prefixed with sub-; no demographic information inferred.'}})


def export_recording(directory, output, *, protocol, profile=None):
    directory, output = no_links(directory), no_links(output)
    if protocol not in ('v1', 'v2'):
        raise BidsExportError('请选择原协议v1或v2；不自动转换旧协议身份。')
    if output.is_relative_to(directory) or directory.is_relative_to(output):
        raise BidsExportError('BIDS输出必须独立于原始采集目录。')
    metadata_files = recording_files(directory)
    if not metadata_files:
        raise BidsExportError('所选目录没有metadata.json。')
    results = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with dataset_lock(output):
        for meta_path in metadata_files:
            m = read_json(meta_path)
            if m.get('demo_mode') or m.get('eeg_mode') == 'dummy' or m.get('device_type') == 'dummy':
                raise BidsExportError('Demo模拟数据不导入正式BIDS数据集。')
            if not m.get('local_eeg_recorded', True):
                raise BidsExportError('外部录制模式：须先取得外部EEG，不能把行为记录冒充EEG。')
            if bool(m.get('protocol_version') == 'emotion-v2' or m.get('num_sessions') == 45) != (protocol == 'v2'):
                raise BidsExportError('所选协议与采集metadata不符，拒绝混合v1/v2。')
            if protocol == 'v1':
                kinds = {str(row.get('task_type', '')) for row in m.get('attention_schedule', [])}
                if m.get('num_sessions') != 17 or not kinds or kinds != {'video_mcq'}:
                    raise BidsExportError('源记录不是已确认的17组内容题v1；旧算术/34组/身份不明记录须独立适配，不改协议标签。')
            elif m.get('protocol_version') not in (None, 'emotion-v2') or m.get('num_sessions') != 45:
                raise BidsExportError('源记录不是45组emotion-v2，不能转换协议身份。')
            subject = str(m.get('subject_id', ''))
            if not re.fullmatch(r'[A-Za-z0-9]+', subject):
                raise BidsExportError('被试编号需要显式匿名映射为字母/数字；不静默删字符或合并编号。')
            session = int(m['session_id']); part = int(m.get('eeg_part', 1))
            if session < 1 or part < 1:
                raise BidsExportError('无效Session/采集段编号。')
            if m.get('sample_index_origin', 'segment_local') != 'segment_local':
                raise BidsExportError('样本索引不是段内坐标；不能推测事件时间。')
            stamp, _ = stamp_of(directory, m)
            def source_file(key, fallback):
                name = m.get(key) or fallback
                if Path(name).name != name or '/' in name or '\\' in name:
                    raise BidsExportError('源文件字段必须为同目录文件名。')
                return no_links(directory/name)
            eeg_path = source_file('eeg_file', 'continuous_eeg.npy')
            event_path = source_file('events_file', 'events.json')
            data = load_signal(eeg_path, m)
            try:
                if data.ndim != 2 or data.shape[1] < 2:
                    raise BidsExportError('EEG为空或数组维度不正确。')
                if m.get('eeg_format') != 'EDF' and (data.dtype.kind != 'f' or data.dtype.itemsize != 4):
                    raise BidsExportError('源EEG不是float32；为避免隐式精度损失，未自动转换。')
                if m.get('n_channels') is not None and int(m['n_channels']) != data.shape[0]:
                    raise BidsExportError('metadata通道数与EEG数组不符。')
                p = profile_for(m, data.shape[0], profile)
                sf = number(m.get('sfreq'))
                if sf is None or sf <= 0:
                    raise BidsExportError('缺少真实采样率。')
                if m.get('sample_count') is not None and int(m['sample_count']) != data.shape[1]:
                    raise BidsExportError('metadata样本数与EEG不符。')
                if p.get('sample_counter_row') == 0:
                    counter = np.asarray(data[0, :min(data.shape[1], 500000)], dtype='float64')
                    if np.mean(np.diff(counter) == 1) < .95:
                        raise BidsExportError('首行计数验证失败，未删除未知通道。')
                events = read_json(event_path)
                if not isinstance(events, list):
                    raise BidsExportError('events.json不是事件列表。')
                tables = select_tables(directory, m, events, part)
                rows, quality = build_events(events, tables, data.shape[1], sf)
                prefix = f'sub-{subject}_ses-{session:02d}_task-video{protocol}_acq-{stamp}_run-{part:02d}'
                hashes = {'eeg': digest(eeg_path), 'events': digest(event_path), 'metadata': digest(meta_path),
                          'selected_behavior': hashlib.sha256(json.dumps(tables, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                          'profile': hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()}
                receipt_path = output/'code/exports'/(prefix+'.json')
                if receipt_path.exists():
                    receipt = read_json(receipt_path)
                    if receipt['source_hashes'] != hashes:
                        raise BidsExportError('已有BIDS副本与当前源数据不同，请另选输出目录，不覆盖历史导出。')
                    if not all((output/name).is_file() and digest(output/name) == h for name, h in receipt['output_hashes'].items()):
                        raise BidsExportError('已有BIDS文件被修改或缺失，请另选输出目录。')
                    results.append({'status': 'EXISTS_VERIFIED', 'prefix': prefix, 'quality_flags': receipt['quality_flags']})
                    continue
                init_dataset(output, protocol)
                stage = output.parent/('.bids-stage-'+uuid4().hex)
                stage.mkdir()
                destination = no_links(output/f'sub-{subject}'/f'ses-{session:02d}'/'eeg')
                try:
                    if shutil.disk_usage(output).free < (data.shape[0]-1)*data.shape[1]*4+64*1024*1024:
                        raise BidsExportError('磁盘空间不足；原始数据已保存，BIDS可稍后重试。')
                    eeg_prefix = prefix+'_eeg'
                    if m.get('eeg_format') == 'EDF':
                        shutil.copyfile(eeg_path, stage/(eeg_prefix+'.edf'))
                    else:
                        write_brainvision(stage, eeg_prefix, data, sf, p['channel_names'])
                    write_tsv(stage/(prefix+'_events.tsv'), rows, COLUMNS)
                    descriptions = {key: {'Description': 'Source variable: '+key} for key in COLUMNS}
                    descriptions.update(onset={'Description': 'Seconds from first stored EEG sample; n/a when unavailable.', 'Units': 's'},
                                        duration={'Description': 'Sample-aligned interval duration; zero for point markers, n/a for missing/invalid offset.', 'Units': 's'},
                                        response_time={'Description': 'Source behavioral reaction time, not EEG sample latency.', 'Units': 's'},
                                        source_details={'Description': 'JSON-encoded original event payload or behavioral table row; machine paths reduced to basename.'},
                                        source_table={'Description': 'events.json or original behavior CSV name; summary rows can be redundant views, not additional trials.'},
                                        trial_type={'Description': 'Original event name; behavior_summary marks a source behavior row.'})
                    write_json(stage/(prefix+'_events.json'), descriptions)
                    write_tsv(stage/(prefix+'_channels.tsv'), [{'name': name, 'type': 'EEG', 'units': 'uV', 'sampling_frequency': sf} for name in p['channel_names']], ('name','type','units','sampling_frequency'))
                    write_json(stage/(prefix+'_eeg.json'), {'TaskName': 'video'+protocol, 'SamplingFrequency': sf,
                        'PowerLineFrequency': p['power_line_frequency'], 'EEGReference': p['reference'],
                        'SoftwareFilters': p.get('software_filters', 'n/a'), 'Manufacturer': p['manufacturer'],
                        'EEGChannelCount': len(p['channel_names']), 'RecordingType': 'continuous',
                        'RecordingDuration': data.shape[1]/sf, 'SourceSampleCounterRow': p.get('sample_counter_row'),
                        'SourceProtocol': m.get('protocol_version') or protocol, 'SourceSessionNumber': session,
                        'SourceTerminationReason': m.get('termination_reason', 'n/a'),
                        'SourceSessionCompleted': bool(m.get('session_completed', False)),
                        'SourceProfileConfirmation': p['confirmation'], 'SourceQualityFlagCount': len(quality),
                        'TaskDescription': 'Video viewing with original protocol-specific behavioral responses and rests; see events.',
                        'InstitutionName': 'n/a'})
                    if digest(eeg_path) != hashes['eeg'] or digest(event_path) != hashes['events'] or digest(meta_path) != hashes['metadata'] or select_tables(directory, m, events, part) != tables:
                        raise BidsExportError('导出期间源记录发生变化；请等采集保存结束后重试。')
                    destination.mkdir(parents=True, exist_ok=True)
                    for path in stage.iterdir():
                        if (destination/path.name).exists():
                            raise BidsExportError('存在未完成或冲突的同名导出，原件未覆盖，请另选输出目录。')
                    output_hashes = {str((destination/path.name).relative_to(output)).replace('\\','/'): digest(path) for path in stage.iterdir()}
                    # Dataset lock prevents competing writers; publish receipt last.
                    for path in list(stage.iterdir()):
                        path.rename(destination/path.name)
                    stage.rmdir()
                    participants = output/'participants.tsv'
                    ids = set()
                    if participants.exists():
                        with participants.open(encoding='utf-8', newline='') as f:
                            ids = {r['participant_id'] for r in csv.DictReader(f, delimiter='\t')}
                    ids.add('sub-'+subject)
                    temp = output/('.participants-'+uuid4().hex+'.tmp')
                    write_tsv(temp, [{'participant_id': x} for x in sorted(ids)], ('participant_id',))
                    temp.replace(participants)
                    receipt = {'exporter_version': VERSION, 'source_hashes': hashes, 'output_hashes': output_hashes,
                               'source_recording': directory.name, 'source_part': part,
                               'source_event_count': len(events), 'exported_event_rows': len(rows),
                               'behavior_table_rows': {name: len(value) for name, value in tables.items()},
                               'quality_flags': quality, 'official_validation': 'NOT_RUN', 'source_unchanged': True}
                    write_json(receipt_path, receipt)
                    results.append({'status': 'EXPORTED', 'prefix': prefix, 'quality_flags': quality})
                except Exception:
                    # Keep an interrupted stage for diagnosis; never remove source/unknown files.
                    raise
            finally:
                if getattr(data, '_mmap', None) is not None:
                    data._mmap.close()
    return {'output': str(output), 'recordings': results, 'official_validation': 'NOT_RUN'}


def after_recording(directory, config):
    if config.get('device_type') == 'emotivpro' and not config.get('hardware_dummy_mode'):
        return ('行为与标记日志已保存；脑电由 EmotivPRO 保存。请停止录制并导出 EDF，'
                '回到控制台登记外部 EEG 后再评分。不套用 BrainCo 通道/量程导出。')
    """Failure-isolated hook called only after acquisition and raw export stop."""
    if config.get('demo_mode') or config.get('hardware_dummy_mode'):
        return 'Demo模拟记录已保存；不混入正式BIDS。'
    protocol = config.get('_unified_protocol')
    if protocol not in ('v1', 'v2') or config.get('bids', {}).get('enabled', True) is False:
        return '原始记录已保存；可使用独立BIDS导出入口。'
    source_root = Path(config.get('storage', {}).get('source_data_root') or ROOT/'data/sourcedata')
    if not source_root.is_absolute():
        source_root = ROOT/source_root
    output = Path(config.get('bids', {}).get('output_root') or source_root.parent/'bids')/protocol
    try:
        result = export_recording(directory, output, protocol=protocol)
        flags = sum(len(r['quality_flags']) for r in result['recordings'])
        text = f'BIDS副本已生成：{output}\n原始数据和进度保留。官方格式校验请用BIDS导出入口。'
        if flags:
            text += f'\n有{flags}项时序质量标记，分析前须核对。'
        return text
    except Exception as exc:
        print('BIDS_EXPORT_PENDING: '+str(exc), flush=True)
        return '原始数据已保存；BIDS导出未完成，可稍后重试。\n原因：'+str(exc)


def validate_dataset(output):
    """Use the compiled official validator, never silently claim validation."""
    try:
        from deno import find_deno_bin
        import bids_validator_deno
        bundle = Path(bids_validator_deno.__file__).parent/'bids-validator.js'
        executable = os.fsdecode(find_deno_bin())
    except ImportError as exc:
        raise BidsExportError('缺少离线官方BIDS校验器；文件已导出，尚未完成官方校验。') from exc
    command = [executable, '--no-prompt', '--allow-read', '--allow-env', '--allow-sys=osRelease',
               str(bundle), str(output), '--format', 'json', '--max-rows', '-1']
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=600,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        report = json.loads(result.stdout)
    except ValueError as exc:
        raise BidsExportError('官方校验器未返回可识别报告：'+result.stderr[-500:]) from exc
    issues = report.get('issues', {}).get('issues')
    if not isinstance(issues, list):
        raise BidsExportError('官方校验报告格式不完整，不能判定通过。')
    errors = sum(i.get('severity') == 'error' for i in issues)
    warnings = sum(i.get('severity') == 'warning' for i in issues)
    write_json(Path(output)/'code/validation_report.json', report)
    if errors or result.returncode:
        raise BidsExportError(f'官方校验未通过：{errors}个错误，{warnings}个警告；见code/validation_report.json。')
    return {'errors': errors, 'warnings': warnings, 'official_validation': 'PASSED'}
