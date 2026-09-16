"""Export a video/label table; Session membership comes from manifests, not old bank metadata."""
from pathlib import Path
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from video_eeg.experiment.ready_question_runner import load_questions
from video_eeg.utils.session_protocol import SessionManifest


def main():
    config = ROOT / 'video_eeg/config'
    bank = load_questions(config / 'complete_questions_20260908/question_bank.json')
    materials = json.loads((config/'materials_manifest.json').read_text(encoding='utf-8'))
    current = {e.video_path:e for e in SessionManifest.load(config/'session_manifest.csv', session_count=17).entries}
    with (config/'session_manifest_emotion_v1.csv').open(encoding='utf-8-sig',newline='') as handle:
        v2 = {r['original_id']:r['session_id'] for r in csv.DictReader(handle) if r['trial_type']=='ordinary'}
    rows = []
    for item in materials['files']:
        name = Path(item['path']).name
        q = bank.get(name, {})
        entry = current.get(name)
        row = dict(video_file=name, video_sha256=item['sha256'], video_bytes=item['bytes'],
            formal_eligible=entry is not None, v1_session=entry.session_id if entry else '',
            v2_session=v2.get(entry.video_id,'') if entry else '',
            duration_sec=entry.video_duration_sec if entry else '',
            duration_bucket=entry.duration_bucket if entry else '', has_question=bool(q),
            question_status=q.get('status','missing'), review_status=q.get('review_status',''),
            source=q.get('source',''), question=q.get('question',''),
            **{f'option_{k}':q.get('options',{}).get(k,'') for k in 'ABCD'}, answer=q.get('answer',''))
        rows.append(row)
    target = config/'video_question_labels.csv'
    with target.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    print(f'Exported {len(rows)} video labels, {sum(r["has_question"] for r in rows)} questions: {target}')


if __name__ == '__main__': main()
