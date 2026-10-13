"""Export sealed single-recording EDF/BIDS packages without changing native records."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_eeg.utils import bids_export as b
from video_eeg.utils import eegqc_export as q


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--protocol', required=True, choices=('v1', 'v2', 'v3'))
    parser.add_argument('--config', help='Private local platform/device configuration; optional for v3 native EDF snapshots')
    parser.add_argument('--no-validate', action='store_true', help='Export only; never mark as validated')
    args = parser.parse_args()
    if not args.config and args.protocol != 'v3':
        parser.error('v1/v2 require --config')
    settings = q.load_settings(args.config) if args.config else {}
    directories = b.discover(args.source)
    if not directories:
        parser.error('No saved metadata.json recordings found')
    errors = []
    for directory in directories:
        try:
            print(json.dumps(q.export_recording(directory, args.output, protocol=args.protocol,
                  settings=settings, validate=not args.no_validate), ensure_ascii=False), flush=True)
        except Exception as exc:
            errors.append(str(exc))
            print(str(directory)+': '+str(exc), file=sys.stderr, flush=True)
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
