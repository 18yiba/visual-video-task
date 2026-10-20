"""Checked Neuracle DCP commands and independent TRG-return evidence."""
from __future__ import annotations
from collections import deque
import json
import struct
import threading
import time

from video_eeg.utils.markers import MarkerBackend


class VerifiedTriggerBox(MarkerBackend):
    delivery_status='device_acknowledged_pending_trg'

    def __init__(self,port,*,timeout_sec=.5,receipt_timeout_sec=3.,_serial=None,_clock=time.monotonic):
        self.port=str(port).strip();self._clock=_clock
        self._lock=threading.RLock();self.pending=deque();self.error=None
        self.last_write_accepted=False;self._last_value=0;self._sample_index=0
        self._last_raw_value=0
        self._confirmed=0;self._sent=0;self._file=None;self._last_port_check=0.
        self.sample_boundary = lambda: self._sample_index
        self.receipt_timeout=float(receipt_timeout_sec)
        self._io_timeout=float(timeout_sec)
        self._verify_presence=_serial is None
        if _serial is None:
            import serial
            from serial.tools.list_ports import comports
            entry=next((p for p in comports() if p.device.upper()==self.port.upper()),None)
            if entry is None:raise RuntimeError('同步盒串口未找到，请重新选择实际端口。')
            evidence=' '.join([entry.hwid or '',entry.description or '',entry.manufacturer or '']).lower()
            if 'usb' not in (entry.hwid or '').lower() or any(x in evidence for x in ('virtual','vspe','com0com','com2com','虚拟')):
                raise RuntimeError('博睿康模式需要真实 USB 同步盒串口，不接受虚拟串口。')
            self.hardware_id=entry.hwid
            _serial=serial.Serial(self.port,115200,timeout=timeout_sec,write_timeout=timeout_sec)
        else:self.hardware_id='injected test transport'
        self._serial=_serial
        try:
            self._serial.reset_input_buffer()
            self.device_name=self._command(4,b'').decode('ascii',errors='replace').strip('\0 ')
            if not self.device_name.startswith('TriggerBox.'):
                raise RuntimeError(f'设备不是已支持的 TriggerBox：{self.device_name!r}')
        except Exception:
            self._serial.close();raise

    def _read_exact(self,n):
        chunks=bytearray()
        deadline=time.monotonic()+self._io_timeout
        while len(chunks)<n:
            if time.monotonic()>deadline:raise RuntimeError('TriggerBox response deadline exceeded')
            part=self._serial.read(n-len(chunks))
            if not part:raise RuntimeError('TriggerBox response incomplete / timed out')
            chunks.extend(part)
        return bytes(chunks)

    def _command(self,fn,payload):
        frame=struct.pack('<BBH',1,fn,len(payload))+payload
        if self._serial.write(frame)!=len(frame):raise RuntimeError('TriggerBox short serial write')
        if fn==225:self.last_write_accepted=True
        device,returned,length=struct.unpack('<BBH',self._read_exact(4))
        if device!=1 or returned!=fn or length>256:
            raise RuntimeError(f'TriggerBox invalid response: device={device} function={returned} length={length}')
        return self._read_exact(length)

    def _fail(self,exc):
        if self.error is None:self.error=str(exc)
        raise RuntimeError(self.error)

    def check_health(self):
        with self._lock:
            if self.error:raise RuntimeError(self.error)
            if not self._serial.is_open:self._fail('同步盒串口已关闭')
            now=self._clock()
            if self.pending and now-self.pending[0]['sent_monotonic_sec']>self.receipt_timeout:
                self._fail(f"TRG 未在 {self.receipt_timeout:g} 秒内回传标记 {self.pending[0]['code']}；停止采集以免错标。")
            if self._verify_presence and now-self._last_port_check>=1:
                from serial.tools.list_ports import comports
                self._last_port_check=now
                if not any(p.device.upper()==self.port.upper() and p.hwid==self.hardware_id for p in comports()):
                    self._fail('同步盒 USB 串口消失或设备身份改变')

    def send(self,label,timestamp=None):
        with self._lock:
            self.check_health();self.last_write_accepted=False
            if not 1<=int(label)<=255 or int(label)!=label:raise ValueError('Trigger code must be an integer 1..255')
            try:
                sent=dict(code=int(label),sent_monotonic_sec=self._clock(),sent_unix_sec=time.time(),
                          sequence=self._sent+1, minimum_sample_index=self.sample_boundary())
                ack=self._command(225,bytes([int(label)]))
                # Reference supports event-code echo and E1 firmware ACK. Neither proves TRG arrival.
                if ack not in (bytes([int(label)]), b'\xe1'):raise RuntimeError(f'TriggerBox ACK mismatch: expected {label} or E1, received {ack.hex()}')
                sent['ack_payload_hex'] = ack.hex()
                self.pending.append(sent);self._sent+=1
            except Exception as exc:self._fail(exc)

    def observe(self,values,*,raw_values=None,trigger_ratio=1,raw_sfreq=None):
        with self._lock:
            raw_edges={}
            if raw_values is not None:
                if len(raw_values)!=len(values)*trigger_ratio or not raw_sfreq:
                    self._fail('TRG raw/mapped length or sampling rate mismatch')
                previous=self._last_raw_value
                for j,value in enumerate(raw_values):
                    if not float(value).is_integer() or not 0<=int(value)<=255:self._fail('TRG invalid raw value')
                    code=int(value)
                    if code and code!=previous:
                        target=j//trigger_ratio
                        if target in raw_edges or int(values[target])!=code:self._fail('TRG raw/mapped edge collision')
                        raw_edges[target]=self._sample_index*trigger_ratio+j
                    previous=code
                if len(raw_values):self._last_raw_value=previous
            for position,value in enumerate(values):
                if not float(value).is_integer():self._fail(f'TRG contains a noninteger value: {value}')
                code=int(value)
                if not 0 <= code <= 255:self._fail(f'TRG value outside 0..255: {code}')
                if (code and code!=self._last_value and not self.error and self.pending
                        and code==self.pending[0]['code']
                        and self._sample_index>=self.pending[0]['minimum_sample_index']):
                    receipt=self.pending.popleft()
                    receipt.update(received_sample_index=self._sample_index,received_unix_sec=time.time(),
                                   sample_index_base=0,hardware_ack=True)
                    if raw_values is not None:
                        if position not in raw_edges:self._fail('TRG mapped confirmation lacks original edge')
                        raw_index=raw_edges[position]
                        receipt.update(received_raw_trigger_sample_index=raw_index,
                            raw_trigger_sampling_rate_hz=raw_sfreq,
                            received_raw_trigger_time_sec=raw_index/raw_sfreq,
                            mapping_early_by_sec=(raw_index-self._sample_index*trigger_ratio)/raw_sfreq)
                    self._confirmed+=1
                    if self._file:
                        self._file.write(json.dumps(receipt,ensure_ascii=False)+'\n');self._file.flush()
                self._last_value=code;self._sample_index+=1

    def start_recording(self,directory,part,title):
        from pathlib import Path
        self._file=(Path(directory)/f'trg_receipts_part_{part:03d}.jsonl').open('x',encoding='utf-8')

    def finish_recording(self):
        # The session manager keeps pulling until the final marker returns.
        end=time.monotonic()+self.receipt_timeout+.2
        while self.pending:
            self.check_health()
            if time.monotonic()>end:self._fail('TRG final marker confirmation timed out')
            time.sleep(.01)
        self.check_health()

    def recording_metadata(self):
        with self._lock:
            return dict(neuracle_trigger=dict(port=self.port,hardware_id=self.hardware_id,device_name=self.device_name,
                transport='Neuracle DCP 115200 8N1',ack_format='event code or E1; independent TRG required',sent_count=self._sent,confirmed_count=self._confirmed,
                pending_codes=[x['code'] for x in self.pending],error=self.error,
                confirmation='matching value edge in forwarded TRG channel',
                recording_control='local TCP recording only; does not control Collect disk recording'))

    def close(self):
        with self._lock:
            if self._file:self._file.close();self._file=None
            self._serial.close()
