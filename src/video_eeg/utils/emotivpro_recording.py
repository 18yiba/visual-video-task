"""External recording evidence, explicitly confirmed by the operator, not telemetry."""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import time


def configure(config, port=''):
    config['device_type'] = 'emotivpro'
    device = dict(config.get('device', {}))
    device.update(emotivpro_serial_port=port, emotivpro_baudrate=115200)
    config['device'] = device


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _receipt_path(metadata_path):
    return metadata_path.with_name('emotivpro_confirmation_' + metadata_path.name)


def confirm_recording(metadata_path, eeg_path, *, operator_confirmed=False):
    if not operator_confirmed:
        raise ValueError('须主试确认导出的 EEG 属于该被试、本 Session 和本次采集，且包含完整起止标记。')
    metadata_path, eeg_path = Path(metadata_path).resolve(), Path(eeg_path).resolve()
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    if metadata.get('eeg_recording_mode') != 'emotivpro_external' or not metadata.get('recording_uuid'):
        raise ValueError('该记录不是 EmotivPRO 外部录制。')
    if (metadata.get('serial_write_error') or metadata.get('startup_error')
            or metadata.get('background_error')
            or metadata.get('external_environment_guard', {}).get('error')):
        raise ValueError('本段发生标记或录制环境故障，需人工审计，不能直接登记为完整采集。')
    if eeg_path.suffix.lower() != '.edf' or not eeg_path.is_file():
        raise ValueError('请选择 EmotivPRO 导出的实际 EDF 脑电文件。')
    import edfio
    eeg = edfio.read_edf(eeg_path, lazy_load_data=True)
    if not eeg.signals or not math.isfinite(eeg.duration) or eeg.duration <= 0:
        raise ValueError('EDF 没有有效信号或采集时长。')
    stat = eeg_path.stat()
    receipt = dict(recording_uuid=metadata['recording_uuid'], eeg_part=metadata['eeg_part'],
        subject_id=metadata.get('subject_id'), session_id=metadata.get('session_id'),
        eeg_file=str(eeg_path), bytes=stat.st_size, mtime_ns=stat.st_mtime_ns,
        sha256=_sha256(eeg_path), metadata_sha256=_sha256(metadata_path),
        confirmed_at_unix_sec=time.time(), operator_confirmed=True,
        confirmation_basis='operator reviewed subject/session, full recording and markers; file is readable EDF',
        marker_alignment_automatically_verified=False, signal_quality_verified=False)
    if (eeg_path.stat().st_size, eeg_path.stat().st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
        raise ValueError('EDF 正在变化，请导出完成后重新登记。')
    target = _receipt_path(metadata_path)
    if target.exists():
        existing = json.loads(target.read_text(encoding='utf-8'))
        if existing.get('sha256') == receipt['sha256'] and existing.get('eeg_file') == str(eeg_path):
            return target
        raise ValueError('已有不同的外部 EEG 登记，请先人工核对，不覆盖原回执。')
    with target.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    return target


@lru_cache(maxsize=64)
def _checked_file(path, size, modified_ns, expected_hash):
    return _sha256(Path(path)) == expected_hash


def external_eeg_saved(attempt):
    row = attempt.get('emotion_rating', {})
    if not attempt.get('video_completed_naturally') or row.get('eeg_recording_mode') != 'emotivpro_external':
        return False
    onset, offset = row.get('video_onset_unix_sec'), row.get('video_offset_unix_sec')
    if not isinstance(onset, (int, float)) or not isinstance(offset, (int, float)) or not math.isfinite(offset-onset) or offset <= onset:
        return False
    directory = row.get('eeg_recording_dir')
    if not directory:
        return False
    for path in Path(directory).glob('metadata*.json'):
        try:
            metadata = json.loads(path.read_text(encoding='utf-8'))
            if metadata.get('eeg_part') != row.get('eeg_part') or metadata.get('eeg_recording_mode') != 'emotivpro_external':
                continue
            if (metadata.get('background_error') or metadata.get('serial_write_error')
                    or metadata.get('external_environment_guard', {}).get('error')):
                continue
            receipt = json.loads(_receipt_path(path).read_text(encoding='utf-8'))
            if not receipt.get('operator_confirmed') or receipt['recording_uuid'] != metadata['recording_uuid'] or receipt['eeg_part'] != row['eeg_part']:
                continue
            if receipt['metadata_sha256'] != _sha256(path):
                continue
            eeg_path = Path(receipt['eeg_file']); stat = eeg_path.stat()
            if stat.st_size != receipt['bytes'] or stat.st_mtime_ns != receipt['mtime_ns']:
                continue
            if _checked_file(str(eeg_path), stat.st_size, stat.st_mtime_ns, receipt['sha256']):
                return True
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return False


def confirm_session_dialog(parent, session_dir):
    from psychopy.gui import qtgui
    W = qtgui.QtWidgets
    pending = []
    for path in sorted(session_dir.glob('*/metadata*.json')):
        metadata = json.loads(path.read_text(encoding='utf-8'))
        if metadata.get('eeg_recording_mode') == 'emotivpro_external' and not _receipt_path(path).exists():
            pending.append((path, metadata))
    if not pending:
        W.QMessageBox.information(parent, '外部 EEG', '当前 Session 没有待登记的 EmotivPRO 采集段。')
        return
    for path, metadata in pending:
        description = (f"被试 {metadata.get('subject_id')} / Session {metadata.get('session_id')}\n"
            f"本段 {path.parent.name} / part {metadata.get('eeg_part')}\n"
            f"开始：{metadata.get('recording_started_at')}\n结束：{metadata.get('recording_ended_at')}")
        filename, _ = W.QFileDialog.getOpenFileName(parent, '选择对应的 EmotivPRO EDF：'+path.parent.name,
                                                   str(session_dir), 'EDF 脑电 (*.edf *.EDF)')
        if not filename:
            return
        choice = W.QMessageBox.question(parent, '人工核对外部录制', description+
            '\n\n请在 EmotivPRO/导出记录中核对：被试与 Session 一致，本段所有完整观看视频都有脑电和对应起止标记。'
            '\n程序仅检查 EDF 可读性，不能自动验证标记对齐或信号质量。\n确认上述条件并登记所选文件？',
            W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.No, W.QMessageBox.StandardButton.No)
        if choice != W.QMessageBox.StandardButton.Yes:
            return
        confirm_recording(path, filename, operator_confirmed=True)
