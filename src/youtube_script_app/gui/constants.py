"""Global non-visual constants for the GUI package."""

from __future__ import annotations

import re

from ..base import LOGGER, OUTPUT_FORMATS

# Re-export LOGGER and OUTPUT_FORMATS for convenience within the package
__all__ = [
    "LOGGER",
    "OUTPUT_FORMATS",
    "TIMESTAMP_RE",
    "BRACKET_RE",
    "DOWNLOAD_PROGRESS_RE",
    "DOWNLOAD_DEST_RE",
    "DOWNLOAD_MERGER_RE",
    "DOWNLOAD_ALREADY_RE",
    "INVALID_FILENAME_CHARS_RE",
    "FILENAME_SPACES_RE",
    "COMMON_TOOL_DIRS",
    "_YTDLP_ERROR_PATTERNS",
    "_diagnose_ytdlp_error",
]

TIMESTAMP_RE = re.compile(r"^\[(\d{2}:\d{2}(?::\d{2})?)\]")
BRACKET_RE = re.compile(r"\[[^\]]+\]")
DOWNLOAD_PROGRESS_RE = re.compile(
    r"\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s+([^\s]+)"
    r"(?:\s+at\s+([^\s]+))?(?:\s+ETA\s+(\S+))?"
)
DOWNLOAD_DEST_RE = re.compile(r"\[download\]\s+Destination:\s+(.*)")
DOWNLOAD_MERGER_RE = re.compile(r"\[Merger\]\s+Merging formats into\s+\"(.+)\"")
DOWNLOAD_ALREADY_RE = re.compile(r"\[download\]\s+(.+?) has already been downloaded")
INVALID_FILENAME_CHARS_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')
FILENAME_SPACES_RE = re.compile(r"\s+")

def _windows_tool_dirs() -> tuple[str, ...]:
    try:
        import os
        import glob
        from pathlib import Path
        dirs: list[str] = []
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            for pattern in (
                r"Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin",
                r"Microsoft\WinGet\Packages\yt-dlp*\*",
                r"Microsoft\WinGet\Links",
            ):
                for match in glob.glob(os.path.join(local, pattern)):
                    try:
                        dirs.append(str(Path(match).resolve()))
                    except (OSError, ValueError):
                        dirs.append(match)
        for base in (
            r"C:\Program Files\ffmpeg\bin",
            r"C:\ffmpeg\bin",
            r"C:\Program Files\yt-dlp",
        ):
            try:
                if os.path.isdir(base):
                    dirs.append(str(Path(base).resolve()))
            except (OSError, ValueError):
                pass
        return tuple(dirs)
    except Exception:
        return ()


import sys as _sys
COMMON_TOOL_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
    *(_windows_tool_dirs() if _sys.platform == "win32" else ()),
)

_YTDLP_ERROR_PATTERNS: list[tuple[str, str]] = [
    ("operation not permitted", "Accès aux cookies refusé par macOS. Va dans Réglages Système → Confidentialité → Accès complet au disque et ajoute Terminal (ou l'app). Ou utilise Chrome/Firefox à la place de Safari."),
    ("errno 1", "Accès aux cookies refusé par macOS. Va dans Réglages Système → Confidentialité → Accès complet au disque et ajoute Terminal (ou l'app). Ou utilise Chrome/Firefox à la place de Safari."),
    ("cookies.binarycookies", "Accès aux cookies Safari refusé par macOS. Utilise Chrome ou Firefox à la place, ou accorde l'accès complet au disque dans Réglages Système → Confidentialité."),
    ("only images are available", "YouTube requiert un PO Token pour cette vidéo. Installe Node.js (https://nodejs.org) pour résoudre le challenge, ou configure des cookies de navigateur."),
    ("po-token", "YouTube requiert un PO Token. Installe Node.js ou configure yt-dlp avec des cookies de navigateur."),
    ("requested format is not available", "Le format vidéo demandé n'est pas disponible pour cette vidéo. Essaie un autre format."),
    ("this video is available to this channel's members", "Cette vidéo est réservée aux membres de la chaîne."),
    ("members only", "Cette vidéo est réservée aux membres de la chaîne."),
    ("private video", "Cette vidéo est privée."),
    ("video unavailable", "Cette vidéo n'est pas disponible dans votre région ou a été supprimée."),
    ("http error 403", "Accès refusé par YouTube (HTTP 403). La vidéo est peut-être géo-bloquée."),
    ("sign in to confirm", "YouTube demande une connexion pour accéder à cette vidéo."),
    ("this video has been removed", "Cette vidéo a été supprimée."),
]


def _diagnose_ytdlp_error(stderr_lines: list[str]) -> str:
    combined = " ".join(stderr_lines).lower()
    for pattern, message in _YTDLP_ERROR_PATTERNS:
        if pattern in combined:
            return message
    for line in reversed(stderr_lines):
        if line.startswith("ERROR:"):
            return line.removeprefix("ERROR:").strip()
    return "Le téléchargement a échoué."
