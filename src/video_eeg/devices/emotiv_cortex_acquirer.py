"""Local Cortex EEG with explicit layout, raw packet journal and fail-closed gaps."""
import json
import math
import queue
import time
import threading
import numpy as np

from .base import AbstractAcquirer, AcquirerMetadata
from .cortex_transport import CortexTransport
from video_eeg.utils.markers import MarkerBackend


class CortexMarker(MarkerBackend):
    fail_closed_on_marker_error = True

    def __init__(self):
        self.acquirer = None

    def start_recording(self, directory, part, title):
        self.acquirer.journal = (directory / f'cortex_packets_part_{part:03d}.jsonl').open('x', encoding='utf-8')
        acq = self.acquirer
        response = acq.client.call('createRecord', dict(cortexToken=acq.client.token,
            session=acq.client.session, title=title))
        acq.record_id = response['record']['uuid']

    def send(self, label, timestamp=None):
        acq = self.acquirer
        if acq is None:
            raise RuntimeError('Cortex marker is not bound to EEG session')
        acq.client.check()
        # Capture wall time before RPC; the reply is not a hardware timing proof.
        started = time.time() * 1000
        reply = acq.client.call('injectMarker', dict(cortexToken=acq.client.token,
            session=acq.client.session, label=str(label), value=int(label),
            port='visual-video-task', time=started), timeout=2)
        if (not isinstance(reply, dict) or not reply.get('marker', {}).get('uuid')
                or reply.get('sessionId') != acq.client.session or reply.get('recordId') != acq.record_id):
            raise RuntimeError('Cortex marker acknowledgement missing')
        if acq.journal:
            with acq.journal_lock:
                acq.journal.write(json.dumps(dict(kind='marker', code=int(label),
                    requested_unix_ms=started, response=reply), ensure_ascii=False)+'\n')
                acq.journal.flush()

    def close(self):
        if self.acquirer and self.acquirer.journal:
            self.acquirer.journal.close()
            self.acquirer.journal = None


class EmotivCortexAcquirer(AbstractAcquirer):
    def __init__(self, *, headset_id='', client_factory=CortexTransport):
        self.client = client_factory()
        self.journal = None
        self.journal_lock = threading.Lock()
        self.previous_counter = None
        self.previous_time = None
        self.packet_count = 0
        self.record_id = None
        self.started = False
        self.last_flush = time.monotonic()
        try:
            self.client.login()
            devices = self.client.call('queryHeadsets') or []
            devices = [d for d in devices if (d['id'] == headset_id if headset_id else d.get('status') == 'connected')]
            if len(devices) != 1:
                raise RuntimeError('Cortex requires exactly one connected headset; set EMOTIV_HEADSET_ID for selection')
            self.headset = devices[0]
            if self.headset.get('isVirtual') or self.headset.get('status') != 'connected':
                raise RuntimeError('Connect a real headset in EMOTIV Launcher first')
            sessions = self.client.call('querySessions', dict(cortexToken=self.client.token)) or []
            if any(s.get('headset', {}).get('id') == self.headset['id'] for s in sessions):
                raise RuntimeError('Headset already has a session; stop the other application first. No session was closed.')
            rate = float(self.headset.get('settings', {}).get('eegRate', 0))
            sensors = self.headset.get('sensors', [])
            if not math.isfinite(rate) or rate <= 0 or not sensors or len(set(sensors)) != len(sensors):
                raise RuntimeError('Cortex did not provide a valid EEG rate and sensor layout')
            self.channel_names = list(sensors)
            self.metadata = AcquirerMetadata('emotiv_cortex', rate, len(sensors), len(sensors))
        except BaseException:
            self.client.close()
            raise

    def bind_marker(self, marker):
        if not isinstance(marker, CortexMarker):
            raise RuntimeError('Cortex EEG requires its own session marker backend')
        marker.acquirer = self

    def start_stream(self):
        if self.started:
            return
        try:
            response = self.client.call('createSession', dict(cortexToken=self.client.token,
                headset=self.headset['id'], status='active'))
            self.client.session = response['id']
            active = response.get('headset', {})
            if (active.get('settings', {}).get('eegRate') != self.metadata.sfreq
                    or active.get('sensors') != self.channel_names):
                raise RuntimeError('Cortex device layout changed since detection')
            result = self.client.call('subscribe', dict(cortexToken=self.client.token,
                session=self.client.session, streams=['eeg']))
            streams = [s for s in result.get('success', []) if s.get('streamName') == 'eeg']
            if result.get('failure') or len(streams) != 1:
                raise RuntimeError('Cortex EEG subscription failed; check EEG license')
            self.columns = streams[0]['cols']
            if len(set(self.columns)) != len(self.columns) or any(c not in self.columns for c in [*self.channel_names, 'COUNTER', 'INTERPOLATED']):
                raise RuntimeError('Cortex EEG columns do not match headset sensors')
            # Save EEG in the subscription's actual channel order.
            self.channel_names = [c for c in self.columns if c in self.channel_names]
            self.indices = [self.columns.index(c) for c in self.channel_names]
            self.started = True
        except BaseException:
            self.stop_stream()
            raise

    def stop_stream(self):
        try:
            if self.record_id and not self.client.closed and not self.client.error:
                self.client.call('stopRecord', dict(cortexToken=self.client.token, session=self.client.session), timeout=3)
        finally:
            try:
                if not self.client.closed:
                    self.client.close()
            finally:
                if self.journal:
                    # Preserve received tail packets even after a sticky acquisition fault.
                    while True:
                        try:
                            host_ns, msg = self.client.samples.get_nowait()
                        except queue.Empty:
                            break
                        self.journal.write(json.dumps(dict(host_arrival_ns=host_ns, packet=msg, uncommitted_tail=True))+'\n')
                    self.journal.flush()

    def get_new_samples(self):
        self.client.check()
        rows, timestamps = [], []
        # Finite batch prevents starving shutdown when producer stays busy.
        for _ in range(1024):
            try:
                host_ns, msg = self.client.samples.get_nowait()
            except queue.Empty:
                break
            if self.journal:
                with self.journal_lock:
                    self.journal.write(json.dumps(dict(host_arrival_ns=host_ns, packet=msg))+'\n')
            values = msg['eeg']
            if msg.get('sid') != self.client.session or len(values) != len(self.columns):
                raise RuntimeError('Cortex session/packet layout changed')
            counter = values[self.columns.index('COUNTER')]
            interpolated = values[self.columns.index('INTERPOLATED')]
            stamp = float(msg['time'])
            row = [float(values[i]) for i in self.indices]
            if not all(math.isfinite(v) for v in [stamp, counter, *row]):
                raise RuntimeError('Cortex returned nonfinite EEG/timestamp/counter')
            if interpolated != 0:
                raise RuntimeError('Cortex reported interpolated EEG; interrupted trial must replay')
            if self.previous_counter is not None:
                # Official per-second counter and supplied Flex SDK's uint16 counter.
                sequential = counter == self.previous_counter + 1
                wrapped = counter == 0 and self.previous_counter + 1 in (self.metadata.sfreq, 65536)
                if not (sequential or wrapped):
                    raise RuntimeError('Cortex sample counter gap/duplicate detected')
            if self.previous_time is not None and (stamp <= self.previous_time or stamp-self.previous_time > 2.5/self.metadata.sfreq):
                raise RuntimeError('Cortex timestamp discontinuity detected')
            self.previous_counter, self.previous_time = counter, stamp
            self.packet_count += 1
            rows.append(row)
            timestamps.append(stamp)
        if self.journal and time.monotonic()-self.last_flush >= 1:
            self.journal.flush()
            self.last_flush = time.monotonic()
        return (np.asarray(rows, dtype=np.float64).T if rows else np.empty((self.metadata.n_channels, 0)),
                np.asarray(timestamps, dtype=np.float64))

    def get_chunk(self, window_sec):
        return self.get_new_samples()

    def recording_metadata(self):
        return dict(channel_names=self.channel_names, eeg_channel_names=self.channel_names,
            eeg_units='uV', eeg_reference='unknown', eeg_filters='unknown',
            cortex_headset_id=self.headset['id'], cortex_columns=getattr(self, 'columns', []),
            cortex_sample_count=self.packet_count, cortex_session_id=self.client.session,
            cortex_record_id=self.record_id,
            cortex_warning_codes=list(getattr(self.client, 'warning_codes', [])),
            cortex_timestamp_basis='Cortex Unix seconds; raw packets retained',
            cortex_event_alignment='host arrival sample index; not hardware synchronization',
            cortex_interpolation_policy='stop', cortex_error=str(self.client.error) if self.client.error else None)
