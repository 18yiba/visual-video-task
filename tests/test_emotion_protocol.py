import csv
import hashlib
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from video_eeg.utils.emotion_protocol import CLASSES, RATING_PAGES, parse_rating, presentation_order
from video_eeg.utils.session_protocol import SessionManifest, SessionManifestEntry, SessionState, load_state, save_state_atomic
from video_eeg.utils.video_library import VideoAsset
from video_eeg.utils.markers import PROTOCOL_EVENT_CODES
from video_eeg.experiment.emotion_runner import EmotionVideoRunner

ROOT = Path(__file__).resolve().parents[1]
def read(name):
    with (ROOT/'video_eeg/config'/name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def test_all_materials_exactly_once_and_every_session_balanced():
    rows = read('session_manifest_emotion_v1.csv')
    ordinary = [r for r in rows if r['trial_type']=='ordinary']
    emotion = [r for r in rows if r['trial_type']=='emotion']
    assert len(rows)==len({r['video_id'] for r in rows})==len({r['video_path'] for r in rows})==11087
    assert {r['original_id'] for r in ordinary}=={r['video_id'] for r in read('session_manifest.csv')}
    assert len(emotion)==len({r['sha256'] for r in emotion})==3138
    assert Counter(r['three_class_label'] for r in emotion)==dict.fromkeys(CLASSES,1046)
    assert Counter(r['original_label'] for r in emotion)==dict(Excitation=523,Relaxation=523,Neutral=1046,Fear=349,Sad=349,Tension=348)
    assert all(5<=float(r['video_duration_sec'])<=60 for r in emotion)
    for sid in range(1,46):
        group = [r for r in rows if int(r['session_id'])==sid]
        counts = Counter(r['three_class_label'] for r in group if r['trial_type']=='emotion')
        assert set(counts)==set(CLASSES) and len(set(counts.values()))==1
        assert 85<=sum(float(r['video_duration_sec']) for r in group)/60<=95
        assert len({r['duration_bucket'] for r in group if r['trial_type']=='ordinary'})==5

def test_order_reproducible_subject_specific_and_emotion_interleaved():
    rows = [r for r in read('session_manifest_emotion_v1.csv') if r['session_id']=='1']
    a = presentation_order(rows,20260912,'A',1)
    assert a==presentation_order(rows,20260912,'A',1)
    assert a!=presentation_order(rows,20260912,'B',1)
    assert set(a)=={r['video_id'] for r in rows}
    lookup = {r['video_id']:r for r in rows}
    emotions = [lookup[k]['three_class_label'] for k in a if lookup[k]['trial_type']=='emotion']
    assert not any(emotions[i]==emotions[i+1]==emotions[i+2] for i in range(len(emotions)-2))
    positions = [i for i,k in enumerate(a) if lookup[k]['trial_type']=='emotion']
    assert positions[0]<len(a)*.1 and positions[-1]>len(a)*.9

@pytest.mark.parametrize('key,expected', [('0',None),('10',None),('',None),('f',None),('space',None),('escape',None),('1',1),('9',9),('num_5',5)])
def test_rating_only_one_to_nine(key,expected):
    assert parse_rating(key)==expected
    assert parse_rating(SimpleNamespace(name=key))==expected

def test_scale_words_do_not_expose_labels_and_two_pages_only():
    assert [p[0] for p in RATING_PAGES]==['valence','arousal']
    for _, wording, anchors in RATING_PAGES:
        assert all(label not in wording+anchors for label in ('positive','negative','Excitation','Fear','Sad','Tension','.mp4'))

def test_marker_codes_preserve_legacy_and_add_unique_events():
    assert [PROTOCOL_EVENT_CODES[k] for k in ('video_on','video_off','break_start','break_end','attention_task_on')]==[132,133,136,137,142]
    new = [value for key,value in PROTOCOL_EVENT_CODES.items() if key.isupper()]
    assert len(new)==len(set(new))==14
    assert not set(new)&{value for key,value in PROTOCOL_EVENT_CODES.items() if not key.isupper()}

@pytest.mark.parametrize('phase', ['video','valence','arousal'])
def test_partial_rating_state_survives_and_video_is_not_committed(tmp_path,phase):
    asset = VideoAsset('emotion:1','emotion/1.mp4',10.,'emotion','valid')
    manifest = SessionManifest(version='emotion-test', entries=[SessionManifestEntry(1,asset.asset_id,asset.rel_path,10.)])
    state = SessionState.new(subject_id='TEST',session_id=1,manifest=manifest,assets=[asset],random_seed=2,
        attention_task_count=0,rest_min_minutes=30,rest_max_minutes=45)
    state.attention_task_type='emotion_rating'
    rating = dict(completed=False, interrupted=True, valence_rating=5 if phase=='arousal' else None, arousal_rating=None)
    state.video_attempts.append(dict(video_id=asset.asset_id,completed=False,emotion_rating=rating))
    state.preserve_aborted_video(asset.asset_id)
    path = tmp_path/'state.json'
    save_state_atomic(path,state)
    resumed=load_state(path)
    assert resumed.queue_video_ids==[asset.asset_id] and not resumed.completed_video_ids
    assert resumed.video_attempts[0]['emotion_rating']==rating
    assert resumed.attention_task_type=='emotion_rating'

def test_export_failure_still_stops_and_exports_eeg():
    runner = object.__new__(EmotionVideoRunner)
    runner.manager=Mock()
    runner.state=SimpleNamespace(session_completed=False,completed_video_ids=[],completed_net_video_duration_sec=8,
        material_exclusion_revision="",excluded_video_ids=[],material_exclusion_history=[],
        active_video_ids=[],active_completed_video_ids=[])
    runner.completed=False; runner.termination_reason='esc_emergency'; runner.progress_dir=Path('test')
    runner.protocol=SimpleNamespace(attention_enabled=False,attention_tasks_per_session=0)
    runner._write_trial_log=Mock(side_effect=PermissionError('locked'))
    runner._write_rating_log=Mock(); runner._write_rest_log=Mock(); runner._checkpoint=Mock()
    runner._stop_and_export()
    runner.manager.stop_and_export.assert_called_once()
    assert runner.manager.stop_and_export.call_args.kwargs['metadata']['export_warnings']

def test_legacy_manifests_byte_identical():
    expected={'session_manifest.csv':'56dc9fa3bcfeb90c5e42fdccc114c633dc9284dba6e17295e4f95de7671679b9'}
    for name,digest in expected.items():
        assert hashlib.sha256((ROOT/'video_eeg/config'/name).read_bytes()).hexdigest()==digest
