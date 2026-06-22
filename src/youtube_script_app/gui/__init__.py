"""GUI package for the YouTube script application."""

import os
import shutil
import subprocess
import webbrowser
from tkinter import messagebox

from ..core import lower_third, subtitle_renderer
from ..video import renderer as video_renderer
from ..settings import DOWNLOAD_LOGO_PLACEHOLDER
from ..base import generate_transcript_with_format
from ..downloads import utils as download_utils
from .constants import COMMON_TOOL_DIRS

from .app import TranscriptApp, main

__all__ = ["TranscriptApp", "main"]
