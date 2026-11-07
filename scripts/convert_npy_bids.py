"""Compatibility entry; implementation lives entirely in bids-convert."""
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[2] / 'BIDS-convert' / 'convert.py'
if not _path.is_file():
    raise SystemExit('Converter not found. Run RUNME.bat in the separate BIDS-convert directory: '+str(_path.parent))
_spec = importlib.util.spec_from_file_location('standalone_bids_convert', _path)
_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tool)
convert = _tool.convert
main = _tool.main

if __name__ == '__main__':
    raise SystemExit(main())
