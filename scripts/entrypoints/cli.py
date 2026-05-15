"""PyInstaller entry point for the CLI build."""

from __future__ import annotations

import sys

from youtube_script_app.base import main


if __name__ == "__main__":
    sys.exit(main())
