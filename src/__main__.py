"""Run the same source CLI as main.py without installing this project."""
from pathlib import Path
import sys

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from video_eeg.cli import main
    raise SystemExit(main())
