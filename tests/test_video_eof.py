from types import SimpleNamespace
from pathlib import Path
import os
import pytest
from video_eeg.experiment import video_runner as base
from video_eeg.utils import video_eof

class Capture:
    def __init__(self,count):self.count=count;self.pos=1;self.calls=0
    def read(self):
        self.calls+=1
        if self.pos>=self.count:return False,None
        self.pos+=1;return True,self.pos-1

def player(count=699,verified=699):
    p=base.OpenCVVideoPlayer.__new__(base.OpenCVVideoPlayer)
    p._finished=False;p._ended_prematurely=False;p._play_started=True;p._start_time=0;p._fps=18.165;p._frame_count=700;p._current_index=0
    p._verified_terminal_count=verified;p._terminal_eof_confirmed=False;p._eof_compatibility_note='';p._cap=Capture(count)
    p._stim=SimpleNamespace(draw=lambda:None);p.size=(10,10);p.frames=[];p._set_frame=p.frames.append;p._stop_audio=lambda:None
    return p

def step(p,index,monkeypatch):
    monkeypatch.setattr(base.time,'perf_counter',lambda:(index+.1)/p._fps);p.draw()

def test_audited_tail_holds_to_original_deadline(monkeypatch):
    p=player()
    for i in range(1,700):step(p,i,monkeypatch)
    assert p._terminal_eof_confirmed and not p.isFinished and not p._ended_prematurely
    assert p._current_index==698 and p.frames[-1]==698
    assert p._eof_compatibility_note==video_eof.AUDITED_EOF_NOTE
    reads=p._cap.calls;step(p,699.5,monkeypatch);assert p._cap.calls==reads
    step(p,700,monkeypatch);assert p.isFinished and not p._ended_prematurely

@pytest.mark.parametrize('count,verified',[(698,699),(400,699),(699,None),(1,None)])
def test_unverified_or_earlier_failure_remains_abort(monkeypatch,count,verified):
    p=player(count,verified)
    for i in range(1,700):
        step(p,i,monkeypatch)
        if p.isFinished:break
    assert p._ended_prematurely and not p._eof_compatibility_note

def test_exact_declared_count_keeps_normal_end(monkeypatch):
    p=player(700,None)
    for i in range(1,701):step(p,i,monkeypatch)
    assert p.isFinished and not p._ended_prematurely and not p._eof_compatibility_note

def test_partial_advance_keeps_last_decoded_frame(monkeypatch):
    p=player();p._current_index=696;p._cap.pos=697;step(p,699,monkeypatch)
    assert p.frames[-1]==698 and p._terminal_eof_confirmed and not p.isFinished

@pytest.mark.parametrize('count,fps',[(699,18.165),(700,30),(700,float('nan'))])
def test_changed_metadata_not_accepted(tmp_path,count,fps):
    p=tmp_path/video_eof.AUDITED_NAME;p.write_bytes(b'changed')
    assert video_eof.verified_terminal_frame_count(p,count,fps) is None

def test_wrong_content_and_missing_file_are_not_accepted(tmp_path):
    p=tmp_path/video_eof.AUDITED_NAME;p.write_bytes(b'not the audited video')
    assert video_eof.verified_terminal_frame_count(p,700,18.165) is None
    assert video_eof.verified_terminal_frame_count(tmp_path/'other.mp4',700,18.165) is None
    assert video_eof.verified_terminal_frame_count(tmp_path/'missing'/video_eof.AUDITED_NAME,700,18.165) is None

def test_actual_audited_material_if_provided():
    filename=os.environ.get('VIDEO_EOF_AUDIT_FILE')
    if not filename:pytest.skip('actual material supplied only for local audit')
    p=Path(filename)
    assert video_eof.verified_terminal_frame_count(p,700,18.165)==699

def test_all_profiles_are_pinned_to_fixed_material_manifest():
    import csv
    root=Path(__file__).resolve().parents[1]
    with (root/'video_eeg/config/session_manifest_emotion_v1.csv').open(encoding='utf-8-sig',newline='') as handle:
        rows={r['video_path']:r for r in csv.DictReader(handle)}
    for name,p in video_eof.PROFILES.items():
        assert Path(p['video_path']).name==name
        import json
        hashes={x['path']:x['sha256'] for x in json.loads((root/'video_eeg/config/materials_manifest.json').read_text(encoding='utf-8-sig'))['files']}
        expected=rows[p['video_path']]['sha256'] or hashes[p['video_path'].replace('original/','videos/',1)]
        assert p['sha256']==expected
        assert int(p['session_id'])==int(rows[p['video_path']]['session_id'])
        assert p['decoded_frames']==p['ffmpeg_frames']
        assert p['declared_frames']-p['decoded_frames'] in (1,2)
        assert p['fps']>0


def test_every_profile_hash_and_count_if_material_root_provided():
    root=os.environ.get('VIDEO_EOF_AUDIT_ROOT')
    if not root:pytest.skip('full local materials not distributed with source')
    root=Path(root)
    for name,p in video_eof.PROFILES.items():
        prefix,rel=p['video_path'].split('/',1)
        path=root/('emotion_video/selected' if prefix=='emotion' else 'videos')/rel
        assert video_eof.verified_terminal_frame_count(path,p['declared_frames'],p['fps'])==p['decoded_frames']



def test_known_corrupt_hash_stops_without_changing_bytes(tmp_path,monkeypatch):
    import hashlib
    path=tmp_path/'bad.mp4';path.write_bytes(b'broken-original')
    before=path.read_bytes()
    monkeypatch.setattr(video_eof,'BLOCKED',{'bad.mp4':{'sha256':hashlib.sha256(before).hexdigest()}})
    with pytest.raises(RuntimeError,match='本 Session 暂不能开始'):
        video_eof.check_known_bad_materials([path])
    assert path.read_bytes()==before
    path.write_bytes(b'different-file')
    video_eof.check_known_bad_materials([path])
    video_eof.check_known_bad_materials([tmp_path/'unlisted.mp4'])



def test_audited_two_frame_tail_also_keeps_original_deadline(monkeypatch):
    p=player(698,698)
    for i in range(1,700):step(p,i,monkeypatch)
    assert p._terminal_eof_confirmed and not p.isFinished and not p._ended_prematurely
    assert p.frames[-1]==697
    step(p,700,monkeypatch)
    assert p.isFinished and not p._ended_prematurely
