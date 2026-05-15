"""Run the command-line interface with ``python -m youtube_script_app``."""

from __future__ import annotations

import sys

from .base import main


if __name__ == "__main__":
    sys.exit(main())
