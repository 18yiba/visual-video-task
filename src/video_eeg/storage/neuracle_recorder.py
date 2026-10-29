"""Neuracle-only bounded asynchronous spool; the writer owns its open files."""
from datetime import datetime
import json
import os
import queue
import threading
import time

import numpy as np

from video_eeg.storage.session_recorder import SessionRecorder
from video_eeg.storage.neuracle_saved_trigger import verify_saved_triggers


class NeuracleSessionRecorder(SessionRecorder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._queue = queue.Queue(maxsize=256)
        self._admission = threading.Lock()
        self._writer_stop = threading.Event()
        self._writer_done = threading.Event()
        self._writer = None
        self._saved_count = 0
        self._write_error = None
        self._write_timeout = 10.0
        self._stop_timeout = 30.0
        self._backlog_samples = max(1, int(self._sfreq*5))
        self._write_started = None
        self._max_depth = 0
        self._trace_file = None
        self.validation_error = None
        self._directory = None
        self._raw_handle = None
        self._raw_ratio = 1
        self._raw_saved_count = 0
        self._raw_path = None
        self._forwarding = {}

    @property
    def _uses_edf(self):
        return True

    def _edf_identity_metadata(self):
        from video_eeg.storage.neuracle_edf import profile
        return dict(eeg_format='EDF', native_edf_profile=profile(self._forwarding),
                    sfreq=self._sfreq, n_channels=self._n_channels,
                    simulated_eeg=False, sample_values='forwarded values without scaling',
                    units_verified=False)

    def _write_edf(self, path, data):
        from video_eeg.storage.neuracle_edf import write_edf
        return write_edf(path, data, self._sfreq, self._recording_started_at,
                         self._edf_identity_metadata()['native_edf_profile'])

    def _edf_export_metadata(self, quantization):
        from video_eeg.storage.neuracle_edf import profile
        return dict(eeg_format='EDF', native_edf_profile=profile(self._forwarding),
                    edf_quantization_details=quantization,
                    sample_values='forwarded values without scaling', units_verified=False,
                    simulated_eeg=False)

    def start_spooling(self, output_dir):
        recording_metadata = self._acquirer.recording_metadata()
        self._forwarding = recording_metadata.get('neuracle_forwarding', {})
        self._mapping = self._forwarding.get('trigger_mapping', {})
        self._raw_ratio = self._mapping.get('ratio', 1)
        super().start_spooling(output_dir)
        self._directory = output_dir
        try:
            if self._raw_ratio>1:
                self._raw_path=output_dir/f'trg_raw_part_{self.part_index:03d}.f32'
                self._raw_handle=self._raw_path.open('xb')
            self._trace_file = (output_dir/f'neuracle_write_part_{self.part_index:03d}.jsonl').open('x', encoding='utf-8')
            self._writer = threading.Thread(target=self._write_loop, name='neuracle-spool-writer', daemon=True)
            self._writer.start()
        except Exception:
            if self._raw_handle is not None:self._raw_handle.close()
            if self._trace_file is not None: self._trace_file.close()
            if self._spool_handle is not None: self._spool_handle.close()
            raise

    def pull(self):
        self.check_health()
        samples, _ = self._acquirer.get_new_samples()
        if samples.ndim != 2 or samples.shape[0] != self._n_channels:
            raise RuntimeError(f'Neuracle unexpected sample shape: {samples.shape}')
        raw=None
        if self._raw_ratio>1:
            raw=self._acquirer.take_raw_trigger()
            if raw is None or raw.shape!=(samples.shape[1]*self._raw_ratio,):
                raise RuntimeError('Neuracle raw TRG and EEG sample count mismatch')
            raw=np.array(raw,dtype='<f4',copy=True)
        if not samples.shape[1]: return samples
        with self._admission:
            if self._frozen: return np.empty((self._n_channels, 0), np.float32)
            count = int(samples.shape[1])
            if self._sample_count-self._saved_count+count > self._backlog_samples:
                self._fail('write_backlog_full: more than 5 seconds of EEG pending')
                raise RuntimeError(self._write_error)
            block = np.array(samples, dtype=np.float32, copy=True, order='C')
            try:
                self._queue.put_nowait((block, raw, self._sample_count, time.monotonic()))
            except queue.Full as exc:
                self._fail('write_queue_full: 256 EEG blocks pending')
                raise RuntimeError(self._write_error) from exc
            self._sample_count += count
            self._max_depth = max(self._max_depth, self._queue.qsize())
        return block

    def freeze(self):
        # This lock never covers disk I/O. Health checks can freeze a stalled writer.
        with self._admission:
            self._frozen = True
            if self._recording_ended_at is None:
                self._recording_ended_at = datetime.now().astimezone().isoformat()

    def _fail(self, detail):
        if self._write_error is None: self._write_error = str(detail)
        self._writer_stop.set()

    def check_health(self):
        if self._write_started is not None and time.monotonic()-self._write_started > self._write_timeout:
            self._fail('write_stalled: disk operation exceeded 10 seconds')
        if self._writer is not None and not self._writer.is_alive() and not self._writer_stop.is_set():
            self._fail('write_thread_exited_unexpectedly')
        if self._write_error: raise RuntimeError('Neuracle save/write failed: '+self._write_error)

    def writer_metadata(self):
        return dict(received_samples=self._sample_count, saved_samples=self._saved_count,
                    saved_raw_trigger_samples=self._raw_saved_count, trigger_ratio=self._raw_ratio,
                    queue_depth=self._queue.qsize(), max_queue_depth=self._max_depth,
                    queue_max_blocks=256, backlog_limit_samples=self._backlog_samples,
                    error=self._write_error, finalized=self._writer_done.is_set())

    def _trace(self, event, **fields):
        self._trace_file.write(json.dumps(dict(event=event, unix_sec=time.time(),
            monotonic_sec=time.monotonic(), **self.writer_metadata(), **fields))+'\n')
        self._trace_file.flush()

    def _write_loop(self):
        try:
            self._trace('writer_started')
            while not self._writer_stop.is_set() or not self._queue.empty():
                try: block, raw, first, queued = self._queue.get(timeout=.05)
                except queue.Empty: continue
                try:
                    if self._write_error: continue
                    self._write_started = time.monotonic()
                    self._trace('write_begin', first_sample_index=first,
                                block_samples=block.shape[1], queue_wait_sec=self._write_started-queued)
                    payload = np.ascontiguousarray(block.T).tobytes()
                    written = self._spool_handle.write(payload)
                    if written != len(payload): raise OSError(f'short write: {written}/{len(payload)} bytes')
                    if self._raw_handle is not None:
                        raw_payload=raw.tobytes()
                        if self._raw_handle.write(raw_payload)!=len(raw_payload):raise OSError('short raw TRG write')
                        self._raw_saved_count+=len(raw)
                    now = time.monotonic()
                    if now-self._last_spool_flush >= self._spool_flush_interval_sec:
                        self._spool_handle.flush(); self._last_spool_flush=now
                        if self._raw_handle is not None:self._raw_handle.flush()
                    self._saved_count += block.shape[1]
                    self._trace('write_done', first_sample_index=first,
                                elapsed_sec=time.monotonic()-self._write_started)
                except Exception as exc:
                    self._fail(exc)
                finally:
                    self._write_started = None
                    self._queue.task_done()
        except Exception as exc:
            self._fail(exc)
        finally:
            self._write_started = time.monotonic()
            try:
                self._spool_handle.flush(); os.fsync(self._spool_handle.fileno())
            except Exception as exc: self._fail(exc)
            finally:
                try: self._spool_handle.close()
                except Exception as exc: self._fail(exc)
                self._spool_handle = None
            if self._raw_handle is not None:
                try:self._raw_handle.flush();os.fsync(self._raw_handle.fileno())
                except Exception as exc:self._fail(exc)
                finally:
                    try:self._raw_handle.close()
                    except Exception as exc:self._fail(exc)
                    self._raw_handle=None
            try: self._trace('writer_closed')
            except Exception as exc: self._fail(exc)
            finally:
                try: self._trace_file.close()
                except Exception as exc: self._fail(exc)
                self._write_started = None
                self._writer_done.set()

    def _save_error(self, detail):
        self.validation_error = str(detail)
        report = dict(self.writer_metadata(), error=str(detail), unix_sec=time.time(),
                      recovery='Preserve the complete directory, including raw spool; no overwrite or automatic resume.')
        path = self._directory/f'neuracle_save_error_part_{self.part_index:03d}.json'
        try:
            with path.open('x', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        except FileExistsError: pass
        except OSError as exc: print(f'Neuracle save error log failed: {exc}; original error: {detail}', flush=True)

    def export(self, output_dir, *, metadata, pull_final=True):
        if pull_final and not self._frozen: self.pull()
        self.freeze(); self._writer_stop.set()
        if self._writer is not None: self._writer.join(timeout=self._stop_timeout)
        if not self._writer_done.is_set():
            self._fail('write_stop_timeout: writer still owns raw file; do not close it from another thread')
        if self._saved_count != self._sample_count and not self._write_error:
            self._fail('received/saved sample count mismatch')
        if self._raw_ratio>1 and (self._raw_saved_count!=self._sample_count*self._raw_ratio):
            self._fail('Raw TRG / EEG saved count mismatch')
        if self._write_error:
            self._save_error(self._write_error)
            raise RuntimeError('Neuracle save/write failed: '+self._write_error)
        if self._spool_path.stat().st_size != self._saved_count*self._n_channels*4:
            self._save_error('Raw spool byte count mismatch')
            raise RuntimeError(self.validation_error)
        metadata = dict(metadata, neuracle_async_writer=self.writer_metadata(),
                        neuracle_saved_trigger_required=True)
        if self._raw_ratio>1:
            if self._raw_path.stat().st_size!=self._raw_saved_count*4:
                self._save_error('Raw TRG file byte count mismatch');raise RuntimeError(self.validation_error)
            metadata['neuracle_raw_trigger']=dict(file=self._raw_path.name,dtype='<f4',
                sample_count=self._raw_saved_count,**self._mapping)
        try:
            return super().export(output_dir, metadata=metadata, pull_final=False)
        except Exception as exc:
            self._save_error(exc)
            raise

    def validate_export_metadata(self, output_dir, metadata):
        try:
            result = verify_saved_triggers(output_dir/self.eeg_filename,
                output_dir/f'trg_receipts_part_{self.part_index:03d}.jsonl',
                n_channels=self._n_channels, sample_count=self._sample_count,
                trigger=metadata.get('neuracle_trigger', {}),raw_trigger=metadata.get('neuracle_raw_trigger'),
                eeg_format=metadata.get('eeg_format'), eeg_metadata=metadata)
        except Exception as exc:
            self._save_error(exc)
            result = dict(status='failed', error=str(exc), sample_index_base=0)
            metadata.update(completed=False, termination_reason='neuracle_saved_trigger_failed',
                            background_error=metadata.get('background_error') or str(exc))
        metadata['neuracle_saved_trigger'] = result
        with (output_dir/f'trg_saved_check_part_{self.part_index:03d}.json').open('x', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
