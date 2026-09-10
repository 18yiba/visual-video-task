"""Read-only corpus/question audit. Run after copying materials to another PC."""
from pathlib import Path
import argparse
import hashlib
import json
from collections import Counter
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video_eeg.experiment.ready_question_runner import load_questions, question_path
from video_eeg.experiment.video_runner import load_config
from video_eeg.utils.session_protocol import SessionManifest, build_video_question_schedule
from video_eeg.utils.video_library import load_video_library


def audit(config_path, *, require_materials=False):
    config = load_config(config_path)
    config['_project_dir'] = str(ROOT)
    bank_path = question_path(config)
    questions = load_questions(bank_path)
    session_count = int(config['protocol'].get('num_sessions', 17))
    manifest = SessionManifest.load(ROOT / config['protocol']['session_manifest_path'], session_count=session_count)
    library = load_video_library(config)
    formal = {e.video_path for e in manifest.entries}
    missing_questions = sorted(formal - set(questions))
    missing_files = [p for p in sorted(formal) if not (library.root / p).is_file()]
    sessions = []
    for session in range(1, session_count + 1):
        assets = manifest.session_assets(session)
        schedule = build_video_question_schedule(assets, questions, task_count=18, random_seed=session)
        assert len({q['video_id'] for q in schedule}) == 18
        sessions.append(dict(session=session, videos=len(assets),
                             questions=sum(a.rel_path in questions for a in assets), checks=len(schedule)))
    report = dict(session_count=session_count, question_count=len(questions), formal_count=len(formal),
        formal_with_questions=len(formal & set(questions)), missing_questions=missing_questions,
        review_status_counts=dict(Counter(q['status'] for q in questions.values())),
        question_bank_sha256=hashlib.sha256(bank_path.read_bytes()).hexdigest(),
        video_root=str(library.root), missing_video_count=len(missing_files),
        missing_video_examples=missing_files[:20], sessions=sessions,
        complete_question_coverage=not missing_questions)
    if require_materials and missing_files:
        raise RuntimeError(f'Missing {len(missing_files)} formal videos in {library.root}; examples: {missing_files[:5]}')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'video_eeg/config/video_config.yaml')
    parser.add_argument('--require-materials', action='store_true')
    parser.add_argument('--require-full-coverage', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = audit(args.config, require_materials=args.require_materials)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text)
    return 1 if args.require_full_coverage and not report['complete_question_coverage'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
