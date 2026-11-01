"""Convert one historical Neuracle recording to a separate verified EDF copy."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def convert(source, output, apply=False):
    import numpy as np
    from video_eeg.storage.neuracle_edf import profile, write_edf, read_edf
    from video_eeg.utils.bids_export import no_links
    source, output = no_links(source), no_links(output)
    if source == output or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError('Output must be separate from the source recording tree.')
    if output.exists():
        raise ValueError('Output already exists; choose a new directory, never overwrite.')
    meta_path = no_links(source / 'metadata.json')
    m = json.loads(meta_path.read_text(encoding='utf-8-sig'))
    if m.get('device_type') != 'neuracle' or not m.get('local_eeg_recorded'):
        raise ValueError('Requires a locally saved Neuracle recording.')
    filename = m.get('eeg_file', '')
    if not filename or Path(filename).name != filename or Path(filename).suffix != '.npy':
        raise ValueError('Expected a local NPY filename in metadata.')
    raw = no_links(source / filename)
    f = m.get('neuracle_forwarding') or {}
    p = profile(f)
    sf = float(m['sfreq'])
    rates = f.get('saved_channel_sampling_rates_hz') or f.get('channel_sampling_rates_hz')
    if not rates or len(rates) != len(p['channel_names']) or any(float(r) != sf for r in rates):
        raise ValueError('Mixed or unknown sampling rates require a separate audit; conversion stopped.')
    data = np.load(raw, mmap_mode='r', allow_pickle=False)
    if data.dtype != np.dtype('float32') or data.ndim != 2 or data.shape != (m['n_channels'], m['sample_count']) or data.shape[0] != len(p['channel_names']):
        raise ValueError('NPY shape disagrees with recorded channel/sample counts.')
    if m.get('trigger_channel_index') != p['trigger_channel_index']:
        raise ValueError('Trigger index differs between metadata and forwarding contract.')
    started = m.get('recording_started_at')
    if not started:
        raise ValueError('Missing recording_started_at; do not infer start time from a filename.')
    segments_path = no_links(source / 'eeg_segments.json')
    segments = json.loads(segments_path.read_text(encoding='utf-8-sig'))
    selected = [s for s in segments['segments'] if s.get('part') == m.get('eeg_part')]
    if len(selected) != 1 or any(selected[0].get(k) != m.get(k) for k in ('eeg_file', 'sample_count', 'n_channels', 'sfreq')):
        raise ValueError('Segment manifest disagrees with metadata.')
    if selected[0].get('status') != 'finalized':
        raise ValueError('Recording segment is not finalized; stop acquisition before conversion.')
    from datetime import datetime
    datetime.fromisoformat(started)
    report = dict(source_file=filename, samples=data.shape[1], channels=data.shape[0], sfreq=sf,
                  duration_sec=data.shape[1]/sf, units_verified=False,
                  termination_reason=selected[0].get('termination_reason'), bids_validation='NOT_RUN')
    if not apply:
        return dict(report, status='preview; no files written')
    events_name = m.get('events_file', 'events.json')
    if Path(events_name).name != events_name:
        raise ValueError('Unsafe events filename.')
    events = no_links(source / events_name)
    event_bytes = events.read_bytes()
    if not isinstance(json.loads(event_bytes), list):
        raise ValueError('events.json must contain an event list.')
    hashes = {x.name: sha256(x) for x in (raw, meta_path, segments_path, events)}
    output.mkdir(parents=True, exist_ok=False)
    # On failure, preserve the partial output for audit; no source writes or deletion.
    edf_path = output / 'continuous_eeg.edf'
    details = write_edf(edf_path, data, sf, started, p)
    derived = copy.deepcopy(m)
    derived.update(eeg_file=edf_path.name, eeg_format='EDF', native_edf_profile=p,
                   conversion_source_sha256=hashes, conversion_kind='historical_neuracle_npy_copy')
    derived['conversion_scope'] = 'One signal segment and its events only; original Session behavior logs remain in sourcedata.'
    derived['conversion_source_segment'] = selected[0]
    derived['conversion_source_session_completed'] = segments.get('completed')
    restored = read_edf(edf_path, derived)
    import edfio
    headers = edfio.read_edf(edf_path)
    errors = []
    for i, signal in enumerate(headers.signals):
        step = (signal.physical_max - signal.physical_min) / (signal.digital_max - signal.digital_min)
        error = float(np.max(np.abs(restored[i] - data[i])))
        if error > step * .501 + 1e-9:
            raise ValueError('EDF round-trip quantization check failed for ' + signal.label)
        errors.append(error)
    trigger = p['trigger_channel_index']
    if not np.array_equal(restored[trigger], data[trigger]):
        raise ValueError('TRG codes changed during conversion.')
    if hashes != {x.name: sha256(x) for x in (raw, meta_path, segments_path, events)}:
        raise ValueError('Source changed during conversion; output is not verified.')
    (output / events_name).write_bytes(event_bytes)
    derived['edf_conversion'] = dict(details, max_absolute_errors=errors, trigger_exact=True)
    (output / 'metadata.json').write_text(json.dumps(derived, ensure_ascii=False, indent=2), encoding='utf-8')
    report.update(status='verified_edf_copy', source_sha256=hashes, edf_sha256=sha256(edf_path),
                  max_absolute_errors=errors, trigger_exact=True)
    (output / 'conversion_receipt.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path, help='One original timestamp recording directory')
    parser.add_argument('--output', required=True, type=Path, help='New independent output directory')
    parser.add_argument('--apply', action='store_true', help='Write verified EDF; otherwise preview only')
    args = parser.parse_args()
    try:
        print(json.dumps(convert(args.source, args.output, args.apply), ensure_ascii=False, indent=2))
    except Exception as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
