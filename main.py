"""Source-only entry point; validation uses the Python 3.12 standard library."""
from pathlib import Path
import sys

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
    from video_eeg.cli import main
    raise SystemExit(main())
