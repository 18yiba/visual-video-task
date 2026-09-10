from __future__ import annotations

from pathlib import Path
import pyglet


win32_path = Path(pyglet.__file__).resolve().parent / "font" / "win32.py"
text = win32_path.read_text(encoding="utf-8")
old = "self._data = (ctypes.c_byte * (4 * width * height))()"
new = "self._data = (ctypes.c_ubyte * (4 * width * height))()"

if old in text:
    backup_path = win32_path.with_suffix(".py.bak")
    if not backup_path.exists():
        backup_path.write_text(text, encoding="utf-8")
    win32_path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"patched pyglet font backend: {win32_path}")
elif new in text:
    print(f"pyglet font backend already patched: {win32_path}")
else:
    raise RuntimeError(f"Could not find expected pyglet patch target in {win32_path}")
