"""Pure behavioral Image_B rating entry point with no EEG or external markers."""

from __future__ import annotations

from psychopy_image_b_experiment import main as _shared_main


def main() -> int:
    return _shared_main(behavior_only=True)


if __name__ == "__main__":
    raise SystemExit(main())
