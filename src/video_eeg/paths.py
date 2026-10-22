"""Resource paths shared by the src layout and legacy flat safety patches."""
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent if PACKAGE_ROOT.parent.name == 'src' else PACKAGE_ROOT.parent
# These immutable resources retain their paths, hashes and persisted references.
CONFIG_DIR = PROJECT_ROOT / 'video_eeg' / 'config'
