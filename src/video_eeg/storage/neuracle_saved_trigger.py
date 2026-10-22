"""Independent readback of final NPY TRG values, using zero-based sample indices."""
import json
from pathlib import Path

import numpy as np


def verify_saved_triggers(path, receipt_path, *, n_channels, sample_count, trigger, raw_trigger=None):
    data = np.load(path, mmap_mode='r', allow_pickle=False)
    try:
        if data.dtype != np.float32 or data.shape != (n_channels, sample_count):
            raise RuntimeError('Saved EEG shape/dtype does not match the received stream')
        if Path(path).stat().st_size != data.offset + data.nbytes:
            raise RuntimeError('Saved EEG file size does not match NPY header')
        receipts = [json.loads(line) for line in Path(receipt_path).read_text(encoding='utf-8').splitlines() if line.strip()]
        if trigger.get('error') or trigger.get('pending_codes'):
            raise RuntimeError('Trigger delivery failed or remains unconfirmed')
        if not receipts or len(receipts) != trigger.get('confirmed_count') or len(receipts) != trigger.get('sent_count'):
            raise RuntimeError('Sent / confirmed / saved receipt counts differ or are empty')
        previous = -1
        expected = []
        for sequence, receipt in enumerate(receipts, 1):
            index, code = receipt.get('received_sample_index'), receipt.get('code')
            if type(index) is not int or not previous < index < sample_count:
                raise RuntimeError('Saved TRG receipt index is invalid, repeated or out of range')
            if type(code) is not int or not 1 <= code <= 255 or receipt.get('sequence') != sequence:
                raise RuntimeError('Saved TRG receipt code/sequence is invalid')
            if index < receipt.get('minimum_sample_index', 0) or not receipt.get('hardware_ack'):
                raise RuntimeError('Saved TRG receipt predates send or lacks hardware ACK')
            if float(data[-1, index]) != code:
                raise RuntimeError(f'Saved TRG mismatch at sample {index}: expected {code}, got {data[-1,index]}')
            expected.append((index, code)); previous = index
        # Check every edge, not only values at the expected locations. Chunk to bound memory.
        actual = []; last = 0
        for start in range(0, sample_count, 100000):
            values = np.asarray(data[-1, start:start+100000])
            if (not np.isfinite(values).all() or np.any(values != np.floor(values))
                    or np.any(values < 0) or np.any(values > 255)):
                raise RuntimeError('Invalid saved TRG values')
            prev = np.concatenate(([last], values[:-1]))
            for i in np.flatnonzero((values != 0) & (values != prev)):
                actual.append((start+int(i), int(values[i])))
            if values.size: last = values[-1]
        if actual != expected:
            raise RuntimeError('Saved TRG edges differ from receipt sequence (extra/missing marker)')
        raw_result={}
        if raw_trigger is not None:
            raw_result=verify_raw_trigger(Path(path).parent,raw_trigger,data,receipts,sample_count)
        return dict(**raw_result,status='passed', verified_count=len(receipts), sample_index_base=0,
                    eeg_file=Path(path).name, receipt_file=Path(receipt_path).name,
                    evidence='final NPY TRG channel values and all nonzero edges')
    finally:
        if hasattr(data, '_mmap'): data._mmap.close()


def verify_raw_trigger(directory, metadata, eeg, receipts, sample_count):
    ratio=metadata.get('ratio');rate=metadata.get('raw_sampling_rate_hz')
    if ratio!=4 or rate!=1000 or metadata.get('eeg_sampling_rate_hz')!=250:
        raise RuntimeError('Unsupported saved raw TRG mapping metadata')
    filename=metadata.get('file','')
    if not filename or Path(filename).name!=filename:raise RuntimeError('Invalid raw TRG path')
    path=directory/filename
    count=sample_count*ratio
    if metadata.get('sample_count')!=count or path.stat().st_size!=count*4:
        raise RuntimeError('Saved raw TRG file length mismatch')
    raw=np.memmap(path,dtype='<f4',mode='r',shape=(count,))
    try:
        actual=[];last=0
        for start in range(0,sample_count,100000):
            values=np.asarray(raw[start*ratio:min(sample_count,start+100000)*ratio])
            if (not np.isfinite(values).all() or np.any(values!=np.floor(values))
                    or np.any(values<0) or np.any(values>255)):
                raise RuntimeError('Invalid saved raw TRG values')
            prior=np.concatenate(([last],values[:-1]))
            for i in np.flatnonzero((values!=0)&(values!=prior)):
                actual.append((start*ratio+int(i),int(values[i])))
            if values.size:last=values[-1]
            groups=values.reshape(-1,ratio);mapped=groups.max(axis=1)
            if np.any((groups!=0)&(groups!=mapped[:,None])) or not np.array_equal(mapped,eeg[-1,start:start+len(mapped)]):
                raise RuntimeError('Saved raw TRG does not map to saved EEG TRG')
        expected=[]
        for receipt in receipts:
            index=receipt.get('received_raw_trigger_sample_index')
            if (type(index) is not int or not 0<=index<count
                    or index//ratio!=receipt['received_sample_index']
                    or receipt.get('raw_trigger_sampling_rate_hz')!=rate
                    or abs(receipt.get('received_raw_trigger_time_sec',-1)-index/rate)>1e-9
                    or abs(receipt.get('mapping_early_by_sec',-1)-(index%ratio)/rate)>1e-9):
                raise RuntimeError('Saved raw TRG receipt timing/index mismatch')
            expected.append((index,receipt['code']))
        if actual!=expected:raise RuntimeError('Saved raw TRG edges differ from receipt sequence')
        return dict(raw_trigger_verified=True,raw_trigger_file=filename,raw_trigger_samples=count,
                    raw_trigger_sampling_rate_hz=rate,mapped_eeg_sampling_rate_hz=250,
                    max_mapping_early_by_sec=.003)
    finally:raw._mmap.close()
