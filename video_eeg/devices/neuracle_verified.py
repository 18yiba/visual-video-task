"""Strict Neuracle forwarding: actual metadata, bounded buffers, sticky faults.

The packet codec is the vendor's existing collect.neuracle_api implementation.
Select named channels as THINGS does; preserve EEG and independently retain high-rate TRG.
"""
from __future__ import annotations

import time
import threading
import struct
import numpy as np
from video_eeg.devices.collect.neuracle_api import DataServerThread, ConnectState, RingBuffer
from video_eeg.devices.neuracle_acquirer import NeuracleAcquirer


# Exact signal order from the supplied desktop THINGS devices.yaml (64 + TRG).
# No transport settings or event codes are imported from that project.
THINGS_CHANNEL_NAMES = tuple(('Fpz Fp1 Fp2 AF3 AF4 AF7 AF8 Fz F1 F2 F3 F4 F5 F6 F7 F8 '
    'FCz FC1 FC2 FC3 FC4 FC5 FC6 FT7 FT8 Cz C1 C2 C3 C4 C5 C6 T7 T8 '
    'CP1 CP2 CP3 CP4 CP5 CP6 TP7 TP8 Pz P3 P4 P5 P6 P7 P8 '
    'POz PO3 PO4 PO5 PO6 PO7 PO8 Oz O1 O2 ECG HEOR HEOL VEOU VEOL TRG').split())


def channel_key(name):
    key = str(name).strip('\0 ').upper()
    return 'TRG' if key in {'TRG', 'TRIGGER', 'TRIG', 'STIM'} else key


def validate_forwarded_metadata(server, sfreq, signal_channels, channel_names=None):
    raw_names = [str(x).strip('\0 ') for x in server.channelNames]
    raw_types = [str(x).strip('\0 ') for x in server.channelTypes]
    raw_rates = [float(x) for x in server.srates]
    keys = [channel_key(n) for n in raw_names]
    if any(not n for n in raw_names) or len(set(keys)) != len(keys):
        raise RuntimeError('转发通道名称为空或重复，无法确定通道布局。')
    expected = int(signal_channels) + 1
    if len(raw_types) != len(raw_names) or len(raw_rates) != len(raw_names):
        raise RuntimeError('转发通道元数据长度不一致。')
    if channel_names is not None:
        wanted = [channel_key(n) for n in channel_names]
        if len(wanted) != expected or len(set(wanted)) != expected or wanted[-1] != 'TRG':
            raise RuntimeError('配置通道名称须唯一、与信号通道数一致并以 TRG 结尾。')
        missing = [n for n in channel_names if channel_key(n) not in keys]
        if missing:
            raise RuntimeError('参考范式要求的通道未转发：' + ', '.join(missing) +
                '。请在 Collect 核对通道布局；不会用其他通道替代。实际通道：' + ', '.join(raw_names))
        selected = [keys.index(k) for k in wanted]
    else:
        if len(raw_names) != expected:
            raise RuntimeError(f'转发通道数不匹配：收到 {len(raw_names)}，需要 {signal_channels} 个信号通道 + 1 个 TRG。')
        selected = list(range(expected))
    names = [raw_names[i] for i in selected]
    types = [raw_types[i] for i in selected]
    rates = [raw_rates[i] for i in selected]
    trigger = [i for i,(n,t) in enumerate(zip(names,types)) if channel_key(n)=='TRG' or channel_key(t)=='TRG']
    if trigger != [expected-1]:
        raise RuntimeError(f'TRG 通道缺失或位置不匹配：检测到 {trigger}；保存的最后一行必须是唯一真实 TRG。收到通道：{names}')
    ratio = 4 if float(sfreq)==250 and rates[-1]==1000 else 1
    if (any(not np.isfinite(r) or abs(r-float(sfreq)) > .01 for r in rates[:-1])
            or not np.isfinite(rates[-1]) or abs(rates[-1]-float(sfreq)*ratio)>.01):
        groups = []
        for rate in sorted(set(rates)):
            group = ', '.join(n for n,r in zip(names,rates) if r == rate)
            groups.append(f'{rate:g} Hz: {group}')
        raise RuntimeError(f'所选通道采样率与设置 {sfreq:g} Hz 不符。' +
            '\n' + '\n'.join(groups) + f'\nTRG={rates[-1]:g} Hz。' +
            '\n请对照 Collect 的实际信号采样率设置范式。支持信号与 TRG 同频，以及信号 250 Hz + TRG 1000 Hz。' +
            '若上述信号均为 250 Hz，请将范式采样率填为 250；不会把 250 Hz EEG 伪装成 1000 Hz。')
    if not any(t.upper() == 'EEG' for t in types[:-1]):
        raise RuntimeError('所选转发通道中没有 EEG 通道。')
    result = dict(channel_names=names, channel_types=types, channel_sampling_rates_hz=rates,
        forwarded_signal_channel_count=len(raw_names)-1, selected_signal_channel_count=signal_channels,
        actual_eeg_channel_count=sum(t.upper()=='EEG' for t in types),
        selected_stream_indices=selected, ignored_channel_names=[n for i,n in enumerate(raw_names) if i not in selected],
        raw_channel_names=raw_names, raw_channel_types=raw_types, raw_channel_sampling_rates_hz=raw_rates,
        trigger_channel_index=expected-1, trigger_channel_name=names[-1],
        module_name=str(server.moduleName), module_type=str(server.moduleType),
        module_serial_number=int(server.serialNumber), sample_values='forwarded values without scaling',
        units_verified=False, resampling=ratio!=1, eeg_resampling=False,
        saved_channel_sampling_rates_hz=[float(sfreq)]*expected,
        trigger_mapping=dict(ratio=ratio, raw_sampling_rate_hz=rates[-1], eeg_sampling_rate_hz=float(sfreq),
            method='floor_to_eeg_interval_with_edge_loss_rejection', max_early_by_sec=(ratio-1)/rates[-1]))
    for field in ('maxPhysical','minPhysical','maxDigital','minDigital','gain'):
        if hasattr(server,field):
            values = getattr(server,field)
            result[field] = [int.from_bytes(values[i], 'little') if isinstance(values[i], bytes) else values[i] for i in selected]
    return result


class StrictRingBuffer(RingBuffer):
    def __init__(self, *args):
        super().__init__(*args)
        self.total_received = 0

    def appendBuffer(self, data):
        with self.bufferLock:
            if data.ndim != 2 or not np.isfinite(data).all():
                raise RuntimeError('Neuracle invalid/nonfinite sample block')
            n=data.shape[1]
            if data.shape[0] != self.n_chan or self.nUpdate+n > self.n_points:
                raise RuntimeError('Neuracle buffer overflow or channel count changed; capture stopped')
            self.buffer[:, (np.arange(n)+self.currentPtr)%self.n_points] = data
            self.currentPtr=(self.currentPtr+n)%self.n_points
            self.nUpdate+=n
            self.total_received+=n

    def getUpdate(self):
        with self.bufferLock:
            # Index by unread count: exact full wraps must not look empty.
            data=self.buffer[:, (np.arange(self.nUpdate)+self.currentPtr-self.nUpdate)%self.n_points].copy()
            self.lastPtr=self.currentPtr
            self.nUpdate=0
            return data


class StrictDataServer(DataServerThread):
    def __init__(self, *, signal_channels, channel_names=None, **kwargs):
        super().__init__(**kwargs)
        self.signal_channels=signal_channels
        self.selected_channel_names = (THINGS_CHANNEL_NAMES if signal_channels == 64 else None) if channel_names is None else tuple(channel_names)
        self.failure=None
        self.forwarded_metadata=None
        self.sock.settimeout(3.)
        self.sockBufLock=threading.RLock()

    def fail(self, error):
        if self.failure is None: self.failure=str(error)
        self.state=ConnectState.ABORT

    def receiveData(self):
        try:
            data=self.sock.recv(65536)
            if not data:
                if self.state != ConnectState.ABORT: self.fail('Neuracle TCP disconnected')
                return
            with self.sockBufLock:
                if len(self.socketBuffer)+len(data)>32*1024*1024:
                    self.fail('Neuracle TCP input buffer overflow')
                else: self.socketBuffer+=data
        except BlockingIOError:
            time.sleep(.001)
        except OSError as exc:
            if self.state != ConnectState.ABORT:self.fail(f'Neuracle TCP error: {exc}')

    def resolveDataThread(self):
        while self.state != ConnectState.ABORT:
            try:
                with self.sockBufLock:
                    before=len(self.socketBuffer)
                    if before>=10:
                        size=int.from_bytes(self.socketBuffer[6:10],'little')
                        if not 18<=size<=16*1024*1024:
                            raise RuntimeError(f'Invalid Neuracle packet length: {size}')
                if before:
                    self.resolve()
                if len(self.socketBuffer)==before:time.sleep(.001)
            except Exception as exc:
                # RLock cannot release a different thread's lock.
                try:self.sockBufLock.release()
                except RuntimeError:pass
                self.fail(f'Neuracle packet/continuity error: {exc}')

    def resolve(self):
        old_buffer=getattr(self,'buffer',None)
        # A changed metadata packet mid-run is an interruption, never ignored.
        with self.sockBufLock:
            if self.forwarded_metadata and self.socketBuffer[:2]==bytes.fromhex('5FF5') and len(self.socketBuffer)>=10:
                n=int.from_bytes(self.socketBuffer[6:10],'little')
                if len(self.socketBuffer)>=n and self.socketBuffer[:n]!=self._metadata_packet:
                    raise RuntimeError('Forwarded metadata changed during capture')
            packet=None
            if self.socketBuffer[:2]==bytes.fromhex('5FF5') and len(self.socketBuffer)>=10:
                n=int.from_bytes(self.socketBuffer[6:10],'little')
                if len(self.socketBuffer)>=n:packet=self.socketBuffer[:n]
            if packet is not None:
                # Split-module merging synthesizes TRG zeros: require actual bulk TRG.
                if len(packet) < 18 or struct.unpack_from('<I', packet, 10)[0] % 2:
                    raise RuntimeError('需要合并转发（bulk），不接受分模块拼接 TRG。')
            if self.socketBuffer[:2] == bytes.fromhex('5AA5') and len(self.socketBuffer) >= 30:
                n = int.from_bytes(self.socketBuffer[6:10], 'little')
                if len(self.socketBuffer) >= n:
                    self._validate_data_packet(self.socketBuffer[:n])
        super().resolve()
        if getattr(self,'buffer',None) is not old_buffer:
            self.forwarded_metadata=validate_forwarded_metadata(self,self.sample_rate,self.signal_channels,self.selected_channel_names)
            ratio=self.forwarded_metadata['trigger_mapping']['ratio']
            if ratio>1:
                from video_eeg.devices.neuracle_multirate import RawTriggerRingBuffer
                self.buffer=RawTriggerRingBuffer(self.signal_channels+1,self.buffer.n_points,ratio)
            else:self.buffer=StrictRingBuffer(self.signal_channels+1,self.buffer.n_points)
            self._metadata_packet=packet

    def _validate_data_packet(self, packet):
        _, header, total, start, duration, triggers, flag, modules = struct.unpack_from('<H7I', packet)
        if header != 30 or total != len(packet) or flag % 2 or modules != 1 or duration <= 0:
            raise RuntimeError('Invalid Neuracle bulk data header')
        offset = struct.unpack_from('<I', packet, 30)[0]
        if offset != 34 or len(packet) < offset + 4 + self.n_chan + 2:
            raise RuntimeError('Invalid Neuracle module offset/length')
        if struct.unpack_from('<I', packet, offset)[0] != self.serialNumber:
            raise RuntimeError('Neuracle module identity changed')
        selected = self.forwarded_metadata['selected_stream_indices']
        # Match THINGS NeuracleTcpApi._process_data_packet: skip the N mask
        # bytes and validate the actual payload length/counts below. The reference
        # does not use these bytes as an admission gate; do not infer lost samples
        # from them. Continuity, actual TRG samples and saved-data audit stay active.
        counts = self.dataCountPerChannel
        chosen = [counts[i] for i in selected]
        ratio=self.forwarded_metadata['trigger_mapping']['ratio']
        if (len(counts)!=self.n_chan or min(counts)<0 or min(chosen)<=0
                or len(set(chosen[:-1]))!=1 or chosen[-1]!=chosen[0]*ratio):
            raise RuntimeError('Neuracle unequal/empty selected channel sample blocks')
        if abs(chosen[0] - duration*self.sample_rate/1000) > .001:
            raise RuntimeError('Neuracle timestamp length does not match sample count')
        expected = offset + 4 + self.n_chan + sum(counts)*4 + triggers*34 + 2
        if len(packet) != expected:
            raise RuntimeError('Neuracle data packet length mismatch')

    def isDataPacketLost(self, data):
        if self.lastTimestamp >= 0 and (self.lastTimestamp % (2**32)) != data['startTimeStamp']:
            raise RuntimeError(f"Neuracle packet discontinuity: expected {self.lastTimestamp % (2**32)}, received {data['startTimeStamp']}")
        self.lastTimestamp = data['startTimeStamp'] + data['timeStampLength']

    def ResampleTrigger(self, data):
        # Legacy hook name: select raw rows BEFORE constructing a rectangular array.
        # Exactly like THINGS, excluded AUX may have different sample counts.
        selected=[data[i] for i in self.forwarded_metadata['selected_stream_indices']]
        ratio=self.forwarded_metadata['trigger_mapping']['ratio']
        if ratio>1:
            from video_eeg.devices.neuracle_multirate import map_trigger
            raw=np.asarray(selected[-1],dtype=np.float32)
            previous=(0,0) if self.buffer.total_received==0 else self._trg_previous
            selected[-1],last_raw,last_mapped=map_trigger(raw,ratio,*previous)
            self._trg_previous=(last_raw,last_mapped)
            self.buffer.next_raw=raw
        return selected


class VerifiedNeuracleAcquirer(NeuracleAcquirer):
    verified_neuracle = True
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self._include_trigger_channel:raise ValueError('正式博睿康模式必须转发 TRG 通道。')
        self._forwarded={}
        self._stream_error=None
        self._observer=None
        self._last_raw_trigger=None

    def bind_marker(self, backend):
        self._observer=backend.observe
        backend.sample_boundary = lambda: getattr(getattr(self._server, 'buffer', None), 'total_received', 0)

    def start_stream(self):
        self.stop_stream()
        self._stream_error=None
        self._server=StrictDataServer(signal_channels=self.metadata.n_channels-1,
            sample_rate=self._sample_rate,t_buffer=self._buffer_sec,
            enable_save_buffer=False,record_timestamps=False)
        try:
            if self._server.connect(self._host,self._port):
                raise RuntimeError(f'无法连接 {self._host}:{self._port}；请在 Collect 启动 TCP 数据转发。')
            deadline=time.monotonic()+self._ready_timeout_sec
            while not self._server.isReady():
                self._check_stream()
                if time.monotonic()>deadline:raise RuntimeError('未收到完整元数据和连续数据，请检查设备及 TCP 转发。')
                time.sleep(.02)
            self._forwarded=dict(self._server.forwarded_metadata)
            expected=getattr(self,'expected_forwarded',None)
            if expected and any(expected.get(k)!=self._forwarded.get(k) for k in ('channel_names','channel_types','channel_sampling_rates_hz','module_serial_number')):
                raise RuntimeError('检测后脑电设备或转发通道发生变化，请重新检查。')
            self.metadata.eeg_channel_count=self._forwarded['actual_eeg_channel_count']
            self.metadata.trigger_channel_name=self._forwarded['trigger_channel_name']
            self._server.start()
        except Exception as exc:
            self._stream_error=str(exc)
            self.stop_stream()
            raise

    def _check_stream(self):
        if self._server is None:raise RuntimeError('Neuracle stream is not started')
        failure=getattr(self._server,'failure',None)
        if failure or getattr(self._server,'state',None)==ConnectState.ABORT:
            self._stream_error=failure or 'Neuracle stream stopped unexpectedly'
            raise RuntimeError(self._stream_error)

    def get_new_samples(self):
        self._check_stream()
        self._last_raw_trigger=None
        if hasattr(self._server.buffer,'getUpdateWithTrigger'):
            data,self._last_raw_trigger=self._server.buffer.getUpdateWithTrigger()
        else:data=self._server.buffer.getUpdate()
        if data.shape[0]!=self.metadata.n_channels:raise RuntimeError('Neuracle channel count changed')
        data=np.asarray(data,dtype=np.float32)
        if self._observer is not None and data.shape[1]:
            if self._last_raw_trigger is not None:
                mapping=self._forwarded['trigger_mapping']
                self._observer(data[-1],raw_values=self._last_raw_trigger,trigger_ratio=mapping['ratio'],
                               raw_sfreq=mapping['raw_sampling_rate_hz'])
            else:self._observer(data[-1])
        return data,np.arange(data.shape[1],dtype=np.float64)/self.metadata.sfreq

    def take_raw_trigger(self):
        raw=self._last_raw_trigger;self._last_raw_trigger=None
        return raw

    def recording_metadata(self):
        return dict(neuracle_forwarding=dict(self._forwarded,host=self._host,port=self._port,
            error=self._stream_error,strict_continuity=True),eeg_recording_mode='neuracle_tcp_local')
