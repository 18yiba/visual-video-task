import struct
import numpy as np
import pytest
from video_eeg.utils.neuracle_markers import VerifiedTriggerBox


class Serial:
    is_open=True
    def __init__(self,ack=None,short=False):self.rx=b'';self.ack=ack;self.short=short;self.writes=[]
    def write(self,b):
        self.writes.append(b);fn=b[1];payload=b'TriggerBox.Titing' if fn==4 else self.ack if self.ack is not None else b[-1:]
        self.rx=struct.pack('<BBH',1,fn,len(payload))+payload
        if self.short:self.rx=self.rx[:2]
        return len(b)
    def read(self,n):
        # Real serial.read can return fragments.
        b=self.rx[:min(n,2)];self.rx=self.rx[len(b):];return b
    def close(self):self.is_open=False
    def reset_input_buffer(self):self.rx=b''


def box(serial=None,clock=None):
    return VerifiedTriggerBox('COM_TEST',_serial=serial or Serial(),_clock=clock or (lambda:0.))


def test_ack_only_does_not_count_as_received_marker():
    b=box();b.send(132)
    assert b.last_write_accepted
    assert b.recording_metadata()['neuracle_trigger']['confirmed_count']==0
    b.observe(np.array([0,132,132,0]))
    assert b.recording_metadata()['neuracle_trigger']['confirmed_count']==1
    assert not b.pending


def test_no_returned_trigger_fault_is_sticky():
    t=[0.];b=box(clock=lambda:t[0]);b.send(132);t[0]=4
    with pytest.raises(RuntimeError,match='TRG'):b.check_health()
    b.observe(np.array([132,0]))
    with pytest.raises(RuntimeError):b.send(133)


def test_wrong_ack_and_short_response_rejected():
    b=box(Serial(ack=b'\x00'))
    with pytest.raises(RuntimeError,match='ACK'):b.send(132)
    with pytest.raises(RuntimeError,match='response'):box(Serial(short=True))


def test_adjacent_different_codes_and_repeat_after_zero():
    b=box();b.send(140);b.send(132);b.send(132)
    b.observe(np.array([0,140,132,132,0,132,0]))
    assert b.recording_metadata()['neuracle_trigger']['confirmed_count']==3
    assert not b.pending


def test_out_of_order_receipt_cannot_confirm_lost_marker():
    b=box();b.send(140);b.send(132);b.observe(np.array([0,132,0]))
    assert len(b.pending)==2
