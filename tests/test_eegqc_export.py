"""Synthetic handoff contracts, EDF roundtrip, retry integrity and raw preservation."""
import copy
import json
from uuid import UUID

import edfio
import numpy as np
import pytest

from video_eeg.utils import bids_export as b
from video_eeg.utils import eegqc_export as q
from video_eeg.storage.session_recorder import SessionRecorder


def fixture(tmp_path, subject='00000001', n=3001):
    folder = tmp_path/'source/session_01/20261008_120000'
    folder.mkdir(parents=True)
    data = np.vstack([np.arange(n), np.tile(np.linspace(-50, 50, n), (31, 1))]).astype('float32')
    np.save(folder/'continuous_eeg.npy', data)
    b.write_json(folder/'metadata.json', dict(subject_id=subject, session_id=1, eeg_part=1,
        num_sessions=45, device_type='brainco', sfreq=1000, n_channels=32, sample_count=n,
        recording_uuid='123456781234423482341234567890ab', termination_reason='completed',
        recording_started_at='2026-10-08T12:00:00+08:00', recording_ended_at='2026-10-08T12:00:04+08:00'))
    events = [dict(name='video_on', sample_index=100, relative_time_sec=.2,
        payload=dict(trial_idx=1, video_name='original:vid_0001', marker_code=20,
                     external_marker_sent=True, marker_send_success=True)),
        dict(name='video_off', sample_index=1100, relative_time_sec=1.25,
             payload=dict(trial_idx=1, video_name='original:vid_0001', completed_naturally=True)),
        dict(name='video_on', sample_index=1200, relative_time_sec=1.5,
             payload=dict(trial_idx=1, video_name='original:vid_0001', marker_code=20,
                          external_marker_sent=False, marker_send_success=True)),
        dict(name='video_off', sample_index=2000, relative_time_sec=2.4,
             payload=dict(trial_idx=1, video_name='original:vid_0001', completed_naturally=False, abort_reason='esc'))]
    b.write_json(folder/'events.json', events)
    settings = dict(paradigm_codes={'v2':'TEST-NOT-A-PRODUCTION-CODE'}, participant_map={},
        device=dict(model='SIMULATED-CONFIG', confirmation='Synthetic tests only', software_filters='n/a',
            physical_ranges_uv={n: [-100, 100] for n in b.profile_for({'device_type':'brainco'},32)['channel_names']}))
    return folder, data, settings


def test_edf_package_roundtrip_events_and_stable_retry(tmp_path):
    folder, data, settings = fixture(tmp_path)
    before = {p.name:b.digest(p) for p in folder.iterdir()}
    result = q.export_recording(folder, tmp_path/'eegqc', protocol='v2', settings=settings)
    root = next((tmp_path/'eegqc').glob('recording-*'))
    session = b.read_json(next(root.rglob('session.json')))
    assert session['participant_id'] == '00000001' and session['session_id'] == '123456781234423482341234567890ab'
    assert session['source_session_number'] == 1 and session['recording_status'] == 'complete'
    edf = edfio.read_edf(next(root.rglob('*.edf')))
    assert len(edf.signals) == 31 and len(edf.signals[0].data) == 3001
    assert edf.signals[0].sampling_frequency == 1000
    for i, signal in enumerate(edf.signals):
        np.testing.assert_allclose(signal.data, data[i+1], atol=200/65535, rtol=0)
        assert signal.physical_dimension == 'uV'
    import csv
    with next(root.rglob('*_events.tsv')).open(encoding='utf-8') as f:
        reader=csv.DictReader(f,delimiter='\t');assert reader.fieldnames[:2]==['onset','duration'];rows=list(reader)
    video=[r for r in rows if r['trial_type']=='video']
    assert len(video)==2 and len({r['trial_id'] for r in video})==2
    assert video[0]['onset']=='0.1' and video[0]['duration']=='1.05'
    assert video[0]['sample_index']=='100' and video[0]['trigger_value']=='20' and video[0]['completed']=='1'
    assert video[1]['trigger_value']=='n/a' and video[1]['completed']=='0'
    assert all(r['stimulus_id']=='original:vid_0001' for r in video)
    assert q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings)['recordings'][0]['status']=='EXISTS_VERIFIED'
    assert {p.name:b.digest(p) for p in folder.iterdir()}==before
    assert len(list(root.rglob('*.edf')))==1 and not list(root.rglob('*.vhdr'))
    assert result['recordings'][0]['official_validation']=='NOT_RUN'
    next(root.rglob('*.edf')).write_bytes(b'broken')
    with pytest.raises(b.BidsExportError,match='修改或缺失'):
        q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings)


def test_missing_identity_and_mapping_no_padding(tmp_path):
    folder, _, settings = fixture(tmp_path, subject='OLD_01')
    with pytest.raises(b.BidsExportError,match='8位'):
        q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings)
    settings['participant_map']={'v2':{'OLD_01':'00000009'}}
    assert q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings)['recordings']
    settings['paradigm_codes']={}
    result=q.export_recording(folder,tmp_path/'other',protocol='v2',settings=settings)
    session=b.read_json(next((tmp_path/'other').rglob('session.json')))
    assert result['recordings'] and session['paradigm_code']=='AVEEG-20260923'


def test_changed_source_refused_and_legacy_uuid_stable(tmp_path):
    folder, _, settings = fixture(tmp_path)
    m=b.read_json(folder/'metadata.json');m.pop('recording_uuid');b.write_json(folder/'metadata.json',m)
    rid=q.recording_id(folder,m,'v2')[0]
    assert UUID(rid).version==5 and q.recording_id(tmp_path/'copy/20261008_120000',m,'v2')[0]==rid
    q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings)
    b.write_json(folder/'events.json',[])
    with pytest.raises(b.BidsExportError,match='源记录或导出配置变化'):
        q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings)


def test_range_and_missing_times_fail_without_clipping(tmp_path):
    folder, _, settings = fixture(tmp_path)
    settings['device']['physical_ranges_uv']['FP1']=[-10,10]
    with pytest.raises(b.BidsExportError,match='超出'):
        q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings)
    assert not list((tmp_path/'eegqc').glob('recording-*'))
    m=b.read_json(folder/'metadata.json');m.pop('recording_started_at');b.write_json(folder/'metadata.json',m)
    with pytest.raises(b.BidsExportError,match='started_at'):
        q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings)


def test_new_part_uuid_and_event_journal_survive_before_export(tmp_path):
    class Acquirer:
        def get_new_samples(self):return np.zeros((32,10),dtype='float32'), np.arange(10)
    r=SessionRecorder(Acquirer(),sfreq=1000,n_channels=32)
    r.start_spooling(tmp_path);r.add_event('test',marker_code=4);r.pull()
    identity=b.read_json(tmp_path/'recording_identity_part_001.json')
    assert UUID(identity['recording_uuid']).version==4
    assert json.loads((tmp_path/'events_journal_part_001.jsonl').read_text())['name']=='test'
    r.freeze();r.export(tmp_path,metadata={},pull_final=False)
    assert b.read_json(tmp_path/'metadata.json')['recording_uuid']==identity['recording_uuid']
    r2=SessionRecorder(Acquirer(),sfreq=1000,n_channels=32,event_only=True);r2.start_spooling(tmp_path)
    assert r2.part_index==2 and b.read_json(tmp_path/'recording_identity_part_002.json')['recording_uuid']!=identity['recording_uuid']


def test_official_validation(tmp_path):
    folder,_,settings=fixture(tmp_path)
    result=q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings,validate=True)
    assert result['recordings'][0]['official_validation']['errors']==0


def test_missing_configuration_does_not_prevent_raw_save(tmp_path):
    result=q.after_recording(tmp_path,{'eegqc_config_path':str(tmp_path/'missing.json')})
    assert '原始记录已保存' in result and '待完成' in result


def test_parts_are_independent_and_source_state_untouched(tmp_path):
    folder, data, settings = fixture(tmp_path)
    (folder.parent/'session_state.json').write_text('{"progress":"keep"}',encoding='utf-8')
    m=b.read_json(folder/'metadata.json')
    m.update(eeg_part=2,recording_uuid='223456781234423482341234567890ab',
             eeg_file='continuous_eeg_part_002.npy',events_file='events_part_002.json',
             termination_reason='eeg_background_error')
    b.write_json(folder/'metadata_part_002.json',m)
    np.save(folder/m['eeg_file'],data)
    b.write_json(folder/m['events_file'],b.read_json(folder/'events.json'))
    before={p.relative_to(folder.parent).as_posix():b.digest(p) for p in folder.parent.rglob('*') if p.is_file()}
    result=q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings)
    assert len(result['recordings'])==2
    packs=list((tmp_path/'eegqc').glob('recording-*'))
    assert all(len(list(p.rglob('*.edf')))==1 for p in packs)
    sessions=[b.read_json(next(p.rglob('session.json'))) for p in packs]
    assert {s['source_part'] for s in sessions}=={1,2}
    assert next(s for s in sessions if s['source_part']==2)['recording_status']=='interrupted'
    assert {p.relative_to(folder.parent).as_posix():b.digest(p) for p in folder.parent.rglob('*') if p.is_file()}==before


def test_drop_or_duplicate_samples_not_declared_continuous(tmp_path):
    folder,data,settings=fixture(tmp_path)
    data[0,1500:]+=1
    np.save(folder/'continuous_eeg.npy',data)
    with pytest.raises(b.BidsExportError,match='跳变'):
        q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings)


def test_failed_validation_keeps_sealed_package_and_retries_same_uuid(tmp_path,monkeypatch):
    folder,_,settings=fixture(tmp_path)
    def failed(root):raise b.BidsExportError('validator unavailable')
    monkeypatch.setattr(b,'validate_dataset',failed)
    with pytest.raises(b.BidsExportError,match='validator unavailable'):
        q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings,validate=True)
    pack=next((tmp_path/'eegqc').glob('recording-*'))
    assert b.read_json(pack/'code/validation_status.json')['official_validation']=='FAILED'
    result=q.export_recording(folder,tmp_path/'eegqc',protocol='v2',settings=settings)
    assert result['recordings'][0]['status']=='EXISTS_VERIFIED'
    assert len(list((tmp_path/'eegqc').glob('recording-*')))==1


def test_release_never_includes_private_platform_mapping(tmp_path,monkeypatch):
    import importlib.util
    spec=importlib.util.spec_from_file_location('eegqc_release',b.ROOT/'scripts/maintenance/build_release.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    (tmp_path/'video_eeg/config').mkdir(parents=True)
    (tmp_path/'scripts').mkdir()
    b.write_json(tmp_path/'scripts/repository_layout.json',{'retired':[]})
    b.write_json(tmp_path/'video_eeg/config/eegqc.local.json',{'participant_map':'PRIVATE'})
    b.write_json(tmp_path/'video_eeg/config/eegqc_settings.example.json',{'participant_map':{}})
    monkeypatch.setattr(builder,'ROOT',tmp_path)
    names={p.name for p in builder.source_files()}
    assert 'eegqc.local.json' not in names and 'eegqc_settings.example.json' in names


def test_current_release_excludes_local_audits_and_private_config():
    import importlib.util
    spec=importlib.util.spec_from_file_location('eegqc_release_current',b.ROOT/'scripts/maintenance/build_release.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    paths={p.relative_to(builder.ROOT).as_posix() for p in builder.source_files()}
    assert 'docs/BRAINCO_POWER_AUDIT_20260912.md' not in paths
    assert 'docs/GITHUB_SYNC_20260915.md' not in paths
    assert 'docs/maintenance/GITHUB_SYNC_20261008.md' not in paths
    assert not any(p.endswith('.local.json') for p in paths)
