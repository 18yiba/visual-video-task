"""Create a readable question audit table without altering the source bank."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    folder = ROOT / 'video_eeg/config/complete_questions_20260908'
    questions = json.loads((folder / 'question_bank.json').read_text(encoding='utf-8-sig'))['questions']
    fields = ['video_file', 'video_id', 'session_id', 'status', 'review_status', 'source',
              'question', 'option_A', 'option_B', 'option_C', 'option_D', 'answer']
    with (folder / 'questions_audit.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for q in questions:
            row = {k: q.get(k, '') for k in fields}
            row.update({f'option_{k}': q['options'][k] for k in 'ABCD'})
            writer.writerow(row)
    print(f'Exported {len(questions)} question rows.')


if __name__ == '__main__':
    main()
