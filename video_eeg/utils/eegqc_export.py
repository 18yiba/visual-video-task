"""Company EEGQC handoff: one sealed EDF/BIDS dataset per continuous recording.

Native recordings are read-only. Configuration/identity omissions fail explicitly;
no platform identity, device range, hardware timing or quality score is inferred.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import numpy as np

from . import bids_export as b

SPEC_URL = 'https://omni-intel.feishu.cn/docx/KrHNd7XgZomAJMxuks8cNonQnwq'
EXPORT_REVISION = 'eegqc-handoff-1'
DEFAULT_PARADIGM_CODES = {
    'v1': 'AVEEG-20260923',
    'v2': 'AVEEG-20260923',
    'v3': 'EMOVID-20261008',
    'v3_emotion_only': 'EMOVID-20261008',
}
FIELDS = ('onset', 'duration', 'trial_type', 'stimulus_id', 'trial_id',
          'sample_index', 'trigger_value', 'completed', 'timing_source',
          'source_trial_id', 'source_event_name', 'source_event_index', *[k for k in b.COLUMNS
          if k not in {'onset', 'duration', 'trial_type', 'trial_id', 'completed'}])


def load_settings(path=None):
    path = Path(path) if path else b.ROOT/'eegqc.local.json'
    if not path.is_file():
        raise b.BidsExportError('缺少 EEGQC 本机配置；请提供平台范式代码、被试映射及设备量程：'+str(path))
    return b.read_json(b.no_links(path))


def identity_for(m, protocol, settings):
    if protocol not in ('v1', 'v2', 'v3'):
        raise b.BidsExportError('必须指定原协议v1、v2或v3。')
    if m.get('demo_mode') or m.get('eeg_mode') == 'dummy' or m.get('device_type') == 'dummy':
        raise b.BidsExportError('Demo模拟数据不能作为正式交接包。')
    if not m.get('local_eeg_recorded', True):
        raise b.BidsExportError('外部录制缺少本地真实EEG，不能生成交接包。')
    if protocol == 'v1':
        kinds = {r.get('task_type') for r in m.get('attention_schedule', [])}
        if m.get('num_sessions') != 17 or kinds != {'video_mcq'}:
            raise b.BidsExportError('源记录不是17组内容题v1。')
    elif protocol == 'v3':
        if m.get('num_sessions') != 45 or m.get('protocol_version') != 'emotion-v3':
            raise b.BidsExportError('源记录不是45组emotion-v3。')
    elif m.get('num_sessions') != 45 or m.get('protocol_version') not in (None, 'emotion-v2'):
        raise b.BidsExportError('源记录不是45组emotion-v2。')
    source_id = m.get('subject_id')
    mapping = settings.get('participant_map', {}).get(protocol, {})
    participant = m.get('platform_participant_id') or mapping.get(str(source_id), source_id)
    if not isinstance(participant, str) or not re.fullmatch(r'[0-9]{8}', participant):
        raise b.BidsExportError('需要平台8位字符串被试编号或显式映射；不补零、不转换原编号。')
    # The approved production code is part of the protocol contract.  A local
    # setting may only replace it when the platform owner explicitly changes it.
    scope = 'v3_emotion_only' if protocol == 'v3' and m.get('emotion_video_scope') == 'emotion_only' else protocol
    code = m.get('paradigm_code') if protocol == 'v3' else None
    code = code or settings.get('paradigm_codes', {}).get(scope) or DEFAULT_PARADIGM_CODES.get(scope)
    if not isinstance(code, str) or not code.strip() or code != code.strip():
        raise b.BidsExportError('缺少已确认的平台范式代码：'+protocol)
    return participant, code


def recording_id(directory, m, protocol):
    if m.get('recording_uuid'):
        try:
            return UUID(str(m['recording_uuid'])).hex, 'acquisition_uuid'
        except ValueError as exc:
            raise b.BidsExportError('源 recording_uuid 无效。') from exc
    # Legacy copies/retries retain identity without writing into the source.
    stamp, _ = b.stamp_of(directory, m)
    key = [protocol, m.get('subject_id'), m.get('session_id'), stamp, m.get('eeg_part', 1)]
    return uuid5(NAMESPACE_URL, 'visual-video-task/legacy/'+json.dumps(key)).hex, 'legacy_deterministic_uuid5'


def v3_capture_identity(config):
    local = Path(config.get('eegqc_config_path') or b.ROOT/'eegqc.local.json')
    settings = config.get('eegqc') or (load_settings(local) if local.is_file() else {})
    metadata = dict(subject_id=config['subject_id'], num_sessions=45, protocol_version='emotion-v3',
        paradigm_code=config.get('paradigm_code'),
        emotion_video_scope='emotion_only' if config['protocol'].get('emotion_only') else 'all')
    return identity_for(metadata, 'v3', settings)


def parse_time(value, field):
    try:
        dt = datetime.fromisoformat(value)
        if dt.utcoffset() is None:
            raise ValueError('timezone missing')
        return dt
    except (TypeError, ValueError) as exc:
        raise b.BidsExportError('缺少带时区的已核实 '+field+'；旧记录请在 recording_times 中提供，不猜测。') from exc


def recording_times(m, rid, settings):
    override = settings.get('recording_times', {}).get(rid, {})
    start = parse_time(m.get('recording_started_at') or override.get('started_at'), f'started_at (UUID {rid})')
    end = parse_time(m.get('recording_ended_at') or override.get('ended_at'), f'ended_at (UUID {rid})')
    if end < start:
        raise b.BidsExportError('结束时间早于开始时间。')
    return start, end, m.get('recording_clock_basis') or override.get('clock_basis', 'operator_verified_legacy_times')


def device_profile(m, data, settings):
    p = b.profile_for(m, data.shape[0])
    if m.get('eeg_format') == 'EDF':
        # Acquisition-time snapshot is authoritative; later local settings must
        # not relabel or requantize a saved native EDF.
        return p
    device = settings.get('device', {})
    if not device.get('model') or not device.get('confirmation'):
        raise b.BidsExportError('缺少已确认的设备型号和配置来源。')
    ranges = device.get('physical_ranges_uv')
    if not isinstance(ranges, dict) or set(ranges) != set(p['channel_names']):
        raise b.BidsExportError('须提供每个已确认EEG通道的物理量程 physical_ranges_uv。')
    if device.get('software_filters') is None:
        raise b.BidsExportError('须确认采集软件滤波设置；未知请明确写 n/a。')
    for name, bounds in ranges.items():
        if (not isinstance(bounds, list) or len(bounds) != 2 or
                any(b.number(v) is None for v in bounds) or float(bounds[0]) >= float(bounds[1])):
            raise b.BidsExportError('无效物理量程：'+name)
    allowed = {'model', 'confirmation', 'software_filters', 'physical_ranges_uv'}
    if set(device)-allowed:
        raise b.BidsExportError('device包含未经适配的字段，不覆盖已确认的通道/单位配置。')
    return dict(p, **device)


def company_events(events, tables, n_samples, sf, rid):
    rows, quality = b.build_events(events, tables, n_samples, sf)
    # Keep all raw event and behavior details; only onset rows represent stimuli.
    for index, row in enumerate(rows):
        row.update(source_trial_id=row.get('trial_id'), source_event_name=row['trial_type'],
                   stimulus_id=row.get('video_id'), sample_index=row.get('sample'),
                   trigger_value=None, completed=None, timing_source='software_timestamp',
                   trial_id=rid+f'e{index:06d}')
        if row['sample_index'] == n_samples:
            row['sample_index'] = None
        source_index = row.get('source_event_index')
        event = events[source_index] if source_index is not None else None
        if event is None:
            row['trial_type'] = 'behavior_summary'
            continue
        name, payload = event.get('name'), event.get('payload') or {}
        if payload.get('external_marker_sent') is True and payload.get('marker_send_success') is True:
            row['trigger_value'] = payload.get('marker_code')
        if name not in b.PAIRS:
            row['trial_type'] = 'marker'
            continue
        off = None
        for candidate in events[source_index+1:]:
            if candidate.get('name') == name and b.same_trial(event, candidate):
                break
            if candidate.get('name') == b.PAIRS[name] and b.same_trial(event, candidate):
                off = candidate
                break
        row['trial_type'] = ('video' if name in ('video_on', 'EMOTION_VIDEO_ONSET') else
                             'rest' if name in ('break_start', 'SHORT_REST_ONSET', 'rest_start') else
                             'fixation' if name == 'fixation_on' else 'response_page')
        if off is None:
            row['completed'] = 0
            row['duration'] = None
            continue
        op = off.get('payload') or {}
        row['completed'] = (int(op['completed_naturally']) if isinstance(op.get('completed_naturally'), bool)
                            else int(op['completed']) if isinstance(op.get('completed'), bool) else None)
        if row['trial_type'] == 'video' and (op.get('skipped') or op.get('abort_reason') or op.get('status') == 'aborted'):
            row['completed'] = 0
        # Actual presentation interval comes from the software clock, never planned duration.
        on_time, off_time = b.number(event.get('relative_time_sec')), b.number(off.get('relative_time_sec'))
        row['duration'] = off_time-on_time if None not in (on_time, off_time) and off_time >= on_time else None
        if not row['eeg_available']:
            row['onset'] = row['sample_index'] = None
    return rows, quality


def write_edf(path, data, sf, profile, start, participant):
    import edfio
    if not float(sf).is_integer():
        raise b.BidsExportError('当前EDF写入仅验证整数采样率；不重采样。')
    # Exactly preserve arbitrary sample counts, including subsecond final records.
    record_duration = math.gcd(data.shape[1], int(sf))/sf
    signals, quantization = [], {}
    for i, name in enumerate(profile['channel_names'], 1):
        values = np.asarray(data[i], dtype=np.float64)
        low, high = map(float, profile['physical_ranges_uv'][name])
        if not np.isfinite(values).all() or values.min() < low or values.max() > high:
            raise b.BidsExportError('EEG非有限数或超出已确认量程：'+name+'；不截幅、不补零。')
        signal = edfio.EdfSignal(values, sf, label=name, physical_dimension='uV', physical_range=(low, high))
        signals.append(signal)
        quantization[name] = (signal.physical_max-signal.physical_min)/65535
    edf = edfio.Edf(signals, patient=edfio.Patient(code=participant),
                    recording=edfio.Recording(startdate=start.date()),
                    starttime=start.time().replace(tzinfo=None, microsecond=0),
                    data_record_duration=record_duration)
    with path.open('xb') as handle:
        edf.write(handle)
    return quantization


def _hash_value(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def selected_tables(directory, metadata, events, part, protocol):
    tables = b.select_tables(directory, metadata, events, part,
        ignore_tables=('emotion_rating_log.csv',) if protocol == 'v3' else ())
    if protocol == 'v3':
        # Independent behavior replay has no EEG; never attach it to the earlier
        # acquisition, or allow later ratings to change a sealed package's hash.
        tables.pop('emotion_rating_log.csv', None)
    return tables


def export_recording(directory, output, *, protocol, settings, validate=False):
    directory, output = b.no_links(directory), b.no_links(output)
    if directory.is_relative_to(output) or output.is_relative_to(directory):
        raise b.BidsExportError('交接输出必须独立于原始采集目录。')
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with b.dataset_lock(output):
        for meta_path in b.recording_files(directory):
            m = b.read_json(meta_path)
            participant, code = identity_for(m, protocol, settings)
            rid, origin = recording_id(directory, m, protocol)
            start, end, clock = recording_times(m, rid, settings)
            part = int(m.get('eeg_part', 1))
            if part < 1 or m.get('sample_index_origin', 'segment_local') != 'segment_local':
                raise b.BidsExportError('采集段编号或样本坐标无效。')
            def source_file(key, fallback):
                if part > 1 and not m.get(key):
                    raise b.BidsExportError('多段记录缺少显式源文件名：'+key)
                name = m.get(key) or fallback
                if not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name:
                    raise b.BidsExportError('源文件必须位于采集目录内。')
                return b.no_links(directory/name)
            eeg_path = source_file('eeg_file', 'continuous_eeg.npy')
            event_path = source_file('events_file', 'events.json')
            data = b.load_signal(eeg_path, m)
            try:
                if data.ndim != 2 or data.shape[1] < 1 or (m.get('eeg_format') != 'EDF' and data.dtype != np.dtype('float32')):
                    raise b.BidsExportError('EEG须为非空通道×样本float32数组。')
                if m.get('n_channels', data.shape[0]) != data.shape[0] or m.get('sample_count', data.shape[1]) != data.shape[1]:
                    raise b.BidsExportError('metadata通道数/样本数与数组不符。')
                sf = b.number(m.get('sfreq'))
                if sf is None or sf <= 0:
                    raise b.BidsExportError('缺少真实采样率。')
                profile = device_profile(m, data, settings)
                if profile.get('sample_counter_row') == 0:
                    counter = np.asarray(data[0, :min(data.shape[1], 500000)], dtype='float64')
                    if np.mean(np.diff(counter) == 1) < .95:
                        raise b.BidsExportError('首行计数验证失败。')
                    for offset in range(0, data.shape[1]-1, 500000):
                        counters = np.asarray(data[0, offset:min(offset+500001, data.shape[1])], dtype='float64')
                        if not np.all(np.diff(counters) == 1):
                            raise b.BidsExportError('样本计数存在跳变/重复；未把可能断段的信号标为连续。请核实计数回绕规则或另行审计分段。')
                events = b.read_json(event_path)
                if not isinstance(events, list):
                    raise b.BidsExportError('events.json须为列表。')
                tables = selected_tables(directory, m, events, part, protocol)
                rows, quality = company_events(events, tables, data.shape[1], sf, rid)
                hashes = {p.name: b.digest(p) for p in (meta_path, eeg_path, event_path)}
                contract = dict(protocol=protocol, participant=participant, paradigm_code=code, profile=profile,
                                start=start.isoformat(), end=end.isoformat(), revision=EXPORT_REVISION)
                hashes.update(selected_behavior=_hash_value(tables), contract=_hash_value(contract))
                destination = b.no_links(output/('recording-'+rid))
                receipt_path = destination/'code/export_receipt.json'
                if destination.exists():
                    if not receipt_path.is_file():
                        raise b.BidsExportError('已有同UUID目录未封存，不覆盖：'+str(destination))
                    receipt = b.read_json(receipt_path)
                    if receipt['source_hashes'] != hashes:
                        raise b.BidsExportError('同UUID源记录或导出配置变化，不覆盖历史交接包。')
                    for name, checksum in receipt['output_hashes'].items():
                        path = b.no_links(destination/name)
                        if not path.is_relative_to(destination) or not path.is_file() or b.digest(path) != checksum:
                            raise b.BidsExportError('已封存交接文件被修改或缺失。')
                    if len(list(destination.rglob('*.edf'))) != 1 or list(destination.rglob('*.float32')):
                        raise b.BidsExportError('交接包必须只有一段主EDF记录，发现额外信号文件。')
                    result = dict(status='EXISTS_VERIFIED', output=str(destination), recording_uuid=rid, quality_flags=quality)
                else:
                    stage = output/('.stage-'+rid+'-'+uuid4().hex)
                    eeg_dir = stage/f'sub-{participant}'/f'ses-{rid}'/'eeg'
                    eeg_dir.mkdir(parents=True)
                    prefix = f'sub-{participant}_ses-{rid}_task-video{protocol}_run-01'
                    if shutil.disk_usage(output).free < data.size*2+64*1024*1024:
                        raise b.BidsExportError('磁盘空间不足。')
                    if m.get('eeg_format') == 'EDF':
                        shutil.copyfile(eeg_path, eeg_dir/(prefix+'_eeg.edf'))
                        step = m['edf_quantization_step_uv']
                    else:
                        step = write_edf(eeg_dir/(prefix+'_eeg.edf'), data, sf, profile, start, participant)
                    b.write_json(stage/'dataset_description.json', {'Name': 'Video EEG '+protocol+' recording '+rid,
                        'BIDSVersion': '1.11.1', 'DatasetType': 'raw', 'GeneratedBy': [{'Name': 'visual-video-task', 'Version': b.VERSION}]})
                    (stage/'.bidsignore').write_text('**/session.json\n', encoding='utf-8')
                    b.write_tsv(stage/'participants.tsv', [{'participant_id': 'sub-'+participant}], ('participant_id',))
                    b.write_json(stage/'participants.json', {'participant_id': {'Description': 'Existing 8-digit personnel-platform identifier; leading zeros preserved.'}})
                    reason = m.get('termination_reason', 'unknown')
                    status = 'complete' if reason in ('completed', 'esc_emergency', 'rest_exit') else 'interrupted' if reason in ('eeg_background_error', 'python_exception', 'incomplete') else 'unknown'
                    stop_reason = {'completed': 'planned_end', 'esc_emergency': 'operator_stop',
                                   'rest_exit': 'operator_stop', 'eeg_background_error': 'acquisition_error',
                                   'python_exception': 'application_error'}.get(reason, reason)
                    b.write_json(eeg_dir.parent/'session.json', dict(schema_version=1, participant_id=participant,
                        session_id=rid, paradigm_code=code, started_at=start.isoformat(), ended_at=end.isoformat(),
                        recording_status=status, stop_reason=stop_reason, source_termination_reason=reason,
                        acquisition_software={'name': 'visual-video-task', 'version': m.get('acquisition_software_version', 'unknown')},
                        source_protocol=m.get('protocol_version') or protocol, source_session_number=m.get('session_id'),
                        source_video_scope=m.get('emotion_video_scope', 'all'),
                        source_part=part, uuid_origin=origin, clock_basis=clock))
                    b.write_tsv(eeg_dir/(prefix+'_events.tsv'), rows, FIELDS)
                    descriptions = {key: {'Description': 'Preserved source variable: '+key} for key in FIELDS}
                    descriptions.update(onset={'Description': 'Seconds from first stored sample using software-observed sample count; n/a if unavailable.', 'Units': 's'},
                        duration={'Description': 'Actual software presentation interval, never planned length; n/a for unknown offset.', 'Units': 's'},
                        trial_id={'Description': 'Unique exported occurrence identifier; original trial and attempt remain in source fields.'},
                        stimulus_id={'Description': 'Stable original material identifier, not ordinal position.'},
                        sample_index={'Description': 'Zero-based stored sample position, n/a if unavailable or one-past-end.'},
                        completed={'Description': 'Stimulus natural completion: 1; interrupted: 0; unknown/not applicable: n/a.'},
                        timing_source={'Description': 'software_timestamp: software-observed sample count and presentation clock; hardware latency not calibrated.'},
                        trigger_value={'Description': 'Actually sent marker code only on confirmed successful external send; otherwise n/a.'},
                        source_details={'Description': 'Original event payload or behavior row, including source clocks and trigger send times.'})
                    b.write_json(eeg_dir/(prefix+'_events.json'), descriptions)
                    b.write_tsv(eeg_dir/(prefix+'_channels.tsv'), [{'name': n, 'type': 'EEG', 'units': 'uV', 'sampling_frequency': sf} for n in profile['channel_names']], ('name', 'type', 'units', 'sampling_frequency'))
                    b.write_json(eeg_dir/(prefix+'_eeg.json'), dict(TaskName='video'+protocol, SamplingFrequency=sf,
                        PowerLineFrequency=profile['power_line_frequency'], EEGReference=profile['reference'],
                        SoftwareFilters=profile['software_filters'], Manufacturer=profile['manufacturer'],
                        ManufacturersModelName=profile['model'], EEGChannelCount=len(profile['channel_names']),
                        EOGChannelCount=0, ECGChannelCount=0, EMGChannelCount=0, MiscChannelCount=0, TriggerChannelCount=0,
                        RecordingType='continuous', RecordingDuration=data.shape[1]/sf, HardwareClockCalibrated=False,
                        EDFQuantizationStepMicrovolts=step, SourceSampleCounterRow=profile.get('sample_counter_row'), SourceClockBasis=clock,
                        SourceProfileConfirmation=profile['confirmation']))
                    (stage/'README').write_text('One continuous recording per package. Native NPY, event JSON and recovery state remain outside this package.\nEDF uses 16-bit quantization at the confirmed physical ranges; no resampling, padding or clipping.\nNo EEG quality pass, usable duration or platform import success is asserted.\nSelect the correct paradigm manually in EEGQC; paradigm_code auto-detection is not yet supported by the specified client.\nSpecification: '+SPEC_URL+'\n', encoding='utf-8')
                    if any(b.digest(p) != hashes[p.name] for p in (meta_path, eeg_path, event_path)) or selected_tables(directory, m, events, part, protocol) != tables:
                        raise b.BidsExportError('导出期间原记录发生变化，未封存。')
                    output_hashes = {p.relative_to(stage).as_posix(): b.digest(p) for p in stage.rglob('*') if p.is_file()}
                    b.write_json(stage/'code/export_receipt.json', dict(source_hashes=hashes, output_hashes=output_hashes,
                        quality_flags=quality, source_unchanged=True, official_validation='NOT_RUN', export_revision=EXPORT_REVISION))
                    stage.rename(destination)  # complete dataset appears as a unit; interrupted stages retained
                    result = dict(status='EXPORTED', output=str(destination), recording_uuid=rid, quality_flags=quality)
                result['official_validation'] = 'NOT_RUN'
                if validate:
                    status_path = destination/'code/validation_status.json'
                    b.write_json(status_path, {'official_validation': 'RUNNING'})
                    try:
                        result['official_validation'] = b.validate_dataset(destination)
                    except Exception as exc:
                        b.write_json(status_path, {'official_validation': 'FAILED', 'error': str(exc)})
                        raise
                    b.write_json(status_path, result['official_validation'])
                results.append(result)
            finally:
                if getattr(data, '_mmap', None) is not None:
                    data._mmap.close()
    if not results:
        raise b.BidsExportError('没有已保存的metadata记录。')
    return {'output': str(output), 'recordings': results}


def after_recording(directory, config):
    if config.get('demo_mode') or config.get('hardware_dummy_mode'):
        return 'Demo模拟记录已保存；不生成正式EEGQC交接包。'
    try:
        protocol = 'v3' if config.get('protocol', {}).get('separate_emotion_ratings') else config.get('_unified_protocol')
        local = Path(config.get('eegqc_config_path') or b.ROOT/'eegqc.local.json')
        settings = config.get('eegqc') or (load_settings(local) if local.is_file() else {} if protocol == 'v3' else load_settings(local))
        source_root = Path(config.get('storage', {}).get('source_data_root') or b.ROOT/'data/sourcedata')
        if not source_root.is_absolute():
            source_root = b.ROOT/source_root
        output = Path(settings.get('output_root') or source_root.parent/'eegqc')
        result = export_recording(directory, output, protocol=protocol, settings=settings, validate=True)
        return f'EEGQC交接包已导出并完成官方格式校验：{output}\n共{len(result["recordings"])}段；须在EEGQC人工确认范式并评分，未上传入库。'
    except Exception as exc:
        return '原始记录已保存；EEGQC交接待完成，可稍后重试。\n原因：'+str(exc)
