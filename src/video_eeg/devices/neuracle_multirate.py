"""Loss-aware integer TRG mapping; EEG samples are never interpolated."""
import numpy as np

from video_eeg.devices.neuracle_verified import StrictRingBuffer


def map_trigger(raw, ratio, previous_raw=0, previous_mapped=0):
    raw=np.asarray(raw,dtype=np.float32)
    if (raw.ndim!=1 or not raw.size or raw.size%ratio or not np.isfinite(raw).all()
            or np.any(raw!=np.floor(raw)) or np.any(raw<0) or np.any(raw>255)):
        raise RuntimeError('TRG invalid samples or incomplete mapping interval')
    groups=raw.reshape(-1,ratio)
    mapped=groups.max(axis=1)
    if np.any((groups!=0)&(groups!=mapped[:,None])):
        raise RuntimeError('TRG collision: multiple codes in one EEG sample interval')
    edges=np.flatnonzero((raw!=0)&(raw!=np.concatenate(([previous_raw],raw[:-1]))))
    mapped_edges=np.flatnonzero((mapped!=0)&(mapped!=np.concatenate(([previous_mapped],mapped[:-1]))))
    expected=[(int(i)//ratio,int(raw[i])) for i in edges]
    actual=[(int(i),int(mapped[i])) for i in mapped_edges]
    if expected!=actual:
        raise RuntimeError('TRG mapping would merge/drop marker edges; capture stopped')
    return mapped, int(raw[-1]), int(mapped[-1])


class RawTriggerRingBuffer(StrictRingBuffer):
    """EEG and source TRG use a single lock and the same time span."""
    def __init__(self,n_chan,n_points,ratio):
        super().__init__(n_chan,n_points)
        self.ratio=ratio;self.raw=np.zeros(n_points*ratio,dtype=np.float32)
        self.next_raw=None

    def appendBuffer(self,data):
        with self.bufferLock:
            n=data.shape[1];raw=self.next_raw
            if (data.ndim!=2 or data.shape[0]!=self.n_chan or self.nUpdate+n>self.n_points
                    or not np.isfinite(data).all() or raw is None or raw.shape!=(n*self.ratio,)):
                raise RuntimeError('Neuracle raw TRG / EEG buffer overflow or shape mismatch')
            self.buffer[:,(np.arange(n)+self.currentPtr)%self.n_points]=data
            self.raw[(np.arange(raw.size)+self.currentPtr*self.ratio)%self.raw.size]=raw
            self.currentPtr=(self.currentPtr+n)%self.n_points
            self.nUpdate+=n;self.total_received+=n;self.next_raw=None

    def getUpdateWithTrigger(self):
        with self.bufferLock:
            first=self.currentPtr-self.nUpdate
            data=self.buffer[:,(np.arange(self.nUpdate)+first)%self.n_points].copy()
            raw=self.raw[(np.arange(self.nUpdate*self.ratio)+first*self.ratio)%self.raw.size].copy()
            self.lastPtr=self.currentPtr;self.nUpdate=0
            return data,raw

    def getUpdate(self):return self.getUpdateWithTrigger()[0]
