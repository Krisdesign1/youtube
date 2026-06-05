"""Tkinter GUI for generating YouTube video transcripts."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, scrolledtext
from tkinter import ttk
from typing import List, Optional

from PIL import Image, ImageTk

from .downloads import history as history_store
from .downloads import utils as download_utils
from .core import lower_third, subtitle_renderer
from .base import (
    LOGGER,
    OUTPUT_FORMATS,
    TranscriptRetrievalError,
    VideoIdExtractionError,
    export_most_viewed_csv,
    extract_video_id,
    format_most_viewed_moments,
    generate_transcript_with_format,
    seconds_to_timestamp,
)
from .settings import (
    DOWNLOAD_LOGO_PLACEHOLDER,
    coerce_bool,
    default_gui_settings,
    load_gui_settings,
    normalize_gui_settings,
    save_gui_settings,
)
from .video import renderer as video_renderer
from .video import presets as video_presets
from .video.logo_config import LogoConfig

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


FILENAME_SPACES_RE = re.compile(r"\s+")
COMMON_TOOL_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)

THEME = {
    "bg": "#f7f8fc",
    "bg_alt": "#edf0f8",
    "card": "#ffffff",
    "shadow": "#d4daea",
    "text": "#0d0d1a",
    "muted": "#5a6482",
    "accent": "#5b5bd6",
    "accent_dark": "#4444b8",
    "secondary": "#7c3aed",
    "success": "#059669",
    "danger": "#dc2626",
    "border": "#dde2f0",
    "select": "#ede9fe",
    "hero": "#1a1040",
    "hero_mid": "#261550",
    "hero_text": "#eeeeff",
    "hero_muted": "#a5b4fc",
    "hero_stripe": "#6366f1",
    "hero_stripe_alt": "#7c3aed",
    "hero_stripe_hot": "#a855f7",
    "hero_stripe_dark": "#4f46e5",
    "white": "#ffffff",
    "button_hover": "#e0e4f8",
    "button_disabled": "#eaecf6",
    "primary_disabled": "#9b9bd4",
    "primary_disabled_text": "#e8e8f5",
    "secondary_hover": "#f0eeff",
    "secondary_disabled": "#f5f6fb",
    "secondary_disabled_text": "#9aa0be",
    "soft_primary": "#ebebff",
    "soft_primary_hover": "#ddddf8",
    "soft_primary_disabled": "#f0f0ff",
    "subtle": "#f4f5fb",
    "subtle_hover": "#e8eaf6",
    "placeholder_bg": "#f3f1ff",
    "placeholder_text": "#7b82aa",
    "canvas_grid": "#d8deeb",
    "disabled_outline": "#a8b0c2",
    "disabled_fill": "#e5e7ef",
    "status_error": "#b91c1c",
    "timestamp": "#7b8aa8",
}

SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 16,
    "lg": 24,
    "xl": 32,
    "2xl": 48,
}

BUTTON_VARIANTS = {
    "primary": "Primary.TButton",
    "secondary": "Secondary.TButton",
    "soft": "SoftPrimary.TButton",
    "tertiary": "Subtle.TButton",
    "link": "Link.TButton",
}


class _CanvasProgress(tk.Canvas):
    """Canvas-based progress bar: text overlay, pulse animation, colour states, segments."""

    _PULSE_STEP = 6
    _PULSE_MS = 22

    def __init__(
        self,
        parent,
        *,
        height: int = 20,
        palette: dict,
        font_family: str = "Arial",
        show_text: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(parent, height=height, highlightthickness=0, bd=0, **kwargs)
        self._pal = palette
        self._ff = font_family
        self._value = 0.0
        self._maximum = 100.0
        self._mode = "determinate"
        self._color_state = "normal"
        self._show_text = show_text and height >= 14
        self._pulse_x = 0.0
        self._pulse_job: str | None = None
        self._seg: tuple[int, int, float] | None = None
        self.bind("<Configure>", lambda _e: self._draw())

    # --- public API (mirrors ttk.Progressbar) --------------------------------

    def configure(self, **kwargs):
        value = kwargs.pop("value", None)
        maximum = kwargs.pop("maximum", None)
        mode = kwargs.pop("mode", None)
        if kwargs:
            super().configure(**kwargs)
        if maximum is not None:
            self._maximum = max(1.0, float(maximum))
        if mode is not None:
            if mode == "indeterminate" and self._mode != "indeterminate":
                self._mode = "indeterminate"
                self._start_pulse()
            elif mode == "determinate":
                self._stop_pulse()
                self._mode = "determinate"
        if value is not None:
            self._value = float(value)
            if self._mode == "indeterminate":
                self._stop_pulse()
                self._mode = "determinate"
        self._draw()

    config = configure

    def set_state(self, state: str) -> None:
        """Change colour: 'normal' (blue), 'success' (green), 'error' (red)."""
        self._color_state = state
        self._draw()

    def set_segments(self, completed: int, total: int, current_pct: float) -> None:
        """Segmented overall view: green=done, blue=active, grey=pending."""
        if self._mode == "indeterminate":
            self._stop_pulse()
            self._mode = "determinate"
        self._seg = (int(completed), int(total), float(current_pct))
        self._draw()

    def clear_segments(self) -> None:
        self._seg = None
        self._draw()

    # --- drawing internals ---------------------------------------------------

    def _bar_color(self) -> str:
        if self._color_state == "success":
            return self._pal["success"]
        if self._color_state == "error":
            return self._pal["danger"]
        return self._pal["accent"]

    def _draw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2:
            self.after(40, self._draw)
            return
        self.create_rectangle(0, 0, w, h, fill=self._pal["bg_alt"], outline="")
        if self._mode == "indeterminate":
            self._draw_pulse(w, h)
        elif self._seg is not None:
            self._draw_segments(w, h)
        else:
            self._draw_simple(w, h)
        if self._show_text and self._mode != "indeterminate":
            self._draw_text(w, h)

    def _draw_simple(self, w: int, h: int) -> None:
        pct = min(1.0, self._value / self._maximum)
        fw = int(w * pct)
        if fw > 0:
            self.create_rectangle(0, 0, fw, h, fill=self._bar_color(), outline="")

    def _draw_segments(self, w: int, h: int) -> None:
        completed, total, current_pct = self._seg
        if total <= 0:
            return
        gap = 2 if total > 1 else 0
        seg_w = max(1.0, (w - gap * (total - 1)) / total)
        for i in range(total):
            x0 = int(i * (seg_w + gap))
            x1 = int(x0 + seg_w)
            if i < completed:
                self.create_rectangle(x0, 0, x1, h, fill=self._pal["success"], outline="")
            elif i == completed:
                self.create_rectangle(x0, 0, x1, h, fill=self._pal["border"], outline="")
                fw = int((x1 - x0) * current_pct / 100.0)
                if fw > 0:
                    self.create_rectangle(x0, 0, x0 + fw, h, fill=self._pal["accent"], outline="")
            else:
                self.create_rectangle(x0, 0, x1, h, fill=self._pal["border"], outline="")

    def _draw_text(self, w: int, h: int) -> None:
        if self._seg is not None:
            completed, total, current_pct = self._seg
            pct = ((completed + current_pct / 100.0) / max(1, total)) * 100.0
        else:
            pct = min(100.0, (self._value / self._maximum) * 100.0)
        text = f"{pct:.0f}%"
        fg = "#ffffff" if pct > 50 else self._pal["text"]
        self.create_text(
            w // 2, h // 2,
            text=text,
            fill=fg,
            font=(self._ff, 8, "bold"),
            anchor="center",
        )

    def _draw_pulse(self, w: int, h: int) -> None:
        pw = max(w // 3, 30)
        x0 = max(0, int(self._pulse_x - pw))
        x1 = min(w, int(self._pulse_x))
        if x1 > x0:
            self.create_rectangle(x0, 0, x1, h, fill=self._pal["accent"], outline="")

    def _start_pulse(self) -> None:
        self._pulse_x = 0.0
        self._stop_pulse()
        self._pulse_job = self.after(self._PULSE_MS, self._tick_pulse)

    def _stop_pulse(self) -> None:
        if self._pulse_job:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None

    def _tick_pulse(self) -> None:
        w = self.winfo_width()
        if w > 1:
            self._pulse_x += self._PULSE_STEP
            if self._pulse_x > w + w // 3:
                self._pulse_x = 0.0
            self._draw()
        if self._mode == "indeterminate":
            self._pulse_job = self.after(self._PULSE_MS, self._tick_pulse)


class TranscriptApp:
    """Simple GUI wrapper around the CLI transcript generator."""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("Générateur de script YouTube")
        master.minsize(900, 600)
        master.resizable(True, True)

        self.style = ttk.Style(master)
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")
        self._apply_blue_theme()

        self.url_var = tk.StringVar()
        self.languages_var = tk.StringVar()
        self.output_format_var = tk.StringVar(value=OUTPUT_FORMATS["text"])
        self.most_viewed_var = tk.BooleanVar(value=True)
        self.most_viewed_count_var = tk.IntVar(value=5)
        self.clip_duration_var = tk.IntVar(value=60)
        self.video_format_var = tk.StringVar(value="mp4")
        self.download_preset_lookup = video_presets.preset_label_lookup()
        self.download_preset_var = tk.StringVar(value="Personnalisé")
        self.download_aspect_ratio_lookup = {
            "Normal 16:9": "landscape",
            "Short 9:16": "shorts",
        }
        self.download_aspect_ratio_var = tk.StringVar(value="Normal 16:9")
        self.download_logo_enabled_var = tk.BooleanVar(value=True)
        self.download_logo_var = tk.StringVar()
        self.download_logo_size_mode_lookup = {
            "Taille relative": "relative",
            "Taille originale (max 30%)": "original",
        }
        self.download_logo_size_mode_var = tk.StringVar(value="Taille relative")
        self.download_logo_size_var = tk.IntVar(
            value=download_utils.DEFAULT_LOGO_SCALE_PERCENT
        )
        self.download_logo_size_label_var = tk.StringVar(
            value=self._download_logo_size_label(
                download_utils.DEFAULT_LOGO_SCALE_PERCENT
            )
        )
        self.download_logo_width_ratio_var = tk.DoubleVar(
            value=download_utils.DEFAULT_LOGO_WIDTH_RATIO
        )
        self.download_logo_x_ratio_var = tk.DoubleVar(
            value=download_utils.DEFAULT_LOGO_X_RATIO
        )
        self.download_logo_y_ratio_var = tk.DoubleVar(
            value=download_utils.DEFAULT_LOGO_Y_RATIO
        )
        self.download_logo_opacity_var = tk.IntVar(value=100)
        self.download_logo_opacity_label_var = tk.StringVar(value="100%")
        self.download_logo_duration_var = tk.IntVar(value=0)
        self.download_shorts_blur_var = tk.BooleanVar(value=True)
        self.download_logo_position_var = tk.StringVar(value="Haut droit")
        self.download_logo_position_lookup = {
            "Haut gauche": "top-left",
            "Haut centre": "top",
            "Haut droit": "top-right",
            "Centre gauche": "center-left",
            "Centre": "center",
            "Centre droit": "center-right",
            "Bas gauche": "bottom-left",
            "Bas centre": "bottom",
            "Bas droit": "bottom-right",
        }
        self.download_subtitles_enabled_var = tk.BooleanVar(value=True)
        self.download_subtitle_offset_var = tk.IntVar(value=-200)
        self.download_subtitle_style_lookup = {
            "Viral mot par mot": "word",
            "Impact TikTok": "impact",
            "Moderne blanc": "modern",
            "Cinéma": "cinema",
            "Boîte noire": "box",
            "Minimal": "minimal",
        }
        self.download_subtitle_style_var = tk.StringVar(value="Viral mot par mot")
        self.download_video_effect_lookup = {
            "Aucun": "none",
            "Noir et blanc": "black_white",
            "Contraste fort": "contrast",
            "Cinéma sombre": "cinematic",
            "Vintage": "vintage",
        }
        self.download_video_effect_var = tk.StringVar(value="Aucun")
        self.download_intro_outro_enabled_var = tk.BooleanVar(value=False)
        self.download_intro_outro_hold_var = tk.DoubleVar(value=1.5)
        self.download_intro_outro_bg_color_var = tk.StringVar(value="#000000")
        self.download_intro_outro_text_color_var = tk.StringVar(value="#FFFFFF")
        self.download_progress_bar_enabled_var = tk.BooleanVar(value=False)
        self.download_animated_watermark_enabled_var = tk.BooleanVar(value=False)
        self.download_lower_third_enabled_var = tk.BooleanVar(value=False)
        self.download_lower_third_position_var = tk.StringVar(value="Bas")
        self.download_lower_third_name_var = tk.StringVar(value="")
        self.download_lower_third_tagline_var = tk.StringVar(value="")
        self.download_lower_third_subscribe_var = tk.BooleanVar(value=True)
        self.download_lower_third_bg_color_var = tk.StringVar(
            value=lower_third.DEFAULT_BG_COLOR
        )
        self.download_lower_third_accent_color_var = tk.StringVar(
            value=lower_third.DEFAULT_ACCENT_COLOR
        )
        self.download_lower_third_interval_var = tk.IntVar(
            value=lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS
        )
        self.download_lower_third_interval_label_var = tk.StringVar(
            value=f"{lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS}s"
        )
        self.download_lower_third_display_duration_var = tk.IntVar(
            value=lower_third.DEFAULT_DISPLAY_DURATION_SECONDS
        )
        self.download_lower_third_display_duration_label_var = tk.StringVar(
            value=f"{lower_third.DEFAULT_DISPLAY_DURATION_SECONDS}s"
        )
        self.download_lower_third_title_scale_var = tk.IntVar(value=100)
        self.download_lower_third_title_scale_label_var = tk.StringVar(value="100%")
        self.download_lower_third_tagline_scale_var = tk.IntVar(value=100)
        self.download_lower_third_tagline_scale_label_var = tk.StringVar(value="100%")
        self.download_lower_third_subscribe_text_var = tk.StringVar(value="Abonnez-vous")
        self.download_lower_third_bg_opacity_var = tk.IntVar(value=86)
        self.download_lower_third_bg_opacity_label_var = tk.StringVar(value="86%")
        self.download_lower_third_valign_var = tk.StringVar(value="Bas")
        self.config_summary_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Prêt.")
        self.meta_var = tk.StringVar(value="")
        self.stats_var = tk.StringVar(value="Lignes: 0 | Caractères: 0")
        self.download_summary_var = tk.StringVar(
            value="Aucun téléchargement en cours."
        )
        self.download_detail_var = tk.StringVar(value="")
        self.download_phase_var = tk.StringVar(value="Étape: en attente.")
        self.last_most_viewed_moments = []
        self.last_transcript_chunks: List[dict] = []
        self.last_url = ""
        self.options_visible = False
        self._moment_excerpt_labels = []
        self._moment_action_buttons = []
        self.download_process = None
        self.download_queue = []
        self.download_active = False
        self.download_cancel = threading.Event()
        self.download_total = 0
        self.download_completed = 0
        self.download_last_percent_logged = -1
        self.download_last_size = ""
        self.last_download_dir = ""
        self.last_downloaded_file = ""
        self.video_title_cache: dict[str, str] = {}
        self.download_history_lock = threading.Lock()
        self.download_history_path = Path.home() / ".youtube-script" / "download_history.json"
        self.download_history = self._load_download_history()
        self.gui_settings_path = Path.home() / ".youtube-script" / "gui_settings.json"
        self.gui_settings = self._load_gui_settings()
        self._apply_gui_settings(self.gui_settings)
        self.download_thread: threading.Thread | None = None
        self.download_log_visible = False
        self.busy = False
        self._moment_mini_bars: dict[int, _CanvasProgress] = {}
        self._current_download_card_index: int | None = None
        self.ytdlp_cookies_browser_var = tk.StringVar(value="")
        self.cancel_event = threading.Event()
        self.generation_thread: threading.Thread | None = None
        self.preview_thread: threading.Thread | None = None
        self.current_job_id = 0
        self.output_format_lookup = dict(OUTPUT_FORMATS)
        self.output_format_reverse = {label: key for key, label in OUTPUT_FORMATS.items()}

        self._build_layout(master)
        self._refresh_download_history_view()
        self.url_var.trace_add(
            "write", lambda *args: self.master.after_idle(self._update_generate_state)
        )
        self.download_aspect_ratio_var.trace_add(
            "write", self._on_download_aspect_change
        )
        self.download_preset_var.trace_add("write", self._on_download_preset_change)
        self.video_format_var.trace_add("write", self._on_download_preferences_change)
        self.clip_duration_var.trace_add("write", self._on_download_preferences_change)
        self.download_logo_enabled_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_logo_position_var.trace_add(
            "write", self._on_download_logo_position_change
        )
        self.download_logo_size_mode_var.trace_add(
            "write", self._on_download_logo_size_mode_change
        )
        self.download_logo_size_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_logo_width_ratio_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_logo_x_ratio_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_logo_y_ratio_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_logo_opacity_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_subtitles_enabled_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_subtitle_style_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_video_effect_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_intro_outro_enabled_var.trace_add(
            "write", self._on_value_add_change
        )
        self.download_progress_bar_enabled_var.trace_add(
            "write", self._on_value_add_change
        )
        self.download_animated_watermark_enabled_var.trace_add(
            "write", self._on_value_add_change
        )
        self.download_lower_third_enabled_var.trace_add(
            "write", self._on_lower_third_change
        )
        self.download_lower_third_position_var.trace_add(
            "write", self._on_lower_third_change
        )
        self.download_lower_third_name_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_lower_third_name_var.trace_add(
            "write", lambda *_: self._redraw_lower_third_preview()
        )
        self.download_lower_third_tagline_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_lower_third_tagline_var.trace_add(
            "write", lambda *_: self._redraw_lower_third_preview()
        )
        self.download_lower_third_subscribe_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_lower_third_subscribe_var.trace_add(
            "write", lambda *_: self._redraw_lower_third_preview()
        )
        self.download_lower_third_bg_color_var.trace_add(
            "write", self._on_lower_third_color_change
        )
        self.download_lower_third_accent_color_var.trace_add(
            "write", self._on_lower_third_color_change
        )
        self.download_lower_third_interval_var.trace_add(
            "write", self._on_lower_third_timing_change
        )
        self.download_lower_third_display_duration_var.trace_add(
            "write", self._on_lower_third_timing_change
        )
        self.download_lower_third_title_scale_var.trace_add(
            "write", self._on_lower_third_preview_change
        )
        self.download_lower_third_tagline_scale_var.trace_add(
            "write", self._on_lower_third_preview_change
        )
        self.download_lower_third_subscribe_text_var.trace_add(
            "write", self._on_lower_third_preview_change
        )
        self.download_lower_third_bg_opacity_var.trace_add(
            "write", self._on_lower_third_preview_change
        )
        self.download_lower_third_valign_var.trace_add(
            "write", self._on_lower_third_preview_change
        )
        self.download_logo_entry.bind(
            "<FocusOut>", self._on_download_logo_focus_out, add="+"
        )
        self._update_generate_state()
        self._update_config_summary()
        self._bind_shortcuts()

    def _apply_blue_theme(self) -> None:
        self.palette = dict(THEME)
        self.spacing = dict(SPACING)
        self.font_family = self._pick_font_family(
            ["Avenir Next", "SF Pro Text", "SF Pro Display", "Montserrat", "Poppins", "Inter", "Segoe UI"],
            fallback="Helvetica",
        )
        self.mono_family = self._pick_font_family(
            ["Menlo", "SF Mono", "Consolas", "Monaco", "Courier New"],
            fallback="Courier New",
        )
        font_main = (self.font_family, 10)
        font_title = (self.font_family, 23, "bold")
        font_label = (self.font_family, 11, "bold")
        font_section = (self.font_family, 12, "bold")
        font_button = (self.font_family, 12, "bold")
        font_link = (self.font_family, 10, "underline")
        font_subtle = (self.font_family, 9)

        self.master.option_add("*Font", font_main)

        self.master.configure(background=self.palette["bg"])
        self.style.configure("TFrame", background=self.palette["bg"])
        self.style.configure("TLabelframe", background=self.palette["bg"])
        self.style.configure(
            "TLabelframe.Label",
            background=self.palette["bg"],
            foreground=self.palette["accent"],
            font=font_label,
        )
        self.style.configure(
            "TLabel",
            background=self.palette["bg"],
            foreground=self.palette["text"],
            font=font_main,
        )
        self.style.configure(
            "Title.TLabel",
            font=font_title,
            foreground=self.palette["accent"],
            background=self.palette["bg"],
        )
        self.style.configure(
            "Subtitle.TLabel",
            foreground=self.palette["muted"],
            background=self.palette["bg"],
            font=font_main,
        )
        self.style.configure(
            "Status.TLabel",
            foreground=self.palette["accent"],
            background=self.palette["bg"],
            font=(self.font_family, 10, "bold"),
        )
        self.style.configure(
            "Hero.TFrame",
            background=self.palette["hero"],
        )
        self.style.configure(
            "HeroTitle.TLabel",
            font=(self.font_family, 26, "bold"),
            foreground=self.palette["hero_text"],
            background=self.palette["hero"],
        )
        self.style.configure(
            "HeroSubtitle.TLabel",
            font=(self.font_family, 12),
            foreground=self.palette["hero_muted"],
            background=self.palette["hero"],
        )
        self.style.configure(
            "TButton",
            background=self.palette["bg_alt"],
            foreground=self.palette["accent"],
            padding=(self.spacing["md"] - self.spacing["xs"], 7),
            font=font_main,
        )
        self.style.map(
            "TButton",
            background=[
                ("active", self.palette["button_hover"]),
                ("disabled", self.palette["button_disabled"]),
            ],
        )
        self.style.configure(
            "Primary.TButton",
            background=self.palette["accent"],
            foreground=self.palette["white"],
            padding=(22, 13),
            font=font_button,
        )
        self.style.map(
            "Primary.TButton",
            background=[
                ("active", self.palette["accent_dark"]),
                ("disabled", self.palette["primary_disabled"]),
            ],
            foreground=[("disabled", self.palette["primary_disabled_text"])],
        )
        self.style.configure(
            "Secondary.TButton",
            background=self.palette["card"],
            foreground=self.palette["muted"],
            padding=(11, 8),
            font=font_main,
            bordercolor=self.palette["border"],
        )
        self.style.map(
            "Secondary.TButton",
            background=[
                ("active", self.palette["secondary_hover"]),
                ("disabled", self.palette["secondary_disabled"]),
            ],
            foreground=[
                ("active", self.palette["accent"]),
                ("disabled", self.palette["secondary_disabled_text"]),
            ],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=self.palette["card"],
            foreground=self.palette["text"],
            bordercolor=self.palette["border"],
        )
        self.style.configure(
            "Normal.TEntry",
            fieldbackground=self.palette["card"],
            foreground=self.palette["text"],
        )
        self.style.configure(
            "Placeholder.TEntry",
            fieldbackground=self.palette["placeholder_bg"],
            foreground=self.palette["placeholder_text"],
        )
        self.style.configure(
            "TCheckbutton",
            background=self.palette["bg"],
            foreground=self.palette["text"],
            font=font_main,
        )
        self.style.configure(
            "Card.TLabelframe",
            background=self.palette["card"],
            bordercolor=self.palette["border"],
            relief="solid",
        )
        self.style.configure(
            "Card.TLabelframe.Label",
            background=self.palette["card"],
            foreground=self.palette["accent"],
            font=font_label,
        )
        self.style.configure(
            "Card.TLabel",
            background=self.palette["card"],
            foreground=self.palette["text"],
            font=font_main,
        )
        self.style.configure(
            "CardTitle.TLabel",
            background=self.palette["card"],
            foreground=self.palette["text"],
            font=font_section,
        )
        self.style.configure(
            "CardMuted.TLabel",
            background=self.palette["card"],
            foreground=self.palette["muted"],
            font=font_main,
        )
        self.style.configure(
            "Card.TFrame",
            background=self.palette["card"],
        )
        self.style.configure(
            "CardAlt.TFrame",
            background=self.palette["bg_alt"],
        )
        self.style.configure(
            "Card.TCheckbutton",
            background=self.palette["card"],
            foreground=self.palette["text"],
            font=font_main,
        )
        self.style.configure(
            "Link.TButton",
            background=self.palette["card"],
            foreground=self.palette["accent"],
            padding=(0, 0),
            font=font_link,
            borderwidth=0,
        )
        self.style.configure(
            "SoftPrimary.TButton",
            background=self.palette["soft_primary"],
            foreground=self.palette["accent"],
            padding=(13, 9),
            font=font_main,
            bordercolor=self.palette["border"],
        )
        self.style.map(
            "SoftPrimary.TButton",
            background=[
                ("active", self.palette["soft_primary_hover"]),
                ("disabled", self.palette["soft_primary_disabled"]),
            ],
            foreground=[
                ("active", self.palette["accent_dark"]),
                ("disabled", self.palette["secondary_disabled_text"]),
            ],
        )
        self.style.configure(
            "Subtle.TButton",
            background=self.palette["subtle"],
            foreground=self.palette["muted"],
            padding=(9, 6),
            font=font_subtle,
            bordercolor=self.palette["border"],
        )
        self.style.map(
            "Subtle.TButton",
            background=[
                ("active", self.palette["subtle_hover"]),
                ("disabled", self.palette["secondary_disabled"]),
            ],
            foreground=[
                ("active", self.palette["accent"]),
                ("disabled", self.palette["secondary_disabled_text"]),
            ],
        )
        self.style.map(
            "Link.TButton",
            foreground=[("active", self.palette["accent_dark"])],
            background=[("active", self.palette["card"])],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=self.palette["card"],
            foreground=self.palette["text"],
        )
        self.style.configure(
            "Options.TNotebook",
            background=self.palette["card"],
            tabmargins=[0, 4, 0, 0],
        )
        self.style.configure(
            "Options.TNotebook.Tab",
            background=self.palette["bg_alt"],
            foreground=self.palette["muted"],
            padding=[14, 6],
            font=(self.font_family, 10),
        )
        self.style.map(
            "Options.TNotebook.Tab",
            background=[("selected", self.palette["soft_primary"])],
            foreground=[("selected", self.palette["accent"])],
        )
        self.style.configure(
            "Blue.Horizontal.TProgressbar",
            troughcolor=self.palette["bg_alt"],
            background=self.palette["accent"],
            bordercolor=self.palette["border"],
            lightcolor=self.palette["accent"],
            darkcolor=self.palette["accent_dark"],
        )
        self.style.configure(
            "Success.Horizontal.TProgressbar",
            troughcolor=self.palette["bg_alt"],
            background=self.palette["success"],
            bordercolor=self.palette["border"],
            lightcolor=self.palette["success"],
            darkcolor=self.palette["success"],
        )

    def _pick_font_family(self, candidates: List[str], *, fallback: str) -> str:
        available = set(tkfont.families(self.master))
        for name in candidates:
            if name in available:
                return name
        return fallback

    def _button(
        self,
        parent: tk.Misc,
        *,
        text: str,
        command,
        variant: str = "secondary",
        **kwargs,
    ) -> ttk.Button:
        style = BUTTON_VARIANTS.get(variant, BUTTON_VARIANTS["secondary"])
        return ttk.Button(parent, text=text, command=command, style=style, **kwargs)

    def _center_container(self) -> None:
        self.master.bind("<Configure>", self._on_root_resize)
        self._on_root_resize()

    def _on_root_resize(self, event: tk.Event | None = None) -> None:
        if not hasattr(self, "_content_container"):
            return
        width = self.master.winfo_width()
        if width <= 1:
            width = self.master.winfo_screenwidth()
        horizontal = self.spacing["md"] if width < 960 else self.spacing["lg"]
        self._content_container.configure(padding=(horizontal, self.spacing["lg"]))

    def _on_main_view_configure(self, event: tk.Event | None = None) -> None:
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

    def _on_main_canvas_configure(self, event: tk.Event) -> None:
        self.main_canvas.itemconfigure(self.main_window, width=event.width)
        self._on_root_resize()

    def _bind_main_scroll(self) -> None:
        self.main_canvas.bind_all("<MouseWheel>", self._on_main_mousewheel, add="+")
        self.main_canvas.bind_all("<Button-4>", self._on_main_mousewheel_linux, add="+")
        self.main_canvas.bind_all("<Button-5>", self._on_main_mousewheel_linux, add="+")

    def _in_nested_scroll_area(self, widget: tk.Misc | None) -> bool:
        blocked = {
            getattr(self, "output_text", None),
            getattr(self, "download_log", None),
            getattr(self, "download_history_text", None),
            getattr(self, "moments_canvas", None),
        }
        current = widget
        while current is not None:
            if current in blocked:
                return True
            current = getattr(current, "master", None)
        return False

    def _on_main_mousewheel(self, event: tk.Event) -> str | None:
        if self._in_nested_scroll_area(getattr(event, "widget", None)):
            return None
        delta = getattr(event, "delta", 0)
        if not delta:
            return None
        steps = -1 if delta > 0 else 1
        self.main_canvas.yview_scroll(steps, "units")
        return "break"

    def _on_main_mousewheel_linux(self, event: tk.Event) -> str | None:
        if self._in_nested_scroll_area(getattr(event, "widget", None)):
            return None
        num = getattr(event, "num", 0)
        if num == 4:
            self.main_canvas.yview_scroll(-1, "units")
            return "break"
        if num == 5:
            self.main_canvas.yview_scroll(1, "units")
            return "break"
        return None

    def _scroll_main_page(self, direction: int) -> str:
        self.main_canvas.yview_scroll(direction, "pages")
        return "break"

    def scroll_to_top(self, event: tk.Event | None = None) -> str:
        self.main_canvas.yview_moveto(0.0)
        return "break"

    def scroll_to_bottom(self, event: tk.Event | None = None) -> str:
        self.main_canvas.yview_moveto(1.0)
        return "break"

    def _build_layout(self, master: tk.Tk) -> None:
        master.grid_columnconfigure(0, weight=1)
        master.grid_rowconfigure(0, weight=1)

        outer = ttk.Frame(master)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)

        self.main_canvas = tk.Canvas(
            outer,
            background=self.palette["bg"],
            highlightthickness=0,
            borderwidth=0,
        )
        self.main_canvas.grid(row=0, column=0, sticky="nsew")
        self.main_scrollbar = ttk.Scrollbar(
            outer, orient="vertical", command=self.main_canvas.yview
        )
        self.main_scrollbar.grid(row=0, column=1, sticky="ns")
        self.main_canvas.configure(yscrollcommand=self.main_scrollbar.set)

        self.main_view = ttk.Frame(self.main_canvas)
        self.main_window = self.main_canvas.create_window(
            (0, 0), window=self.main_view, anchor="nw"
        )
        self.main_view.grid_columnconfigure(0, weight=1)
        self.main_view.bind("<Configure>", self._on_main_view_configure)
        self.main_canvas.bind("<Configure>", self._on_main_canvas_configure)

        container = ttk.Frame(self.main_view, padding=(24, 20))
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(6, weight=1)
        self._content_container = container
        self._center_container()
        self._bind_main_scroll()

        # Hero header — outer wrapper to allow the accent stripe at the bottom
        hero_wrapper = tk.Frame(container, bg=self.palette["hero"])
        hero_wrapper.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        hero_wrapper.grid_columnconfigure(0, weight=1)

        header_frame = tk.Frame(hero_wrapper, bg=self.palette["hero"])
        header_frame.grid(row=0, column=0, sticky="ew", padx=26, pady=(22, 18))
        header_frame.grid_columnconfigure(0, weight=1)
        header_frame.grid_columnconfigure(1, weight=0)

        # Title + badge row
        title_row = tk.Frame(header_frame, bg=self.palette["hero"])
        title_row.grid(row=0, column=0, sticky="w")
        tk.Label(
            title_row,
            text="🎬",
            bg=self.palette["hero"],
            fg=self.palette["hero_text"],
            font=(self.font_family, 22),
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        tk.Label(
            title_row,
            text="YouTube Script Studio",
            bg=self.palette["hero"],
            fg=self.palette["hero_text"],
            font=(self.font_family, 26, "bold"),
        ).grid(row=0, column=1, sticky="w")
        # "beta" pill next to title
        tk.Label(
            title_row,
            text="  STUDIO  ",
            bg=self.palette["hero_stripe"],
            fg=self.palette["white"],
            font=(self.font_family, 8, "bold"),
            padx=2,
            pady=1,
        ).grid(row=0, column=2, sticky="w", padx=(10, 0))

        tk.Label(
            header_frame,
            text="Transforme une vidéo en scripts clairs, moments clés et médias prêts à télécharger.",
            bg=self.palette["hero"],
            fg=self.palette["hero_muted"],
            font=(self.font_family, 12),
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        nav_buttons = tk.Frame(header_frame, bg=self.palette["hero"])
        nav_buttons.grid(row=0, column=1, rowspan=2, sticky="ne")
        self.scroll_top_button = self._button(
            nav_buttons,
            text="↑ Haut",
            command=self.scroll_to_top,
            variant="tertiary",
        )
        self.scroll_top_button.grid(row=0, column=0, sticky="ew")
        self.scroll_bottom_button = self._button(
            nav_buttons,
            text="↓ Bas",
            command=self.scroll_to_bottom,
            variant="tertiary",
        )
        self.scroll_bottom_button.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        # Accent stripe at the bottom of the hero
        stripe_canvas = tk.Canvas(
            hero_wrapper,
            height=4,
            highlightthickness=0,
            borderwidth=0,
        )
        stripe_canvas.grid(row=1, column=0, sticky="ew")
        stripe_colors = [
            self.palette["hero_stripe"],
            self.palette["hero_stripe_alt"],
            self.palette["hero_stripe_hot"],
            self.palette["hero_stripe"],
            self.palette["hero_stripe_dark"],
        ]

        def _draw_stripe(event: tk.Event | None = None) -> None:
            stripe_canvas.delete("all")
            w = stripe_canvas.winfo_width() or 800
            seg = max(1, w // len(stripe_colors))
            for i, color in enumerate(stripe_colors):
                stripe_canvas.create_rectangle(
                    i * seg, 0, (i + 1) * seg + 2, 4, fill=color, outline=""
                )

        stripe_canvas.bind("<Configure>", _draw_stripe)
        stripe_canvas.after(50, _draw_stripe)

        url_shadow = tk.Frame(container, bg=self.palette["shadow"])
        url_shadow.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        url_shadow.grid_columnconfigure(0, weight=1)
        url_card = tk.Frame(url_shadow, bg=self.palette["card"])
        url_card.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        url_card.grid_columnconfigure(1, weight=1)

        ttk.Label(url_card, text="Lien vidéo ou publication", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 6)
        )
        url_row = tk.Frame(url_card, bg=self.palette["card"])
        url_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16)
        url_row.grid_columnconfigure(1, weight=1)
        tk.Label(
            url_row,
            text="🔗",
            bg=self.palette["card"],
            fg=self.palette["accent"],
            font=(self.font_family, 12, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.url_entry = ttk.Entry(
            url_row, textvariable=self.url_var, width=80, style="Normal.TEntry"
        )
        self.url_entry.configure(font=(self.font_family, 12))
        self.url_entry.grid(row=0, column=1, sticky="ew", ipady=8)

        url_actions = tk.Frame(url_card, bg=self.palette["card"])
        url_actions.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(10, 14))
        url_actions.grid_columnconfigure(2, weight=1)
        self._button(
            url_actions,
            text="Coller l'URL",
            command=self.paste_url,
            variant="tertiary",
        ).grid(row=0, column=0, sticky="w")
        self.preview_video_button = self._button(
            url_actions,
            text="Voir la vidéo",
            command=self.preview_video,
            variant="tertiary",
        )
        self.preview_video_button.grid(row=0, column=1, sticky="w", padx=(10, 0))

        quick_actions = tk.Frame(url_card, bg=self.palette["card"])
        quick_actions.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 14))
        quick_actions.grid_columnconfigure(0, weight=1)
        quick_actions.grid_columnconfigure(1, weight=1)
        quick_actions.grid_columnconfigure(2, weight=1)

        self.quick_transcribe_button = self._button(
            quick_actions,
            text="Transcription YouTube",
            command=self.generate,
            variant="primary",
        )
        self.quick_transcribe_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.quick_download_full_video_button = self._button(
            quick_actions,
            text="Télécharger vidéo",
            command=self.download_full_video,
            variant="secondary",
        )
        self.quick_download_full_video_button.grid(row=0, column=1, sticky="ew", padx=6)

        self.quick_download_audio_button = self._button(
            quick_actions,
            text="Télécharger audio",
            command=self.download_audio_only,
            variant="secondary",
        )
        self.quick_download_audio_button.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        self._apply_placeholder(self.url_entry, "https://www.youtube.com/watch?v=... ou lien social")

        self.config_summary_label = ttk.Label(
            url_card,
            textvariable=self.config_summary_var,
            style="CardMuted.TLabel",
        )
        self.config_summary_label.grid(
            row=4, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 4)
        )

        cookies_row = tk.Frame(url_card, bg=self.palette["card"])
        cookies_row.grid(row=5, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 10))
        ttk.Label(
            cookies_row,
            text="Cookies navigateur :",
            style="CardMuted.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self._cookies_browser_combo = ttk.Combobox(
            cookies_row,
            textvariable=self.ytdlp_cookies_browser_var,
            values=["Aucun", "Chrome", "Firefox", "Safari", "Edge", "Brave"],
            state="readonly",
            width=10,
        )
        self._cookies_browser_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(
            cookies_row,
            text="— si YouTube bloque le téléchargement",
            style="CardMuted.TLabel",
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))

        download_status_shadow = tk.Frame(container, bg=self.palette["shadow"])
        download_status_shadow.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        download_status_shadow.grid_columnconfigure(0, weight=1)
        download_status_shadow.grid_remove()  # caché par défaut, affiché au démarrage d'un téléchargement
        self._download_status_shadow = download_status_shadow
        download_status_card = tk.Frame(download_status_shadow, bg=self.palette["card"])
        download_status_card.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        download_status_card.grid_columnconfigure(0, weight=1)

        download_status_header = tk.Frame(download_status_card, bg=self.palette["card"])
        download_status_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        download_status_header.grid_columnconfigure(0, weight=1)

        ttk.Label(
            download_status_header,
            text="Suivi des téléchargements",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")

        download_status_right = tk.Frame(download_status_header, bg=self.palette["card"])
        download_status_right.grid(row=0, column=1, sticky="e")
        ttk.Label(
            download_status_right,
            textvariable=self.download_summary_var,
            style="CardMuted.TLabel",
        ).grid(row=0, column=0, sticky="e", padx=(0, 10))
        self.download_toggle_button = ttk.Button(
            download_status_right,
            text="Voir les détails techniques",
            command=self.toggle_download_logs,
            style="Link.TButton",
        )
        self.download_toggle_button.grid(row=0, column=1, sticky="e")

        self.download_overall_progress = _CanvasProgress(
            download_status_card,
            height=20,
            palette=self.palette,
            font_family=self.font_family,
            show_text=True,
            bg=self.palette["card"],
        )
        self.download_overall_progress.grid(
            row=1, column=0, sticky="ew", padx=16, pady=(4, 4)
        )

        self.download_current_progress = _CanvasProgress(
            download_status_card,
            height=14,
            palette=self.palette,
            font_family=self.font_family,
            show_text=True,
            bg=self.palette["card"],
        )
        self.download_current_progress.grid(
            row=2, column=0, sticky="ew", padx=16, pady=(0, 8)
        )

        ttk.Label(
            download_status_card,
            textvariable=self.download_detail_var,
            style="CardMuted.TLabel",
        ).grid(row=3, column=0, sticky="w", padx=16)
        ttk.Label(
            download_status_card,
            textvariable=self.download_phase_var,
            style="CardMuted.TLabel",
        ).grid(row=4, column=0, sticky="w", padx=16, pady=(4, 0))

        self.download_log = scrolledtext.ScrolledText(
            download_status_card,
            wrap=tk.WORD,
            height=4,
            font=(self.mono_family, 9),
        )
        self.download_log.grid(row=5, column=0, sticky="ew", padx=16, pady=(8, 16))
        self.download_log.configure(state="disabled")
        self._style_text_widget(self.download_log, background=self.palette["bg_alt"])
        self.download_log.grid_remove()

        options_shadow = tk.Frame(container, bg=self.palette["shadow"])
        options_shadow.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        options_shadow.grid_columnconfigure(0, weight=1)
        options_card = tk.Frame(options_shadow, bg=self.palette["card"])
        options_card.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        options_card.grid_columnconfigure(0, weight=1)

        options_header = tk.Frame(options_card, bg=self.palette["card"])
        options_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        options_header.grid_columnconfigure(0, weight=1)

        ttk.Label(options_header, text="Options avancées", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            options_header,
            text="(pour utilisateurs expérimentés)",
            style="CardMuted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.options_toggle_button = ttk.Button(
            options_header,
            text="Afficher ▾",
            command=self.toggle_options,
            style="Link.TButton",
        )
        self.options_toggle_button.grid(row=0, column=1, sticky="e")

        self.options_body = tk.Frame(options_card, bg=self.palette["card"])
        self.options_body.grid(row=1, column=0, sticky="ew", padx=0, pady=(0, 14))
        self.options_body.grid_columnconfigure(0, weight=1)

        self._options_notebook = ttk.Notebook(self.options_body, style="Options.TNotebook")
        self._options_notebook.grid(row=0, column=0, sticky="nsew", padx=16, pady=(4, 0))
        options_notebook = self._options_notebook

        _tabs: dict[str, tk.Frame] = {}
        for _key, _label in [
            ("trans", "Transcription"),
            ("video", "Vidéo"),
            ("logo",  "Logo"),
            ("subs",  "Sous-titres"),
        ]:
            # tk.Frame (non-ttk) pour éviter les conflits padding/grid_columnconfigure
            _f = tk.Frame(options_notebook, bg=self.palette["card"])
            _f.grid_columnconfigure(0, weight=1)
            options_notebook.add(_f, padding=(12, 10))
            options_notebook.tab(_f, text=_label)
            _tabs[_key] = _f

        # Redessine l'aperçu logo quand l'onglet Logo devient actif
        def _on_tab_changed(event: tk.Event) -> None:
            try:
                idx = options_notebook.index(options_notebook.select())
                if idx == 2:  # onglet Logo
                    self.master.after_idle(self._redraw_logo_preview)
            except tk.TclError:
                pass
        options_notebook.bind("<<NotebookTabChanged>>", _on_tab_changed)

        # ── TAB: Transcription ──────────────────────────────────────────
        _tr = _tabs["trans"]

        ttk.Label(_tr, text="Langues (séparées par des virgules)", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.languages_entry = ttk.Entry(_tr, textvariable=self.languages_var, style="Normal.TEntry")
        self.languages_entry.grid(row=1, column=0, sticky="ew", pady=(6, 10))
        self._apply_placeholder(self.languages_entry, "fr,en")

        ttk.Label(_tr, text="Format de sortie", style="Card.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        self.format_combo = ttk.Combobox(
            _tr,
            textvariable=self.output_format_var,
            values=list(self.output_format_lookup.values()),
            state="readonly",
        )
        self.format_combo.grid(row=3, column=0, sticky="w", pady=(6, 10))

        ttk.Checkbutton(
            _tr,
            text="Moments forts estimés",
            variable=self.most_viewed_var,
            style="Card.TCheckbutton",
        ).grid(row=4, column=0, sticky="w")
        count_row = tk.Frame(_tr, bg=self.palette["card"])
        count_row.grid(row=5, column=0, sticky="w", pady=(6, 0))
        ttk.Label(count_row, text="Nombre", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.most_viewed_spin = ttk.Spinbox(count_row, from_=1, to=20, width=5, textvariable=self.most_viewed_count_var)
        self.most_viewed_spin.grid(row=0, column=1, sticky="w", padx=(10, 0))

        duration_row = tk.Frame(_tr, bg=self.palette["card"])
        duration_row.grid(row=6, column=0, sticky="w", pady=(10, 0))
        ttk.Label(duration_row, text="Durée extrait (s)", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.clip_duration_spin = ttk.Spinbox(duration_row, from_=10, to=300, increment=10, width=5, textvariable=self.clip_duration_var)
        self.clip_duration_spin.grid(row=0, column=1, sticky="w", padx=(10, 0))

        # ── TAB: Vidéo ─────────────────────────────────────────────────
        _vi = _tabs["video"]
        _vi.grid_columnconfigure(0, weight=1)

        format_row = tk.Frame(_vi, bg=self.palette["card"])
        format_row.grid(row=0, column=0, sticky="w")
        ttk.Label(format_row, text="Format vidéo", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.video_format_combo = ttk.Combobox(format_row, textvariable=self.video_format_var, values=["mp4", "webm"], state="readonly", width=6)
        self.video_format_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))

        preset_row = tk.Frame(_vi, bg=self.palette["card"])
        preset_row.grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Label(preset_row, text="Preset créatif", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.download_preset_combo = ttk.Combobox(preset_row, textvariable=self.download_preset_var, values=list(self.download_preset_lookup.keys()), state="readonly", width=18)
        self.download_preset_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))

        aspect_row = tk.Frame(_vi, bg=self.palette["card"])
        aspect_row.grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Label(aspect_row, text="Format final", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.download_aspect_ratio_combo = ttk.Combobox(aspect_row, textvariable=self.download_aspect_ratio_var, values=list(self.download_aspect_ratio_lookup.keys()), state="readonly", width=14)
        self.download_aspect_ratio_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.download_shorts_blur_check = ttk.Checkbutton(
            _vi,
            text="Fond flouté (pillarbox Shorts)",
            variable=self.download_shorts_blur_var,
            style="Card.TCheckbutton",
        )
        self.download_shorts_blur_check.grid(row=3, column=0, sticky="w", pady=(6, 0))

        video_effect_row_vi = tk.Frame(_vi, bg=self.palette["card"])
        video_effect_row_vi.grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Label(video_effect_row_vi, text="Effet vidéo", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.download_video_effect_combo = ttk.Combobox(video_effect_row_vi, textvariable=self.download_video_effect_var, values=list(self.download_video_effect_lookup.keys()), state="readonly", width=16)
        self.download_video_effect_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))

        value_add_row = tk.Frame(_vi, bg=self.palette["card"])
        value_add_row.grid(row=5, column=0, sticky="w", pady=(14, 0))
        ttk.Label(value_add_row, text="Valeur ajoutée", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.download_intro_outro_check = ttk.Checkbutton(value_add_row, text="Intro / Outro", variable=self.download_intro_outro_enabled_var, style="Card.TCheckbutton",
            command=self._on_intro_outro_toggle)
        self.download_intro_outro_check.grid(row=1, column=0, sticky="w")

        self.download_intro_outro_options = tk.Frame(value_add_row, bg=self.palette["card"])
        self.download_intro_outro_options.grid(row=2, column=0, sticky="ew", padx=(16, 0), pady=(4, 0))
        self.download_intro_outro_options.grid_columnconfigure(1, weight=1)
        # Durée hold
        ttk.Label(self.download_intro_outro_options, text="Durée affichage (s)", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.download_intro_outro_hold_spin = ttk.Spinbox(
            self.download_intro_outro_options, from_=0.5, to=5.0, increment=0.5, width=5,
            textvariable=self.download_intro_outro_hold_var,
        )
        self.download_intro_outro_hold_spin.grid(row=0, column=1, sticky="w", padx=(10, 0))
        # Couleurs
        intro_color_row = tk.Frame(self.download_intro_outro_options, bg=self.palette["card"])
        intro_color_row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.download_intro_outro_bg_button = ttk.Button(
            intro_color_row, text="Fond", style="Subtle.TButton",
            command=lambda: self._pick_intro_outro_color(self.download_intro_outro_bg_color_var, self.download_intro_outro_bg_swatch),
        )
        self.download_intro_outro_bg_button.grid(row=0, column=0, sticky="w")
        self.download_intro_outro_bg_swatch = tk.Label(
            intro_color_row, width=3,
            bg=self.download_intro_outro_bg_color_var.get(), relief="solid", borderwidth=1,
        )
        self.download_intro_outro_bg_swatch.grid(row=0, column=1, padx=(6, 12))
        self.download_intro_outro_text_button = ttk.Button(
            intro_color_row, text="Texte", style="Subtle.TButton",
            command=lambda: self._pick_intro_outro_color(self.download_intro_outro_text_color_var, self.download_intro_outro_text_swatch),
        )
        self.download_intro_outro_text_button.grid(row=0, column=2, sticky="w")
        self.download_intro_outro_text_swatch = tk.Label(
            intro_color_row, width=3,
            bg=self.download_intro_outro_text_color_var.get(), relief="solid", borderwidth=1,
        )
        self.download_intro_outro_text_swatch.grid(row=0, column=3, padx=(6, 0))
        self.download_intro_outro_options.grid_remove()  # masqué par défaut

        self.download_progress_bar_check = ttk.Checkbutton(value_add_row, text="Barre de progression", variable=self.download_progress_bar_enabled_var, style="Card.TCheckbutton")
        self.download_progress_bar_check.grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.download_animated_watermark_check = ttk.Checkbutton(value_add_row, text="Filigrane animé", variable=self.download_animated_watermark_enabled_var, style="Card.TCheckbutton")
        self.download_animated_watermark_check.grid(row=4, column=0, sticky="w", pady=(4, 0))

        # ── TAB: Logo ──────────────────────────────────────────────────
        _lo = _tabs["logo"]
        _lo.grid_columnconfigure(0, weight=1)

        self.download_logo_check = ttk.Checkbutton(
            _lo, text="Intégrer le logo",
            variable=self.download_logo_enabled_var,
            command=self._on_download_logo_toggle, style="Card.TCheckbutton",
        )
        self.download_logo_check.grid(row=0, column=0, sticky="w")

        logo_row = tk.Frame(_lo, bg=self.palette["card"])
        logo_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        logo_row.grid_columnconfigure(0, weight=1)
        ttk.Label(logo_row, text="Logo à intégrer (facultatif)", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        logo_input = tk.Frame(logo_row, bg=self.palette["card"])
        logo_input.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        logo_input.grid_columnconfigure(0, weight=1)
        self.download_logo_entry = ttk.Entry(logo_input, textvariable=self.download_logo_var, style="Normal.TEntry")
        self.download_logo_entry.grid(row=0, column=0, sticky="ew")
        self.download_logo_button = ttk.Button(logo_input, text="Choisir…", command=self.select_download_logo, style="Secondary.TButton")
        self.download_logo_button.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self._apply_placeholder(self.download_logo_entry, DOWNLOAD_LOGO_PLACEHOLDER)

        logo_position_row = tk.Frame(_lo, bg=self.palette["card"])
        logo_position_row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        logo_position_row.grid_columnconfigure(0, weight=1)
        ttk.Label(logo_position_row, text="Position du logo", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.download_logo_position_combo = ttk.Combobox(
            logo_position_row, textvariable=self.download_logo_position_var,
            values=list(self.download_logo_position_lookup.keys()), state="readonly", width=16,
        )
        self.download_logo_position_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))

        logo_preview_row = tk.Frame(_lo, bg=self.palette["card"])
        logo_preview_row.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        logo_preview_row.grid_columnconfigure(0, weight=1)
        ttk.Label(logo_preview_row, text="Aperçu logo", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.download_logo_preview_canvas = tk.Canvas(
            logo_preview_row, width=280, height=158,
            bg=self.palette["bg_alt"], highlightthickness=1,
            highlightbackground=self.palette["shadow"], cursor="hand2",
        )
        self.download_logo_preview_canvas.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.download_logo_preview_canvas.bind("<Configure>", lambda _event: self._redraw_logo_preview())
        self.download_logo_preview_canvas.bind("<ButtonPress-1>", self._on_logo_preview_press)
        self.download_logo_preview_canvas.bind("<B1-Motion>", self._on_logo_preview_drag)

        logo_size_row = tk.Frame(_lo, bg=self.palette["card"])
        logo_size_row.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        logo_size_row.grid_columnconfigure(0, weight=1)
        ttk.Label(logo_size_row, text="Taille logo", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(logo_size_row, textvariable=self.download_logo_size_label_var, style="CardMuted.TLabel").grid(row=0, column=1, sticky="e")
        logo_size_mode_row = tk.Frame(logo_size_row, bg=self.palette["card"])
        logo_size_mode_row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(logo_size_mode_row, text="Mode", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.download_logo_size_mode_combo = ttk.Combobox(
            logo_size_mode_row, textvariable=self.download_logo_size_mode_var,
            values=list(self.download_logo_size_mode_lookup.keys()), state="readonly", width=26,
        )
        self.download_logo_size_mode_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.download_logo_size_scale = ttk.Scale(
            logo_size_row, from_=20, to=80, variable=self.download_logo_size_var,
            orient="horizontal", command=self._on_logo_size_change,
        )
        self.download_logo_size_scale.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        logo_opacity_row = tk.Frame(_lo, bg=self.palette["card"])
        logo_opacity_row.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        logo_opacity_row.grid_columnconfigure(0, weight=1)
        ttk.Label(logo_opacity_row, text="Opacité logo", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(logo_opacity_row, textvariable=self.download_logo_opacity_label_var, style="CardMuted.TLabel").grid(row=0, column=1, sticky="e")
        self.download_logo_opacity_scale = ttk.Scale(
            logo_opacity_row, from_=10, to=100, variable=self.download_logo_opacity_var,
            orient="horizontal", command=self._on_logo_opacity_change,
        )
        self.download_logo_opacity_scale.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        logo_duration_row = tk.Frame(_lo, bg=self.palette["card"])
        logo_duration_row.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        logo_duration_row.grid_columnconfigure(0, weight=1)
        ttk.Label(logo_duration_row, text="Durée logo (s, 0 = toujours)", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.download_logo_duration_spin = ttk.Spinbox(
            logo_duration_row, from_=0, to=120, increment=5, width=5,
            textvariable=self.download_logo_duration_var,
        )
        self.download_logo_duration_spin.grid(row=0, column=1, sticky="e")

        # ── TAB: Sous-titres ───────────────────────────────────────────
        _su = _tabs["subs"]
        _su.grid_columnconfigure(0, weight=1)

        self.download_subtitles_check = ttk.Checkbutton(
            _su, text="Ajouter sous-titres",
            variable=self.download_subtitles_enabled_var, style="Card.TCheckbutton",
        )
        self.download_subtitles_check.grid(row=0, column=0, sticky="w")

        subtitle_style_row = tk.Frame(_su, bg=self.palette["card"])
        subtitle_style_row.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(subtitle_style_row, text="Design sous-titres", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.download_subtitle_style_combo = ttk.Combobox(
            subtitle_style_row, textvariable=self.download_subtitle_style_var,
            values=list(self.download_subtitle_style_lookup.keys()), state="readonly", width=18,
        )
        self.download_subtitle_style_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))

        subtitle_offset_row = tk.Frame(_su, bg=self.palette["card"])
        subtitle_offset_row.grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(subtitle_offset_row, text="Décalage audio (ms)", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.download_subtitle_offset_spin = ttk.Spinbox(
            subtitle_offset_row, from_=-800, to=800, increment=50, width=6,
            textvariable=self.download_subtitle_offset_var,
        )
        self.download_subtitle_offset_spin.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(
            subtitle_offset_row, text="(négatif = avancer, 0 = désactivé)",
            style="CardMuted.TLabel",
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))

        ttk.Separator(_su, orient="horizontal").grid(row=3, column=0, sticky="ew", pady=(14, 0))

        self.download_lower_third_check = ttk.Checkbutton(
            _su, text="Ajouter lower third",
            variable=self.download_lower_third_enabled_var, style="Card.TCheckbutton",
        )
        self.download_lower_third_check.grid(row=4, column=0, sticky="w", pady=(10, 0))

        self.download_lower_third_frame = tk.Frame(_su, bg=self.palette["card"])
        self.download_lower_third_frame.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.download_lower_third_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(
            self.download_lower_third_frame,
            text="Nom chaîne",
            style="Card.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.download_lower_third_name_entry = ttk.Entry(
            self.download_lower_third_frame,
            textvariable=self.download_lower_third_name_var,
            width=22,
        )
        self.download_lower_third_name_entry.grid(
            row=0, column=1, sticky="ew", padx=(10, 0)
        )
        self.download_lower_third_fetch_button = ttk.Button(
            self.download_lower_third_frame,
            text="Récupérer ↓",
            style="Subtle.TButton",
            command=self._fetch_lower_third_from_url,
        )
        self.download_lower_third_fetch_button.grid(row=0, column=2, sticky="w", padx=(6, 0))
        ttk.Label(
            self.download_lower_third_frame,
            text="Tagline",
            style="Card.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.download_lower_third_tagline_entry = ttk.Entry(
            self.download_lower_third_frame,
            textvariable=self.download_lower_third_tagline_var,
            width=22,
        )
        self.download_lower_third_tagline_entry.grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=(6, 0)
        )
        self.download_lower_third_subscribe_check = ttk.Checkbutton(
            self.download_lower_third_frame,
            text='Afficher "Abonnez-vous"',
            variable=self.download_lower_third_subscribe_var,
            style="Card.TCheckbutton",
        )
        self.download_lower_third_subscribe_check.grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        lower_position_row = tk.Frame(self.download_lower_third_frame, bg=self.palette["card"])
        lower_position_row.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(
            lower_position_row, text="Position", style="Card.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.download_lower_third_position_combo = ttk.Combobox(
            lower_position_row,
            textvariable=self.download_lower_third_position_var,
            values=["Bas", "Haut", "Centré haut"],
            state="readonly",
            width=8,
        )
        self.download_lower_third_position_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))
        lower_color_row = tk.Frame(self.download_lower_third_frame, bg=self.palette["card"])
        lower_color_row.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.download_lower_third_bg_button = ttk.Button(
            lower_color_row,
            text="Couleur fond",
            style="Subtle.TButton",
            command=lambda: self._pick_lower_third_color(
                self.download_lower_third_bg_color_var
            ),
        )
        self.download_lower_third_bg_button.grid(row=0, column=0, sticky="w")
        self.download_lower_third_bg_swatch = tk.Label(
            lower_color_row,
            width=3,
            bg=self.download_lower_third_bg_color_var.get(),
            relief="solid",
            borderwidth=1,
        )
        self.download_lower_third_bg_swatch.grid(row=0, column=1, padx=(6, 12))
        self.download_lower_third_accent_button = ttk.Button(
            lower_color_row,
            text="Couleur accent",
            style="Subtle.TButton",
            command=lambda: self._pick_lower_third_color(
                self.download_lower_third_accent_color_var
            ),
        )
        self.download_lower_third_accent_button.grid(row=0, column=2, sticky="w")
        self.download_lower_third_accent_swatch = tk.Label(
            lower_color_row,
            width=3,
            bg=self.download_lower_third_accent_color_var.get(),
            relief="solid",
            borderwidth=1,
        )
        self.download_lower_third_accent_swatch.grid(row=0, column=3, padx=(6, 0))

        lower_timing_row = tk.Frame(
            self.download_lower_third_frame,
            bg=self.palette["card"],
        )
        lower_timing_row.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        lower_timing_row.grid_columnconfigure(0, weight=1)
        ttk.Label(
            lower_timing_row,
            text="Intervalle",
            style="Card.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            lower_timing_row,
            textvariable=self.download_lower_third_interval_label_var,
            style="CardMuted.TLabel",
        ).grid(row=0, column=1, sticky="e")
        self.download_lower_third_interval_scale = tk.Scale(
            lower_timing_row,
            from_=lower_third.MIN_DISPLAY_INTERVAL_SECONDS,
            to=lower_third.MAX_DISPLAY_INTERVAL_SECONDS,
            resolution=1,
            orient="horizontal",
            variable=self.download_lower_third_interval_var,
            command=lambda _value: self._sync_lower_third_timing_labels(),
            bg=self.palette["card"],
            troughcolor=self.palette["bg_alt"],
            activebackground=self.palette["accent"],
            highlightthickness=0,
        )
        self.download_lower_third_interval_scale.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
        )
        ttk.Label(
            lower_timing_row,
            text="Durée affichage",
            style="Card.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(
            lower_timing_row,
            textvariable=self.download_lower_third_display_duration_label_var,
            style="CardMuted.TLabel",
        ).grid(row=2, column=1, sticky="e", pady=(6, 0))
        self.download_lower_third_display_duration_scale = tk.Scale(
            lower_timing_row,
            from_=lower_third.MIN_DISPLAY_DURATION_SECONDS,
            to=lower_third.MAX_DISPLAY_DURATION_SECONDS,
            resolution=1,
            orient="horizontal",
            variable=self.download_lower_third_display_duration_var,
            command=lambda _value: self._sync_lower_third_timing_labels(),
            bg=self.palette["card"],
            troughcolor=self.palette["bg_alt"],
            activebackground=self.palette["accent"],
            highlightthickness=0,
        )
        self.download_lower_third_display_duration_scale.grid(
            row=3,
            column=0,
            columnspan=2,
            sticky="ew",
        )

        # ── Aperçu lower third ──────────────────────────────────────────
        lt_preview_outer = tk.Frame(self.download_lower_third_frame, bg=self.palette["card"])
        lt_preview_outer.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        lt_preview_outer.grid_columnconfigure(0, weight=1)
        ttk.Label(lt_preview_outer, text="Aperçu lower third", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.download_lower_third_preview_canvas = tk.Canvas(
            lt_preview_outer, width=140, height=248,
            bg=self.palette["bg_alt"], highlightthickness=1,
            highlightbackground=self.palette["shadow"],
        )
        self.download_lower_third_preview_canvas.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.download_lower_third_preview_canvas.bind(
            "<Configure>", lambda _e: self._redraw_lower_third_preview()
        )

        # ── Taille titre ────────────────────────────────────────────────
        lt_title_scale_row = tk.Frame(self.download_lower_third_frame, bg=self.palette["card"])
        lt_title_scale_row.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        lt_title_scale_row.grid_columnconfigure(0, weight=1)
        ttk.Label(lt_title_scale_row, text="Taille titre", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            lt_title_scale_row, textvariable=self.download_lower_third_title_scale_label_var,
            style="CardMuted.TLabel",
        ).grid(row=0, column=1, sticky="e")
        self.download_lower_third_title_scale_slider = tk.Scale(
            lt_title_scale_row, from_=50, to=150, resolution=5, orient="horizontal",
            variable=self.download_lower_third_title_scale_var,
            command=lambda _v: self._on_lower_third_preview_change(),
            bg=self.palette["card"], troughcolor=self.palette["bg_alt"],
            activebackground=self.palette["accent"], highlightthickness=0,
        )
        self.download_lower_third_title_scale_slider.grid(
            row=1, column=0, columnspan=2, sticky="ew"
        )

        # ── Taille tagline ──────────────────────────────────────────────
        lt_tagline_scale_row = tk.Frame(self.download_lower_third_frame, bg=self.palette["card"])
        lt_tagline_scale_row.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        lt_tagline_scale_row.grid_columnconfigure(0, weight=1)
        ttk.Label(lt_tagline_scale_row, text="Taille tagline", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            lt_tagline_scale_row, textvariable=self.download_lower_third_tagline_scale_label_var,
            style="CardMuted.TLabel",
        ).grid(row=0, column=1, sticky="e")
        self.download_lower_third_tagline_scale_slider = tk.Scale(
            lt_tagline_scale_row, from_=50, to=150, resolution=5, orient="horizontal",
            variable=self.download_lower_third_tagline_scale_var,
            command=lambda _v: self._on_lower_third_preview_change(),
            bg=self.palette["card"], troughcolor=self.palette["bg_alt"],
            activebackground=self.palette["accent"], highlightthickness=0,
        )
        self.download_lower_third_tagline_scale_slider.grid(
            row=1, column=0, columnspan=2, sticky="ew"
        )

        # ── Texte bouton ────────────────────────────────────────────────
        lt_sub_text_row = tk.Frame(self.download_lower_third_frame, bg=self.palette["card"])
        lt_sub_text_row.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        lt_sub_text_row.grid_columnconfigure(1, weight=1)
        ttk.Label(lt_sub_text_row, text="Texte bouton", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.download_lower_third_subscribe_text_entry = ttk.Entry(
            lt_sub_text_row, textvariable=self.download_lower_third_subscribe_text_var, width=18,
        )
        self.download_lower_third_subscribe_text_entry.grid(
            row=0, column=1, sticky="ew", padx=(10, 0)
        )

        # ── Opacité fond ────────────────────────────────────────────────
        lt_opacity_row = tk.Frame(self.download_lower_third_frame, bg=self.palette["card"])
        lt_opacity_row.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        lt_opacity_row.grid_columnconfigure(0, weight=1)
        ttk.Label(lt_opacity_row, text="Opacité fond", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            lt_opacity_row, textvariable=self.download_lower_third_bg_opacity_label_var,
            style="CardMuted.TLabel",
        ).grid(row=0, column=1, sticky="e")
        self.download_lower_third_bg_opacity_slider = tk.Scale(
            lt_opacity_row, from_=20, to=100, resolution=5, orient="horizontal",
            variable=self.download_lower_third_bg_opacity_var,
            command=lambda _v: self._on_lower_third_preview_change(),
            bg=self.palette["card"], troughcolor=self.palette["bg_alt"],
            activebackground=self.palette["accent"], highlightthickness=0,
        )
        self.download_lower_third_bg_opacity_slider.grid(
            row=1, column=0, columnspan=2, sticky="ew"
        )

        # ── Position verticale (Centré haut only) ───────────────────────
        lt_valign_row = tk.Frame(self.download_lower_third_frame, bg=self.palette["card"])
        lt_valign_row.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        lt_valign_row.grid_columnconfigure(0, weight=1)
        ttk.Label(lt_valign_row, text="Position dans la zone", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.download_lower_third_valign_combo = ttk.Combobox(
            lt_valign_row, textvariable=self.download_lower_third_valign_var,
            values=["Haut", "Centre", "Bas"], state="readonly", width=8,
        )
        self.download_lower_third_valign_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self._lt_valign_row = lt_valign_row  # keep ref for show/hide

        self._update_download_logo_controls_state()
        self._update_lower_third_controls_state()
        self._redraw_logo_preview()
        self.master.after_idle(self._redraw_lower_third_preview)

        self.options_body.grid_remove()

        cta_shadow = tk.Frame(container, bg=self.palette["shadow"])
        cta_shadow.grid(row=4, column=0, sticky="ew", pady=(4, 12))
        cta_shadow.grid_columnconfigure(0, weight=1)
        cta_card = tk.Frame(cta_shadow, bg=self.palette["card"])
        cta_card.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        cta_card.grid_columnconfigure(0, weight=1)

        ttk.Label(
            cta_card,
            text="Transcription YouTube",
            style="CardMuted.TLabel",
        ).grid(row=0, column=0, sticky="n", pady=(14, 4))
        self.generate_button = self._button(
            cta_card,
            text="Transcrire la vidéo YouTube",
            command=self.generate,
            variant="primary",
        )
        self.generate_button.grid(
            row=1, column=0, sticky="ew", padx=160, pady=(0, 16), ipadx=30
        )

        actions = tk.Frame(container, bg=self.palette["bg"])
        actions.grid(row=5, column=0, sticky="ew", pady=(0, 16))
        actions.grid_columnconfigure(0, weight=1)

        actions_right = tk.Frame(actions, bg=self.palette["bg"])
        actions_right.grid(row=0, column=1, sticky="e")

        self.save_button = self._button(
            actions_right,
            text="Enregistrer",
            command=self.save_transcript,
            variant="tertiary",
        )
        self.save_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.download_moments_button = self._button(
            actions_right,
            text="Exporter liste",
            command=self.export_moments,
            variant="tertiary",
        )
        self.download_moments_button.grid(row=0, column=1, sticky="ew", padx=6)

        self.clear_button = self._button(
            actions_right,
            text="Réinitialiser",
            command=self.clear_form,
            variant="tertiary",
        )
        self.clear_button.grid(row=0, column=2, sticky="ew", padx=6)

        self.cancel_button = self._button(
            actions_right,
            text="Annuler",
            command=self.cancel,
            state="disabled",
            variant="tertiary",
        )
        self.cancel_button.grid(row=0, column=3, sticky="ew", padx=(6, 0))

        transcript_shadow = tk.Frame(container, bg=self.palette["shadow"])
        transcript_shadow.grid(row=6, column=0, sticky="nsew", pady=(0, 16))
        transcript_shadow.grid_rowconfigure(0, weight=1)
        transcript_shadow.grid_columnconfigure(0, weight=1)
        transcript_card = tk.Frame(transcript_shadow, bg=self.palette["card"])
        transcript_card.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        transcript_card.grid_rowconfigure(1, weight=1)
        transcript_card.grid_columnconfigure(0, weight=1)

        transcript_header = tk.Frame(transcript_card, bg=self.palette["card"])
        transcript_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        transcript_header.grid_columnconfigure(0, weight=1)

        ttk.Label(transcript_header, text="Transcription", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.copy_button = self._button(
            transcript_header,
            text="Copier",
            command=self.copy_to_clipboard,
            variant="tertiary",
        )
        self.copy_button.grid(row=0, column=1, sticky="e")

        self.output_text = scrolledtext.ScrolledText(
            transcript_card, wrap=tk.WORD, height=18, font=(self.mono_family, 11)
        )
        self.output_text.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self._style_text_widget(self.output_text, background=self.palette["bg_alt"])
        self._configure_transcript_tags()

        moments_shadow = tk.Frame(container, bg=self.palette["shadow"])
        moments_shadow.grid(row=7, column=0, sticky="ew", pady=(0, 16))
        moments_shadow.grid_columnconfigure(0, weight=1)
        moments_card = tk.Frame(moments_shadow, bg=self.palette["card"])
        moments_card.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        moments_card.grid_columnconfigure(0, weight=1)

        moments_header = tk.Frame(moments_card, bg=self.palette["card"])
        moments_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        moments_header.grid_columnconfigure(0, weight=1)

        ttk.Label(
            moments_header,
            text="Moments forts estimés",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            moments_header,
            text="Extraits les plus engageants selon l'analyse",
            style="CardMuted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.moments_count_label = ttk.Label(
            moments_header, text="", style="CardMuted.TLabel"
        )
        self.moments_count_label.grid(row=0, column=1, sticky="e", padx=(0, 10))
        self.copy_chapters_button = self._button(
            moments_header,
            text="Copier chapitres",
            command=self._copy_youtube_chapters,
            variant="tertiary",
        )
        self.copy_chapters_button.grid(row=0, column=2, sticky="e", padx=(0, 8))
        self.download_clips_button = self._button(
            moments_header,
            text="Télécharger extraits",
            command=self.download_clips,
            variant="secondary",
        )
        self.download_clips_button.grid(row=0, column=3, sticky="e")

        self.moments_canvas = tk.Canvas(
            moments_card,
            background=self.palette["card"],
            highlightthickness=0,
            height=210,
        )
        self.moments_canvas.grid(row=1, column=0, sticky="ew", padx=16, pady=(6, 16))
        self.moments_scroll = ttk.Scrollbar(
            moments_card, orient="vertical", command=self.moments_canvas.yview
        )
        self.moments_scroll.grid(row=1, column=1, sticky="ns", pady=(6, 16))
        self.moments_canvas.configure(yscrollcommand=self.moments_scroll.set)

        self.moments_list = ttk.Frame(self.moments_canvas, style="Card.TFrame")
        self.moments_window = self.moments_canvas.create_window(
            (0, 0), window=self.moments_list, anchor="nw"
        )
        self.moments_list.bind("<Configure>", self._on_moments_configure)
        self.moments_canvas.bind("<Configure>", self._on_moments_canvas_configure)
        self._render_most_viewed_cards([])

        download_shadow = tk.Frame(container, bg=self.palette["shadow"])
        download_shadow.grid(row=8, column=0, sticky="ew", pady=(0, 14))
        download_shadow.grid_columnconfigure(0, weight=1)
        download_card = tk.Frame(download_shadow, bg=self.palette["card"])
        download_card.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        download_card.grid_columnconfigure(0, weight=1)
        download_header = tk.Frame(download_card, bg=self.palette["card"])
        download_header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 6))
        download_header.grid_columnconfigure(0, weight=1)

        ttk.Label(
            download_header,
            text="Téléchargements multi-réseaux",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            download_header,
            text="Vidéo entière, audio MP3 et historique des exports.",
            style="CardMuted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        download_actions = tk.Frame(download_card, bg=self.palette["card"])
        download_actions.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(2, 8))
        download_actions.grid_columnconfigure(0, weight=1)
        download_actions.grid_columnconfigure(1, weight=1)

        self.download_full_video_button = self._button(
            download_actions,
            text="Télécharger la vidéo entière",
            command=self.download_full_video,
            variant="secondary",
        )
        self.download_full_video_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.download_audio_button = self._button(
            download_actions,
            text="Télécharger l'audio (MP3)",
            command=self.download_audio_only,
            variant="secondary",
        )
        self.download_audio_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.download_video_logo_check = ttk.Checkbutton(
            download_actions,
            text="Ajouter le logo à la vidéo",
            variable=self.download_logo_enabled_var,
            command=self._on_download_logo_toggle,
            style="Card.TCheckbutton",
        )
        self.download_video_logo_check.grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        history_header = tk.Frame(download_card, bg=self.palette["card"])
        history_header.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(6, 6))
        history_header.grid_columnconfigure(0, weight=1)
        ttk.Label(
            history_header,
            text="Historique des liens téléchargés",
            style="Card.TLabel",
        ).grid(row=0, column=0, sticky="w")
        history_actions = tk.Frame(history_header, bg=self.palette["card"])
        history_actions.grid(row=0, column=1, sticky="e")
        self.download_history_refresh_button = ttk.Button(
            history_actions,
            text="Actualiser",
            command=self._refresh_download_history_view,
            style="Link.TButton",
        )
        self.download_history_refresh_button.grid(row=0, column=0, sticky="e")
        self.download_history_clear_button = ttk.Button(
            history_actions,
            text="Effacer",
            command=self.clear_download_history,
            style="Link.TButton",
        )
        self.download_history_clear_button.grid(row=0, column=1, sticky="e", padx=(10, 0))

        self.download_history_text = scrolledtext.ScrolledText(
            download_card, wrap=tk.WORD, height=8, font=(self.mono_family, 9)
        )
        self.download_history_text.grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16)
        )
        self.download_history_text.configure(state="disabled")
        self._style_text_widget(self.download_history_text, background=self.palette["bg_alt"])

        feedback_frame = ttk.Frame(container)
        feedback_frame.grid(row=9, column=0, sticky="ew", pady=(6, 0))
        feedback_frame.grid_columnconfigure(0, weight=1)
        feedback_frame.grid_columnconfigure(1, weight=1)

        self.progress = ttk.Progressbar(
            feedback_frame,
            mode="indeterminate",
            maximum=50,
            length=200,
            style="Blue.Horizontal.TProgressbar",
        )
        self.progress.grid(row=0, column=0, sticky="w")

        ttk.Label(
            feedback_frame, textvariable=self.status_var, style="Status.TLabel"
        ).grid(row=0, column=1, sticky="e")

        ttk.Label(feedback_frame, textvariable=self.meta_var).grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Label(feedback_frame, textvariable=self.stats_var).grid(
            row=1, column=1, sticky="e", pady=(6, 0)
        )

    def toggle_options(self) -> None:
        if self.options_visible:
            self.options_body.grid_remove()
            self.options_toggle_button.configure(text="Afficher ▾")
            self.options_visible = False
        else:
            self.options_body.grid()
            self.options_toggle_button.configure(text="Masquer ▴")
            self.options_visible = True
        self._refresh_options_badge()

    def _count_active_options(self) -> int:
        count = 0
        if self.download_logo_enabled_var.get() and self._current_download_logo_path():
            count += 1
        if self.download_lower_third_enabled_var.get():
            count += 1
        if self.download_subtitles_enabled_var.get():
            count += 1
        if self.download_intro_outro_enabled_var.get():
            count += 1
        if self.download_progress_bar_enabled_var.get():
            count += 1
        if self.download_animated_watermark_enabled_var.get():
            count += 1
        if self.download_video_effect_var.get() not in ("Aucun", "none", ""):
            count += 1
        if self.download_aspect_ratio_var.get() != "Normal 16:9":
            count += 1
        return count

    def _refresh_options_badge(self) -> None:
        n = self._count_active_options()
        badge = f" ({n} active{'s' if n > 1 else ''})" if n > 0 else ""
        label = "Masquer ▴" if self.options_visible else "Afficher ▾"
        self.options_toggle_button.configure(text=f"{label}{badge}")

    def _update_config_summary(self) -> None:
        parts: list[str] = []
        aspect = self.download_aspect_ratio_var.get()
        parts.append(aspect)
        if self.download_logo_enabled_var.get() and self._current_download_logo_path():
            try:
                dur = int(self.download_logo_duration_var.get())
            except (TypeError, ValueError):
                dur = 0
            parts.append(f"Logo{f' {dur}s' if dur > 0 else ''}")
        if self.download_lower_third_enabled_var.get():
            name = self.download_lower_third_name_var.get().strip()
            parts.append(f"Lower third{f': {name}' if name else ''}")
        if self.download_subtitles_enabled_var.get():
            style = self.download_subtitle_style_var.get()
            parts.append(f"Sous-titres: {style}")
        effect = self.download_video_effect_var.get()
        if effect and effect not in ("Aucun", "none"):
            parts.append(effect)
        if self.download_intro_outro_enabled_var.get():
            parts.append("Intro/Outro")
        if self.download_progress_bar_enabled_var.get():
            parts.append("Progression")
        summary = " · ".join(parts)
        self.config_summary_var.set(summary)
        self._refresh_options_badge()

    def _on_moments_configure(self, event: tk.Event) -> None:
        self.moments_canvas.configure(scrollregion=self.moments_canvas.bbox("all"))

    def _on_moments_canvas_configure(self, event: tk.Event) -> None:
        self.moments_canvas.itemconfigure(self.moments_window, width=event.width)
        wrap = max(event.width - 220, 220)
        for label in self._moment_excerpt_labels:
            label.configure(wraplength=wrap)

    def _score_color(self, ratio: float) -> str:
        """Return a color from indigo (low) → violet (mid) → emerald (high)."""
        ratio = max(0.0, min(1.0, ratio))
        if ratio < 0.5:
            # indigo → violet
            t = ratio * 2
            start = (91, 91, 214)   # #5b5bd6 accent
            end = (124, 58, 237)    # #7c3aed secondary
        else:
            # violet → emerald
            t = (ratio - 0.5) * 2
            start = (124, 58, 237)  # #7c3aed secondary
            end = (5, 150, 105)     # #059669 success
        r = int(start[0] + (end[0] - start[0]) * t)
        g = int(start[1] + (end[1] - start[1]) * t)
        b = int(start[2] + (end[2] - start[2]) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _render_most_viewed_cards(self, moments: List) -> None:
        for child in self.moments_list.winfo_children():
            child.destroy()
        self._moment_excerpt_labels = []
        self._moment_action_buttons = []
        self._moment_mini_bars = {}

        if not moments:
            self.moments_count_label.configure(text="0 moment")
            empty = ttk.Label(
                self.moments_list,
                text="Aucun moment détecté pour le moment.",
                style="CardMuted.TLabel",
            )
            empty.grid(row=0, column=0, sticky="w", padx=4, pady=6)
            return

        self.moments_count_label.configure(text=f"{len(moments)} moments")
        max_score = max((moment.score for moment in moments), default=1) or 1
        for index, moment in enumerate(moments):
            is_top = index == 0
            card_border = self.palette["hero_stripe"] if is_top else self.palette["border"]
            card = tk.Frame(
                self.moments_list,
                bg=self.palette["card"],
                highlightthickness=2 if is_top else 1,
                highlightbackground=card_border,
            )
            card.grid(row=index, column=0, sticky="ew", padx=4, pady=(10 if is_top else 5, 5))
            card.grid_columnconfigure(1, weight=1)

            # Left accent bar (vertical stripe)
            accent_bar = tk.Frame(
                card,
                bg=self._score_color(moment.score / max_score),
                width=4,
            )
            accent_bar.grid(row=0, column=0, rowspan=3, sticky="ns")

            timestamp = seconds_to_timestamp(moment.minute_index * 60)
            top_row = tk.Frame(card, bg=self.palette["card"])
            top_row.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(12, 12), pady=(12, 4))
            top_row.grid_columnconfigure(0, weight=1)

            badge_row = tk.Frame(top_row, bg=self.palette["card"])
            badge_row.grid(row=0, column=0, sticky="w")

            badge = tk.Label(
                badge_row,
                text=f"  {timestamp}  ",
                bg=self.palette["accent"],
                fg=self.palette["white"],
                font=(self.font_family, 10, "bold"),
                pady=3,
            )
            badge.grid(row=0, column=0, sticky="w")

            if is_top:
                tk.Label(
                    badge_row,
                    text="  ★ Recommandé  ",
                    bg=self.palette["success"],
                    fg=self.palette["white"],
                    font=(self.font_family, 9, "bold"),
                    pady=3,
                ).grid(row=0, column=1, sticky="w", padx=(8, 0))

            # Score bar + label (top-right)
            score_frame = tk.Frame(top_row, bg=self.palette["card"])
            score_frame.grid(row=0, column=1, sticky="e")
            score_label = tk.Label(
                score_frame,
                text=f"Score {moment.score}",
                bg=self.palette["card"],
                fg=self.palette["accent"],
                font=(self.font_family, 9, "bold"),
            )
            score_label.grid(row=0, column=0, sticky="e")

            bar_width = 100
            bar = tk.Canvas(
                score_frame,
                width=bar_width,
                height=8,
                background=self.palette["bg_alt"],
                highlightthickness=0,
            )
            fill_width = max(4, int(bar_width * moment.score / max_score))
            bar_color = self._score_color(moment.score / max_score)
            bar.create_rectangle(0, 0, bar_width, 8, fill=self.palette["bg_alt"], outline="")
            bar.create_rectangle(0, 0, fill_width, 8, fill=bar_color, outline="")
            bar.grid(row=1, column=0, sticky="e", pady=(4, 0))

            excerpt_label = tk.Label(
                card,
                text=moment.excerpt,
                bg=self.palette["card"],
                fg=self.palette["text"],
                justify="left",
                anchor="w",
                font=(self.font_family, 10),
                wraplength=520,
            )
            excerpt_label.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(12, 12))
            self._moment_excerpt_labels.append(excerpt_label)

            button_stack = tk.Frame(card, bg=self.palette["card"])
            button_stack.grid(row=2, column=1, columnspan=2, sticky="w", padx=12, pady=(10, 12))

            play_button = ttk.Button(
                button_stack,
                text="▶ Lire",
                command=lambda m=moment: self._open_at_minute(m.minute_index),
                style="SoftPrimary.TButton",
            )
            play_button.grid(row=0, column=0, sticky="ew")
            self._moment_action_buttons.append(play_button)

            download_button = ttk.Button(
                button_stack,
                text="⬇ Extraire",
                command=lambda m=moment: self.download_single_clip(m),
                style="Secondary.TButton",
            )
            download_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
            self._moment_action_buttons.append(download_button)

            preview_button = ttk.Button(
                button_stack,
                text="👁 Aperçu",
                command=lambda m=moment: self.preview_single_clip(m),
                style="Secondary.TButton",
            )
            preview_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))
            self._moment_action_buttons.append(preview_button)

            copy_button = ttk.Button(
                button_stack,
                text="📋 Copier",
                command=lambda m=moment: self.copy_moment_text(m),
                style="Secondary.TButton",
            )
            copy_button.grid(row=0, column=3, sticky="ew", padx=(8, 0))
            self._moment_action_buttons.append(copy_button)

            mini_bar = _CanvasProgress(
                card,
                height=4,
                palette=self.palette,
                font_family=self.font_family,
                show_text=False,
                bg=self.palette["card"],
            )
            mini_bar.grid(row=3, column=0, columnspan=3, sticky="ew")
            self._moment_mini_bars[index] = mini_bar

    def _open_at_minute(self, minute_index: int) -> None:
        url = self.last_url or self._get_entry_value(self.url_entry)
        if not url:
            messagebox.showinfo("Aucune URL", "Ajoute une URL pour ouvrir ce moment.")
            return
        seconds = minute_index * 60
        separator = "&" if "?" in url else "?"
        webbrowser.open(f"{url}{separator}t={seconds}s")

    def _build_moment_clip_text(self, moment) -> str:
        start = float(moment.minute_index * 60)
        duration = float(self._get_clip_duration())
        end = start + duration
        lines: List[str] = []
        for chunk in self.last_transcript_chunks:
            text = str(chunk.get("text", "")).replace("\n", " ").strip()
            if not text:
                continue
            try:
                chunk_start = float(chunk.get("start", 0.0) or 0.0)
                chunk_duration = float(chunk.get("duration", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            chunk_end = chunk_start + max(chunk_duration, 0.0)
            if chunk_start < end and chunk_end > start:
                lines.append(text)
        if lines:
            return "\n".join(lines)
        return str(getattr(moment, "excerpt", "")).strip()

    @staticmethod
    def _filename_timestamp(seconds: float) -> str:
        return seconds_to_timestamp(seconds).replace(":", "-")

    @staticmethod
    def _sanitize_filename_text(text: str, max_length: int = 96) -> str:
        cleaned = INVALID_FILENAME_CHARS_RE.sub(" ", text.replace("\n", " ").strip())
        cleaned = FILENAME_SPACES_RE.sub(" ", cleaned).strip(" ._-")
        if not cleaned:
            return "extrait"
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length].rstrip(" ._-")
        return cleaned or "extrait"

    def _build_moment_filename_label(self, moment) -> str:
        raw_text = self._build_moment_clip_text(moment)
        if not raw_text:
            raw_text = str(getattr(moment, "excerpt", "")).strip()
        return self._sanitize_filename_text(raw_text)

    def copy_moment_text(self, moment) -> None:
        content = self._build_moment_clip_text(moment)
        if not content:
            messagebox.showinfo(
                "Aucun texte",
                "Aucun texte trouvé pour cet extrait.",
            )
            return
        self.master.clipboard_clear()
        self.master.clipboard_append(content)
        timestamp = seconds_to_timestamp(moment.minute_index * 60)
        self._set_status(
            f"Texte de l'extrait {timestamp} copié ✓", busy=False, success=True
        )

    def _configure_transcript_tags(self) -> None:
        self.output_text.tag_configure(
            "timestamp",
            foreground=self.palette["muted"],
            font=(self.mono_family, 10, "bold"),
        )
        self.output_text.tag_configure(
            "bracket",
            foreground=self.palette["timestamp"],
            font=(self.mono_family, 10, "italic"),
        )

    def _apply_transcript_tags(self, lines: List[str]) -> None:
        for idx, line in enumerate(lines, start=1):
            match = TIMESTAMP_RE.match(line)
            if match:
                end = match.end()
                self.output_text.tag_add("timestamp", f"{idx}.0", f"{idx}.{end}")
            for bracket in BRACKET_RE.finditer(line):
                self.output_text.tag_add(
                    "bracket",
                    f"{idx}.{bracket.start()}",
                    f"{idx}.{bracket.end()}",
                )

    def _append_download_log(self, line: str) -> None:
        if not line:
            return
        self.download_log.configure(state="normal")
        self.download_log.insert(tk.END, f"{line}\n")
        if int(float(self.download_log.index("end-1c").split(".")[0])) > 200:
            self.download_log.delete("1.0", "2.0")
        self.download_log.configure(state="disabled")
        self.download_log.see(tk.END)

    def toggle_download_logs(self) -> None:
        if self.download_log_visible:
            self.download_log.grid_remove()
            self.download_toggle_button.configure(text="Voir les détails techniques")
            self.download_log_visible = False
        else:
            self.download_log.grid()
            self.download_toggle_button.configure(text="Masquer les détails")
            self.download_log_visible = True

    def _set_download_summary(
        self,
        index: int,
        total: int,
        start: int,
        duration: int,
        video_format: str,
        video_title: str = "",
        shorts_mode: bool = False,
        has_logo: bool = False,
        logo_position: str = download_utils.DEFAULT_LOGO_POSITION,
        logo_size_mode: str = "relative",
        logo_scale_percent: int = download_utils.DEFAULT_LOGO_SCALE_PERCENT,
        logo_opacity_percent: int = 100,
        has_subtitles: bool = False,
        subtitle_style: str = "impact",
        video_effect: str = "none",
        item_kind: str = "clip",
    ) -> None:
        kind = (item_kind or "clip").strip().lower()
        title_suffix = f" — {video_title}" if video_title else ""
        subtitle_label = ""
        if has_subtitles:
            subtitle_label = f" | sous-titres {subtitle_renderer.normalize_subtitle_style(subtitle_style)}"
        effect_label = ""
        normalized_effect = subtitle_renderer.normalize_video_effect(video_effect)
        if normalized_effect != "none":
            effect_label = f" | effet {normalized_effect.replace('_', ' ')}"
        if kind == "full_video":
            mode = ""
            if has_logo:
                position_label = download_utils.logo_position_label(logo_position)
                size_label = (
                    "taille originale"
                    if logo_size_mode == "original"
                    else f"{video_renderer.logo_frame_width_percent(logo_scale_percent)}% vidéo"
                )
                mode = f" | logo {size_label} {position_label} opacité {logo_opacity_percent}%"
            self.download_summary_var.set(
                f"Vidéo {index}/{total}{title_suffix} — vidéo entière — {video_format}{mode}{subtitle_label}{effect_label}"
            )
            self._set_download_phase("préparation du téléchargement")
            return
        if kind == "audio":
            self.download_summary_var.set(
                f"Audio {index}/{total}{title_suffix} — piste audio — {video_format}"
            )
            self._set_download_phase("préparation du téléchargement")
            return

        start_ts = seconds_to_timestamp(start)
        end_ts = seconds_to_timestamp(start + duration)
        mode_parts: List[str] = []
        if shorts_mode:
            mode_parts.append("shorts 9:16")
        else:
            mode_parts.append("normal 16:9")
        if has_logo:
            position_label = download_utils.logo_position_label(logo_position)
            size_label = (
                "taille originale"
                if logo_size_mode == "original"
                else f"{video_renderer.logo_frame_width_percent(logo_scale_percent)}% vidéo"
            )
            mode_parts.append(f"logo {size_label} {position_label} opacité {logo_opacity_percent}%")
        if has_subtitles:
            mode_parts.append(
                f"sous-titres {subtitle_renderer.normalize_subtitle_style(subtitle_style)}"
            )
        if normalized_effect != "none":
            mode_parts.append(f"effet {normalized_effect.replace('_', ' ')}")
        mode = f" | {', '.join(mode_parts)}" if mode_parts else ""
        self.download_summary_var.set(
            f"Clip {index}/{total}{title_suffix} — {start_ts} → {end_ts} — {video_format}{mode}"
        )
        self._set_download_phase("préparation du téléchargement")

    @staticmethod
    def _default_gui_settings() -> dict:
        return default_gui_settings()

    @staticmethod
    def _coerce_bool(value: object, default: bool) -> bool:
        return coerce_bool(value, default)

    @classmethod
    def _normalize_gui_settings(cls, raw: object) -> dict:
        return normalize_gui_settings(raw)

    def _load_gui_settings(self) -> dict:
        path = getattr(self, "gui_settings_path", None)
        return load_gui_settings(path, LOGGER)

    def _current_download_logo_path(self) -> str:
        entry = getattr(self, "download_logo_entry", None)
        if isinstance(entry, ttk.Entry):
            logo_path = self._get_entry_value(entry).strip()
        else:
            value = getattr(self, "download_logo_var", None)
            if value is not None and hasattr(value, "get"):
                logo_path = str(value.get()).strip()
            else:
                logo_path = ""
        if logo_path == DOWNLOAD_LOGO_PLACEHOLDER:
            return ""
        return logo_path

    def _save_gui_settings(self) -> None:
        path = getattr(self, "gui_settings_path", None)
        if not isinstance(path, Path):
            return
        defaults = self._default_gui_settings()

        aspect_mode = defaults["download_aspect_mode"]
        if hasattr(self, "download_aspect_ratio_var") and hasattr(
            self, "download_aspect_ratio_lookup"
        ):
            aspect_mode = self._selected_download_aspect_mode()

        video_format = defaults["video_format"]
        if hasattr(self, "video_format_var"):
            video_format = self._get_video_format()

        clip_duration = defaults["clip_duration"]
        if hasattr(self, "clip_duration_var"):
            clip_duration = self._get_clip_duration()

        logo_enabled_var = getattr(self, "download_logo_enabled_var", None)
        logo_enabled = defaults["download_logo_enabled"]
        if logo_enabled_var is not None and hasattr(logo_enabled_var, "get"):
            logo_enabled = bool(logo_enabled_var.get())

        logo_position = defaults["download_logo_position"]
        if hasattr(self, "download_logo_position_var") and hasattr(
            self, "download_logo_position_lookup"
        ):
            logo_position = self._selected_download_logo_position()

        logo_size_mode = defaults["download_logo_size_mode"]
        if hasattr(self, "download_logo_size_mode_var") and hasattr(
            self, "download_logo_size_mode_lookup"
        ):
            logo_size_mode = self._selected_download_logo_size_mode()

        logo_scale_percent = defaults["download_logo_scale_percent"]
        if hasattr(self, "download_logo_size_var"):
            logo_scale_percent = self._get_download_logo_scale_percent()

        logo_width_ratio = defaults["download_logo_width_ratio"]
        if hasattr(self, "download_logo_width_ratio_var"):
            logo_width_ratio = self._get_download_logo_width_ratio()
        else:
            logo_width_ratio = download_utils.logo_scale_percent_to_width_ratio(
                logo_scale_percent
            )

        logo_x_ratio = defaults["download_logo_x_ratio"]
        if hasattr(self, "download_logo_x_ratio_var"):
            logo_x_ratio = self._get_download_logo_x_ratio()
        else:
            logo_x_ratio, _logo_y_ratio = download_utils.logo_position_to_ratios(
                logo_position,
                logo_width_ratio,
            )

        logo_y_ratio = defaults["download_logo_y_ratio"]
        if hasattr(self, "download_logo_y_ratio_var"):
            logo_y_ratio = self._get_download_logo_y_ratio()
        else:
            _logo_x_ratio, logo_y_ratio = download_utils.logo_position_to_ratios(
                logo_position,
                logo_width_ratio,
            )

        logo_opacity_percent = defaults["download_logo_opacity_percent"]
        if hasattr(self, "download_logo_opacity_var"):
            logo_opacity_percent = self._get_download_logo_opacity_percent()

        logo_path = self._current_download_logo_path()

        subtitles_enabled_var = getattr(self, "download_subtitles_enabled_var", None)
        subtitles_enabled = defaults["download_subtitles_enabled"]
        if subtitles_enabled_var is not None and hasattr(subtitles_enabled_var, "get"):
            subtitles_enabled = bool(subtitles_enabled_var.get())

        subtitle_style = defaults["download_subtitle_style"]
        if hasattr(self, "download_subtitle_style_var") and hasattr(
            self, "download_subtitle_style_lookup"
        ):
            subtitle_style = self._selected_download_subtitle_style()

        video_effect = defaults["download_video_effect"]
        if hasattr(self, "download_video_effect_var") and hasattr(
            self, "download_video_effect_lookup"
        ):
            video_effect = self._selected_download_video_effect()

        intro_outro_enabled = defaults["download_intro_outro_enabled"]
        if hasattr(self, "download_intro_outro_enabled_var"):
            intro_outro_enabled = bool(self.download_intro_outro_enabled_var.get())
        progress_bar_enabled = defaults["download_progress_bar_enabled"]
        if hasattr(self, "download_progress_bar_enabled_var"):
            progress_bar_enabled = bool(self.download_progress_bar_enabled_var.get())
        animated_watermark_enabled = defaults["download_animated_watermark_enabled"]
        if hasattr(self, "download_animated_watermark_enabled_var"):
            animated_watermark_enabled = bool(
                self.download_animated_watermark_enabled_var.get()
            )

        lower_third_enabled = defaults["download_lower_third_enabled"]
        if hasattr(self, "download_lower_third_enabled_var"):
            lower_third_enabled = bool(self.download_lower_third_enabled_var.get())
        lower_third_name = defaults["download_lower_third_name"]
        if hasattr(self, "download_lower_third_name_var"):
            lower_third_name = self.download_lower_third_name_var.get()
        lower_third_tagline = defaults["download_lower_third_tagline"]
        if hasattr(self, "download_lower_third_tagline_var"):
            lower_third_tagline = self.download_lower_third_tagline_var.get()
        lower_third_subscribe = defaults["download_lower_third_subscribe"]
        if hasattr(self, "download_lower_third_subscribe_var"):
            lower_third_subscribe = bool(self.download_lower_third_subscribe_var.get())
        lower_third_bg_color = defaults["download_lower_third_bg_color"]
        if hasattr(self, "download_lower_third_bg_color_var"):
            lower_third_bg_color = self.download_lower_third_bg_color_var.get()
        lower_third_accent_color = defaults["download_lower_third_accent_color"]
        if hasattr(self, "download_lower_third_accent_color_var"):
            lower_third_accent_color = self.download_lower_third_accent_color_var.get()
        lower_third_interval = defaults["download_lower_third_interval"]
        if hasattr(self, "download_lower_third_interval_var"):
            lower_third_interval = self._get_download_lower_third_interval()
        lower_third_display_duration = defaults[
            "download_lower_third_display_duration"
        ]
        if hasattr(self, "download_lower_third_display_duration_var"):
            lower_third_display_duration = (
                self._get_download_lower_third_display_duration()
            )

        download_preset = defaults["download_preset"]
        if hasattr(self, "download_preset_var") and hasattr(
            self, "download_preset_lookup"
        ):
            download_preset = self._selected_download_preset()

        snapshot = self._normalize_gui_settings(
            {
                "download_aspect_mode": aspect_mode,
                "video_format": video_format,
                "clip_duration": clip_duration,
                "download_logo_enabled": logo_enabled,
                "download_logo_path": logo_path,
                "download_logo_position": logo_position,
                "download_logo_size_mode": logo_size_mode,
                "download_logo_scale_percent": logo_scale_percent,
                "download_logo_opacity_percent": logo_opacity_percent,
                "download_logo_width_ratio": logo_width_ratio,
                "download_logo_x_ratio": logo_x_ratio,
                "download_logo_y_ratio": logo_y_ratio,
                "download_subtitles_enabled": subtitles_enabled,
                "download_subtitle_style": subtitle_style,
                "download_video_effect": video_effect,
                "download_intro_outro_enabled": intro_outro_enabled,
                "download_progress_bar_enabled": progress_bar_enabled,
                "download_animated_watermark_enabled": animated_watermark_enabled,
                "download_lower_third_enabled": lower_third_enabled,
                "download_lower_third_name": lower_third_name,
                "download_lower_third_tagline": lower_third_tagline,
                "download_lower_third_subscribe": lower_third_subscribe,
                "download_lower_third_bg_color": lower_third_bg_color,
                "download_lower_third_accent_color": lower_third_accent_color,
                "download_lower_third_interval": lower_third_interval,
                "download_lower_third_display_duration": lower_third_display_duration,
                "download_preset": download_preset,
                "ytdlp_cookies_browser": self._selected_cookies_browser(),
            }
        )
        self.gui_settings = save_gui_settings(path, snapshot, LOGGER)

    def _apply_gui_settings(self, settings: dict | None = None) -> None:
        snapshot = self._normalize_gui_settings(settings if settings is not None else {})
        self.gui_settings = snapshot

        selected_mode = snapshot.get("download_aspect_mode", "landscape")
        selected_label = next(
            (
                label
                for label, mode in self.download_aspect_ratio_lookup.items()
                if mode == selected_mode
            ),
            "Normal 16:9",
        )
        self.download_aspect_ratio_var.set(selected_label)

        self.video_format_var.set(str(snapshot.get("video_format", "mp4")))
        self.clip_duration_var.set(int(snapshot.get("clip_duration", 60)))

        self.download_logo_enabled_var.set(
            bool(snapshot.get("download_logo_enabled", True))
        )
        self.download_logo_var.set(str(snapshot.get("download_logo_path", "")))

        selected_position = str(
            snapshot.get(
                "download_logo_position",
                download_utils.DEFAULT_LOGO_POSITION,
            )
        )
        selected_position_label = next(
            (
                label
                for label, value in self.download_logo_position_lookup.items()
                if value == selected_position
            ),
            "Haut droit",
        )
        self.download_logo_position_var.set(selected_position_label)

        selected_size_mode = str(snapshot.get("download_logo_size_mode", "relative"))
        selected_size_mode_label = next(
            (
                label
                for label, value in self.download_logo_size_mode_lookup.items()
                if value == selected_size_mode
            ),
            "Taille relative",
        )
        self.download_logo_size_mode_var.set(selected_size_mode_label)

        logo_width_ratio = download_utils.normalize_logo_width_ratio(
            snapshot.get(
                "download_logo_width_ratio",
                download_utils.DEFAULT_LOGO_WIDTH_RATIO,
            )
        )
        logo_scale_percent = download_utils.logo_width_ratio_to_scale_percent(
            logo_width_ratio
        )
        self.download_logo_size_var.set(logo_scale_percent)
        self.download_logo_size_label_var.set(
            self._download_logo_size_label(logo_scale_percent, selected_size_mode)
        )
        if hasattr(self, "download_logo_width_ratio_var"):
            self.download_logo_width_ratio_var.set(logo_width_ratio)
        if hasattr(self, "download_logo_x_ratio_var"):
            self.download_logo_x_ratio_var.set(
                download_utils.normalize_logo_x_ratio(
                    snapshot.get(
                        "download_logo_x_ratio",
                        download_utils.DEFAULT_LOGO_X_RATIO,
                    ),
                    logo_width_ratio,
                )
            )
        if hasattr(self, "download_logo_y_ratio_var"):
            self.download_logo_y_ratio_var.set(
                download_utils.normalize_logo_y_ratio(
                    snapshot.get(
                        "download_logo_y_ratio",
                        download_utils.DEFAULT_LOGO_Y_RATIO,
                    )
                )
            )

        logo_opacity_percent = int(snapshot.get("download_logo_opacity_percent", 100))
        self.download_logo_opacity_var.set(logo_opacity_percent)
        self.download_logo_opacity_label_var.set(f"{logo_opacity_percent}%")

        if hasattr(self, "download_subtitles_enabled_var"):
            self.download_subtitles_enabled_var.set(
                bool(snapshot.get("download_subtitles_enabled", True))
            )

        selected_subtitle_style = str(snapshot.get("download_subtitle_style", "impact"))
        subtitle_style_lookup = getattr(
            self,
            "download_subtitle_style_lookup",
            {"Impact TikTok": "impact"},
        )
        selected_subtitle_label = next(
            (
                label
                for label, value in subtitle_style_lookup.items()
                if value == selected_subtitle_style
            ),
            "Impact TikTok",
        )
        if hasattr(self, "download_subtitle_style_var"):
            self.download_subtitle_style_var.set(selected_subtitle_label)

        selected_video_effect = str(snapshot.get("download_video_effect", "none"))
        video_effect_lookup = getattr(
            self,
            "download_video_effect_lookup",
            {"Aucun": "none"},
        )
        selected_effect_label = next(
            (
                label
                for label, value in video_effect_lookup.items()
                if value == selected_video_effect
            ),
            "Aucun",
        )
        if hasattr(self, "download_video_effect_var"):
            self.download_video_effect_var.set(selected_effect_label)

        if hasattr(self, "download_intro_outro_enabled_var"):
            self.download_intro_outro_enabled_var.set(
                bool(snapshot.get("download_intro_outro_enabled", False))
            )
        if hasattr(self, "download_progress_bar_enabled_var"):
            self.download_progress_bar_enabled_var.set(
                bool(snapshot.get("download_progress_bar_enabled", False))
            )
        if hasattr(self, "download_animated_watermark_enabled_var"):
            self.download_animated_watermark_enabled_var.set(
                bool(snapshot.get("download_animated_watermark_enabled", False))
            )

        if hasattr(self, "download_lower_third_enabled_var"):
            self.download_lower_third_enabled_var.set(
                bool(snapshot.get("download_lower_third_enabled", False))
            )
        if hasattr(self, "download_lower_third_name_var"):
            self.download_lower_third_name_var.set(
                str(snapshot.get("download_lower_third_name", ""))
            )
        if hasattr(self, "download_lower_third_tagline_var"):
            self.download_lower_third_tagline_var.set(
                str(snapshot.get("download_lower_third_tagline", ""))
            )
        if hasattr(self, "download_lower_third_subscribe_var"):
            self.download_lower_third_subscribe_var.set(
                bool(snapshot.get("download_lower_third_subscribe", True))
            )
        if hasattr(self, "download_lower_third_bg_color_var"):
            self.download_lower_third_bg_color_var.set(
                lower_third.normalize_hex_color(
                    snapshot.get("download_lower_third_bg_color", ""),
                    lower_third.DEFAULT_BG_COLOR,
                )
            )
        if hasattr(self, "download_lower_third_accent_color_var"):
            self.download_lower_third_accent_color_var.set(
                lower_third.normalize_hex_color(
                    snapshot.get("download_lower_third_accent_color", ""),
                    lower_third.DEFAULT_ACCENT_COLOR,
                )
            )
        if hasattr(self, "download_lower_third_interval_var"):
            self.download_lower_third_interval_var.set(
                int(
                    snapshot.get(
                        "download_lower_third_interval",
                        lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS,
                    )
                )
            )
        if hasattr(self, "download_lower_third_display_duration_var"):
            self.download_lower_third_display_duration_var.set(
                int(
                    snapshot.get(
                        "download_lower_third_display_duration",
                        lower_third.DEFAULT_DISPLAY_DURATION_SECONDS,
                    )
                )
            )
        self._sync_lower_third_timing_labels()

        selected_preset = str(snapshot.get("download_preset", "custom"))
        preset_lookup = getattr(
            self,
            "download_preset_lookup",
            {"Personnalisé": "custom"},
        )
        selected_preset_label = next(
            (
                label
                for label, value in preset_lookup.items()
                if value == selected_preset
            ),
            "Personnalisé",
        )
        if hasattr(self, "download_preset_var"):
            self.download_preset_var.set(selected_preset_label)

        saved_browser = str(snapshot.get("ytdlp_cookies_browser", "")).strip().lower()
        browser_label = {
            "chrome": "Chrome", "firefox": "Firefox",
            "safari": "Safari", "edge": "Edge", "brave": "Brave",
        }.get(saved_browser, "Aucun")
        if hasattr(self, "ytdlp_cookies_browser_var"):
            self.ytdlp_cookies_browser_var.set(browser_label)
        self._update_download_logo_controls_state()
        self._update_value_add_controls_state()
        self._update_lower_third_controls_state()
        self._redraw_logo_preview()

    def _on_download_preferences_change(self, *_: object) -> None:
        self._redraw_logo_preview()
        self._update_config_summary()
        self._save_gui_settings()

    def _on_value_add_change(self, *_: object) -> None:
        self._update_value_add_controls_state()
        self._update_download_logo_controls_state()
        self._update_lower_third_controls_state()
        self._update_config_summary()
        self._save_gui_settings()

    def _on_lower_third_change(self, *_: object) -> None:
        self._update_lower_third_controls_state()
        self._redraw_lower_third_preview()
        self._update_config_summary()
        self._save_gui_settings()

    def _on_lower_third_color_change(self, *_: object) -> None:
        self._update_lower_third_controls_state()
        self._redraw_lower_third_preview()
        self._save_gui_settings()

    def _on_lower_third_preview_change(self, *_: object) -> None:
        self._sync_lower_third_scale_labels()
        self._redraw_lower_third_preview()

    def _on_lower_third_timing_change(self, *_: object) -> None:
        self._sync_lower_third_timing_labels()
        self._save_gui_settings()

    def _on_download_aspect_change(self, *_: object) -> None:
        self._redraw_logo_preview()
        self._update_config_summary()
        # Le fond flouté n'est pertinent qu'en mode Shorts
        if hasattr(self, "download_shorts_blur_check"):
            is_shorts = self._selected_download_aspect_mode() == "shorts"
            self.download_shorts_blur_check.configure(
                state="normal" if is_shorts else "disabled"
            )
        self._save_gui_settings()

    def _on_download_logo_position_change(self, *_: object) -> None:
        if not hasattr(self, "download_logo_x_ratio_var") or not hasattr(
            self,
            "download_logo_y_ratio_var",
        ):
            self._save_gui_settings()
            return
        width_ratio = self._get_download_logo_width_ratio()
        x_ratio, y_ratio = download_utils.logo_position_to_ratios(
            self._selected_download_logo_position(),
            width_ratio,
        )
        self.download_logo_x_ratio_var.set(x_ratio)
        self.download_logo_y_ratio_var.set(y_ratio)
        self._redraw_logo_preview()
        self._save_gui_settings()

    def _on_download_preset_change(self, *_: object) -> None:
        preset_key = self._selected_download_preset()
        preset = video_presets.preset_by_key(preset_key)
        if preset.key != "custom":
            aspect_label = next(
                (
                    label
                    for label, value in self.download_aspect_ratio_lookup.items()
                    if value == preset.aspect_mode
                ),
                "Normal 16:9",
            )
            self.download_aspect_ratio_var.set(aspect_label)
            self.download_subtitles_enabled_var.set(preset.subtitles_enabled)

            subtitle_label = next(
                (
                    label
                    for label, value in self.download_subtitle_style_lookup.items()
                    if value == preset.subtitle_style
                ),
                "Impact TikTok",
            )
            self.download_subtitle_style_var.set(subtitle_label)

            effect_label = next(
                (
                    label
                    for label, value in self.download_video_effect_lookup.items()
                    if value == preset.video_effect
                ),
                "Aucun",
            )
            self.download_video_effect_var.set(effect_label)
            if preset.clip_duration is not None:
                self.clip_duration_var.set(preset.clip_duration)
        self._save_gui_settings()

    def _on_download_logo_size_mode_change(self, *_: object) -> None:
        if hasattr(self, "download_logo_size_label_var"):
            self.download_logo_size_label_var.set(
                self._download_logo_size_label(
                    self._get_download_logo_scale_percent(),
                    self._selected_download_logo_size_mode(),
                )
            )
        self._redraw_logo_preview()
        self._update_download_logo_controls_state()
        self._save_gui_settings()

    def _on_download_logo_focus_out(self, _event: tk.Event) -> None:
        self._save_gui_settings()

    def _fetch_lower_third_from_url(self) -> None:
        url = self.last_url or self._get_entry_value(self.url_entry)
        if not url:
            messagebox.showwarning("Aucune URL", "Ajoute d'abord une URL vidéo.")
            return
        yt_dlp_cmd = self._resolve_yt_dlp_cmd()
        if not yt_dlp_cmd:
            messagebox.showerror("yt-dlp manquant", "yt-dlp est requis pour récupérer les métadonnées.")
            return
        btn = getattr(self, "download_lower_third_fetch_button", None)
        if btn:
            btn.configure(state="disabled", text="…")

        def _do_fetch() -> None:
            cmd = [
                *yt_dlp_cmd,
                "--no-playlist", "--skip-download",
                "--print", "%(channel)s",
                "--print", "%(title)s",
                url,
            ]
            try:
                result = subprocess.run(
                    cmd, check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, timeout=25,
                )
                lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
                channel = lines[0] if len(lines) > 0 else ""
                title = lines[1] if len(lines) > 1 else ""
            except Exception:
                channel = ""
                title = ""
            self.master.after(0, self._apply_lower_third_metadata, channel, title)

        threading.Thread(target=_do_fetch, daemon=True).start()

    def _apply_lower_third_metadata(self, channel: str, title: str) -> None:
        btn = getattr(self, "download_lower_third_fetch_button", None)
        if btn:
            btn.configure(state="normal", text="Récupérer ↓")
        if not channel and not title:
            messagebox.showwarning(
                "Métadonnées indisponibles",
                "Impossible de récupérer les informations de la vidéo.",
            )
            return
        if channel:
            self.download_lower_third_name_var.set(channel)
        if title:
            tagline = title[:52] + "…" if len(title) > 52 else title
            self.download_lower_third_tagline_var.set(tagline)

    def _on_intro_outro_toggle(self) -> None:
        panel = getattr(self, "download_intro_outro_options", None)
        if panel is None:
            return
        if self.download_intro_outro_enabled_var.get():
            panel.grid()
        else:
            panel.grid_remove()

    def _pick_intro_outro_color(self, var: tk.StringVar, swatch: tk.Label) -> None:
        color = colorchooser.askcolor(color=var.get())[1]
        if color:
            var.set(color)
            try:
                swatch.configure(bg=color)
            except tk.TclError:
                pass

    def _hex_to_ffmpeg_color(self, hex_color: str, opacity: float = 0.55) -> str:
        color = str(hex_color or "#000000").strip().lstrip("#")
        if len(color) == 6:
            return f"0x{color}@{opacity}"
        return "0x000000@0.55"

    def _pick_lower_third_color(self, var: tk.StringVar) -> None:
        color = colorchooser.askcolor(color=var.get())[1]
        if color:
            var.set(color)

    def _download_lower_third_enabled(self) -> bool:
        enabled_var = getattr(self, "download_lower_third_enabled_var", None)
        return (
            bool(enabled_var.get())
            if enabled_var is not None and hasattr(enabled_var, "get")
            else False
        )

    def _intro_outro_enabled(self) -> bool:
        enabled_var = getattr(self, "download_intro_outro_enabled_var", None)
        return (
            bool(enabled_var.get())
            if enabled_var is not None and hasattr(enabled_var, "get")
            else False
        )

    def _progress_bar_enabled(self) -> bool:
        enabled_var = getattr(self, "download_progress_bar_enabled_var", None)
        return (
            bool(enabled_var.get())
            if enabled_var is not None and hasattr(enabled_var, "get")
            else False
        )

    def _animated_watermark_enabled(self) -> bool:
        enabled_var = getattr(self, "download_animated_watermark_enabled_var", None)
        return (
            bool(enabled_var.get())
            if enabled_var is not None and hasattr(enabled_var, "get")
            else False
        )

    def _update_value_add_controls_state(self) -> None:
        state = "disabled" if getattr(self, "busy", False) else "normal"
        for name in (
            "download_intro_outro_check",
            "download_progress_bar_check",
            "download_animated_watermark_check",
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(state=state)

    def _selected_value_add_options(self) -> dict | None:
        intro_outro_enabled = self._intro_outro_enabled()
        progress_bar_enabled = self._progress_bar_enabled()
        animated_watermark_enabled = self._animated_watermark_enabled()
        channel_name = (
            self.download_lower_third_name_var.get()
            if hasattr(self, "download_lower_third_name_var")
            else ""
        ).strip()
        if intro_outro_enabled and not channel_name:
            messagebox.showwarning(
                "Intro / Outro incomplet",
                "Renseigne le nom de la chaîne pour afficher l'intro/outro.",
            )
            return None

        watermark_logo_path = ""
        if animated_watermark_enabled:
            watermark_logo_path = self._validated_download_logo_path()
            if watermark_logo_path is None:
                return None
            if not watermark_logo_path:
                messagebox.showwarning(
                    "Filigrane incomplet",
                    "Sélectionne un logo pour ajouter le filigrane animé.",
                )
                return None

        try:
            hold = max(0.5, float(getattr(self, "download_intro_outro_hold_var", None) and self.download_intro_outro_hold_var.get() or 1.5))
        except (TypeError, ValueError):
            hold = 1.5
        bg_hex = str(getattr(self, "download_intro_outro_bg_color_var", None) and self.download_intro_outro_bg_color_var.get() or "#000000")
        text_hex = str(getattr(self, "download_intro_outro_text_color_var", None) and self.download_intro_outro_text_color_var.get() or "#FFFFFF")
        return {
            "intro_outro_enabled": intro_outro_enabled,
            "intro_outro_channel_name": channel_name,
            "intro_outro_hold_duration": hold,
            "intro_outro_bg_color": self._hex_to_ffmpeg_color(bg_hex, 0.75),
            "intro_outro_text_color": text_hex,
            "progress_bar_enabled": progress_bar_enabled,
            "animated_watermark_enabled": animated_watermark_enabled,
            "watermark_logo_path": watermark_logo_path,
        }

    def _get_download_lower_third_interval(self) -> int:
        var = getattr(self, "download_lower_third_interval_var", None)
        try:
            value = int(round(float(var.get()))) if var is not None else 0
        except (TypeError, ValueError, tk.TclError):
            value = lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS
        return max(
            lower_third.MIN_DISPLAY_INTERVAL_SECONDS,
            min(lower_third.MAX_DISPLAY_INTERVAL_SECONDS, value),
        )

    def _get_download_lower_third_display_duration(self) -> int:
        var = getattr(self, "download_lower_third_display_duration_var", None)
        try:
            value = int(round(float(var.get()))) if var is not None else 0
        except (TypeError, ValueError, tk.TclError):
            value = lower_third.DEFAULT_DISPLAY_DURATION_SECONDS
        return max(
            lower_third.MIN_DISPLAY_DURATION_SECONDS,
            min(lower_third.MAX_DISPLAY_DURATION_SECONDS, value),
        )

    def _sync_lower_third_timing_labels(self) -> None:
        if hasattr(self, "download_lower_third_interval_label_var"):
            self.download_lower_third_interval_label_var.set(
                f"{self._get_download_lower_third_interval()}s"
            )
        if hasattr(self, "download_lower_third_display_duration_label_var"):
            self.download_lower_third_display_duration_label_var.set(
                f"{self._get_download_lower_third_display_duration()}s"
            )

    def _update_lower_third_controls_state(self) -> None:
        enabled = self._download_lower_third_enabled()
        needs_channel_name = self._intro_outro_enabled()
        visible = enabled or needs_channel_name
        frame = getattr(self, "download_lower_third_frame", None)
        if frame is not None:
            if visible:
                frame.grid()
            else:
                frame.grid_remove()

        state = "normal" if visible and not getattr(self, "busy", False) else "disabled"
        for name in (
            "download_lower_third_name_entry",
            "download_lower_third_tagline_entry",
            "download_lower_third_subscribe_check",
            "download_lower_third_bg_button",
            "download_lower_third_accent_button",
            "download_lower_third_interval_scale",
            "download_lower_third_display_duration_scale",
            "download_lower_third_title_scale_slider",
            "download_lower_third_tagline_scale_slider",
            "download_lower_third_subscribe_text_entry",
            "download_lower_third_bg_opacity_slider",
            "download_lower_third_valign_combo",
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(state=state)

        # Subscribe text entry enabled only when subscribe button is shown
        sub_text_entry = getattr(self, "download_lower_third_subscribe_text_entry", None)
        if sub_text_entry is not None and visible and not getattr(self, "busy", False):
            sub_on = bool(
                self.download_lower_third_subscribe_var.get()
                if hasattr(self, "download_lower_third_subscribe_var") else True
            )
            sub_text_entry.configure(state="normal" if sub_on else "disabled")

        # Valign row: only visible for "Centré haut" position
        valign_row = getattr(self, "_lt_valign_row", None)
        if valign_row is not None:
            pos_label = (
                self.download_lower_third_position_var.get()
                if hasattr(self, "download_lower_third_position_var") else ""
            )
            if visible and pos_label == "Centré haut":
                valign_row.grid()
            else:
                valign_row.grid_remove()

        bg_swatch = getattr(self, "download_lower_third_bg_swatch", None)
        if bg_swatch is not None and hasattr(self, "download_lower_third_bg_color_var"):
            bg_swatch.configure(
                bg=lower_third.normalize_hex_color(
                    self.download_lower_third_bg_color_var.get(),
                    lower_third.DEFAULT_BG_COLOR,
                )
            )
        accent_swatch = getattr(self, "download_lower_third_accent_swatch", None)
        if accent_swatch is not None and hasattr(
            self,
            "download_lower_third_accent_color_var",
        ):
            accent_swatch.configure(
                bg=lower_third.normalize_hex_color(
                    self.download_lower_third_accent_color_var.get(),
                    lower_third.DEFAULT_ACCENT_COLOR,
                )
            )

    def _selected_download_lower_third_config(
        self,
        *,
        show_error: bool = True,
    ) -> lower_third.LowerThirdConfig | None:
        if not self._download_lower_third_enabled():
            return None

        name = (
            self.download_lower_third_name_var.get()
            if hasattr(self, "download_lower_third_name_var")
            else ""
        ).strip()
        if not name:
            if show_error:
                messagebox.showwarning(
                    "Lower third incomplet",
                    "Renseigne le nom de la chaîne pour ajouter le lower third.",
                )
            return None

        video_format = (
            "9:16" if self._selected_download_aspect_mode() == "shorts" else "16:9"
        )
        _bg_opacity = (
            self.download_lower_third_bg_opacity_var.get()
            if hasattr(self, "download_lower_third_bg_opacity_var") else 86
        )
        _title_scale = (
            self.download_lower_third_title_scale_var.get()
            if hasattr(self, "download_lower_third_title_scale_var") else 100
        ) / 100.0
        _tagline_scale = (
            self.download_lower_third_tagline_scale_var.get()
            if hasattr(self, "download_lower_third_tagline_scale_var") else 100
        ) / 100.0
        _sub_text = (
            self.download_lower_third_subscribe_text_var.get().strip()
            if hasattr(self, "download_lower_third_subscribe_text_var") else ""
        ) or "Abonnez-vous"
        return lower_third.config_from_hex(
            channel_name=name,
            tagline=(
                self.download_lower_third_tagline_var.get()
                if hasattr(self, "download_lower_third_tagline_var")
                else ""
            ),
            bg_color=(
                self.download_lower_third_bg_color_var.get()
                if hasattr(self, "download_lower_third_bg_color_var")
                else lower_third.DEFAULT_BG_COLOR
            ),
            accent_color=(
                self.download_lower_third_accent_color_var.get()
                if hasattr(self, "download_lower_third_accent_color_var")
                else lower_third.DEFAULT_ACCENT_COLOR
            ),
            show_subscribe=(
                bool(self.download_lower_third_subscribe_var.get())
                if hasattr(self, "download_lower_third_subscribe_var")
                else True
            ),
            video_format=video_format,
            position=self._selected_lower_third_position(),
            bg_alpha=int(_bg_opacity * 2.55),
            title_scale=_title_scale,
            tagline_scale=_tagline_scale,
            subscribe_text=_sub_text,
            vertical_align=self._selected_lower_third_valign(),
        )

    def _selected_lower_third_position(self) -> str:
        var = getattr(self, "download_lower_third_position_var", None)
        if var is None:
            return "bottom"
        label = var.get()
        return {"Haut": "top", "Centré haut": "top-center"}.get(label, "bottom")

    def _selected_lower_third_valign(self) -> str:
        var = getattr(self, "download_lower_third_valign_var", None)
        if var is None:
            return "top"
        label = var.get()
        return {"Centre": "center", "Bas": "bottom"}.get(label, "top")

    def _sync_lower_third_scale_labels(self) -> None:
        t_var = getattr(self, "download_lower_third_title_scale_var", None)
        t_lbl = getattr(self, "download_lower_third_title_scale_label_var", None)
        if t_var and t_lbl:
            t_lbl.set(f"{t_var.get()}%")
        g_var = getattr(self, "download_lower_third_tagline_scale_var", None)
        g_lbl = getattr(self, "download_lower_third_tagline_scale_label_var", None)
        if g_var and g_lbl:
            g_lbl.set(f"{g_var.get()}%")
        o_var = getattr(self, "download_lower_third_bg_opacity_var", None)
        o_lbl = getattr(self, "download_lower_third_bg_opacity_label_var", None)
        if o_var and o_lbl:
            o_lbl.set(f"{o_var.get()}%")

    def _redraw_lower_third_preview(self) -> None:
        canvas = getattr(self, "download_lower_third_preview_canvas", None)
        if canvas is None:
            return
        try:
            canvas.update_idletasks()
            cw = max(1, canvas.winfo_width())
            ch = max(1, canvas.winfo_height())
            canvas.delete("all")
        except tk.TclError:
            return

        # Background frame
        canvas.create_rectangle(
            1, 1, cw - 2, ch - 2,
            fill=self.palette["bg_alt"], outline=self.palette["shadow"],
        )

        position = self._selected_lower_third_position()
        is_portrait = (position == "top-center")
        vw, vh = (1080, 1920) if is_portrait else (1920, 1080)

        name_var = getattr(self, "download_lower_third_name_var", None)
        name = (name_var.get().strip() if name_var else "") or "Nom de la chaîne"

        opacity_var = getattr(self, "download_lower_third_bg_opacity_var", None)
        bg_alpha = int((opacity_var.get() if opacity_var else 86) * 2.55)

        title_s_var = getattr(self, "download_lower_third_title_scale_var", None)
        title_scale = (title_s_var.get() if title_s_var else 100) / 100.0
        tag_s_var = getattr(self, "download_lower_third_tagline_scale_var", None)
        tagline_scale = (tag_s_var.get() if tag_s_var else 100) / 100.0
        sub_text_var = getattr(self, "download_lower_third_subscribe_text_var", None)
        sub_text = (sub_text_var.get().strip() if sub_text_var else "") or "Abonnez-vous"

        video_format = "9:16" if is_portrait else "16:9"
        try:
            cfg = lower_third.config_from_hex(
                channel_name=name,
                tagline=(
                    self.download_lower_third_tagline_var.get()
                    if hasattr(self, "download_lower_third_tagline_var") else ""
                ),
                bg_color=(
                    self.download_lower_third_bg_color_var.get()
                    if hasattr(self, "download_lower_third_bg_color_var")
                    else lower_third.DEFAULT_BG_COLOR
                ),
                accent_color=(
                    self.download_lower_third_accent_color_var.get()
                    if hasattr(self, "download_lower_third_accent_color_var")
                    else lower_third.DEFAULT_ACCENT_COLOR
                ),
                show_subscribe=(
                    bool(self.download_lower_third_subscribe_var.get())
                    if hasattr(self, "download_lower_third_subscribe_var") else True
                ),
                video_format=video_format,
                position=position,
                bg_alpha=bg_alpha,
                title_scale=title_scale,
                tagline_scale=tagline_scale,
                subscribe_text=sub_text,
                vertical_align=self._selected_lower_third_valign(),
            )
            lt_img = lower_third.generate_lower_third_image(cfg, vw, vh)
        except Exception:
            canvas.create_text(
                cw // 2, ch // 2, text="Erreur aperçu",
                fill=self.palette["danger"], font=(self.font_family, 8),
            )
            return

        if is_portrait:
            # Draw a simulated 9:16 shorts frame on the canvas
            scale = ch / vh
            fg_h_virt = int(vw * 9 / 16)          # 607 px
            pb_h_virt = (vh - fg_h_virt) // 2      # 656 px
            pb_canvas = int(pb_h_virt * scale)
            fg_canvas = int(fg_h_virt * scale)

            # Bottom pillarbox (blurred mirror)
            canvas.create_rectangle(1, 1, cw - 2, ch - 2, fill="#555555")
            # Video zone (slightly warmer)
            canvas.create_rectangle(1, pb_canvas, cw - 2, pb_canvas + fg_canvas, fill="#6a5040")
            # Top pillarbox grid lines
            canvas.create_line(cw // 3, 1, cw // 3, pb_canvas - 1, fill="#666666")
            canvas.create_line(2 * cw // 3, 1, 2 * cw // 3, pb_canvas - 1, fill="#666666")

            # Place the lower-third band at the correct y position
            _valign = self._selected_lower_third_valign()
            band_h_virt = lower_third.lower_third_band_height(cfg, vh)
            if _valign == "bottom":
                y_off_virt = max(0, pb_h_virt - band_h_virt)
            elif _valign == "center":
                y_off_virt = max(0, (pb_h_virt - band_h_virt) // 2)
            else:
                y_off_virt = 0
            y_off_canvas = int(y_off_virt * scale)
            band_h_canvas = max(1, int(band_h_virt * scale))

            try:
                band_resized = lt_img.resize((cw, band_h_canvas), Image.LANCZOS)
                self._lt_preview_tk = ImageTk.PhotoImage(band_resized)
                canvas.create_image(0, y_off_canvas, anchor="nw", image=self._lt_preview_tk)
            except Exception:
                pass
        else:
            # Standard lower third: full-frame image, just resize to canvas
            try:
                resized = lt_img.resize((cw, ch), Image.LANCZOS)
                self._lt_preview_tk = ImageTk.PhotoImage(resized)
                canvas.create_image(0, 0, anchor="nw", image=self._lt_preview_tk)
            except Exception:
                pass

    @staticmethod
    def _empty_download_history() -> dict:
        return history_store.empty_download_history()

    def _normalize_download_history(self, raw: object) -> dict:
        return history_store.normalize_download_history(raw)

    def _load_download_history(self) -> dict:
        path = getattr(self, "download_history_path", None)
        return history_store.load_download_history(path, LOGGER)

    def _save_download_history(self, snapshot: dict | None = None) -> None:
        path = getattr(self, "download_history_path", None)
        if not isinstance(path, Path):
            return
        if snapshot is None:
            lock = getattr(self, "download_history_lock", None)
            if lock is not None:
                with lock:
                    snapshot = json.loads(json.dumps(self.download_history, ensure_ascii=False))
            else:
                snapshot = json.loads(json.dumps(self.download_history, ensure_ascii=False))
        history_store.save_download_history(path, snapshot, LOGGER)

    def _history_key_for_url(self, url: str) -> tuple[str, str]:
        return history_store.history_key_for_url(url)

    @staticmethod
    def _format_history_timestamp(value: str) -> str:
        return history_store.format_history_timestamp(value)

    def _resolve_video_title(self, url: str, yt_dlp_cmd: List[str]) -> str:
        url = (url or "").strip()
        if not url:
            return "Titre inconnu"
        cached = self.video_title_cache.get(url)
        if cached:
            return cached

        title = ""
        if yt_dlp_cmd:
            title_cmd = [
                *yt_dlp_cmd,
                "--no-playlist",
                "--skip-download",
                "--print",
                "%(title)s",
                url,
            ]
            try:
                completed = subprocess.run(
                    title_cmd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=25,
                )
                for line in completed.stdout.splitlines():
                    cleaned = line.strip()
                    if cleaned:
                        title = cleaned
                        break
            except (
                OSError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ) as error:
                LOGGER.warning("Impossible de récupérer le titre vidéo pour %s: %s", url, error)

        if not title:
            try:
                title = f"YouTube ({extract_video_id(url)})"
            except VideoIdExtractionError:
                title = "Titre inconnu"
        self.video_title_cache[url] = title
        return title

    def _record_download_history(self, item: dict, final_path: Path) -> None:
        url = str(item.get("url", "")).strip()
        if not url:
            return
        with self.download_history_lock:
            snapshot = history_store.add_download_record(
                self.download_history,
                item,
                final_path,
                video_title_cache=self.video_title_cache,
            )

        self._save_download_history(snapshot)
        self.master.after(0, self._refresh_download_history_view)

    def _format_download_history_lines(self) -> List[str]:
        with self.download_history_lock:
            snapshot = json.loads(json.dumps(self.download_history, ensure_ascii=False))
        return history_store.format_download_history_lines(snapshot)

    def _refresh_download_history_view(self) -> None:
        widget = getattr(self, "download_history_text", None)
        if widget is None:
            return
        lines = self._format_download_history_lines()
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, "\n".join(lines))
        widget.configure(state="disabled")
        widget.see("1.0")

    def clear_download_history(self) -> None:
        should_clear = messagebox.askyesno(
            "Effacer l'historique",
            "Supprimer l'historique des liens et téléchargements enregistrés ?",
        )
        if not should_clear:
            return
        with self.download_history_lock:
            self.download_history = self._empty_download_history()
            snapshot = json.loads(json.dumps(self.download_history, ensure_ascii=False))
        self._save_download_history(snapshot)
        self._refresh_download_history_view()
        self._append_download_log("Historique des téléchargements effacé.")

    def _set_download_phase(self, phase: str) -> None:
        phase_var = getattr(self, "download_phase_var", None)
        if phase_var is None:
            return
        phase_var.set(f"Étape: {phase}")

    @staticmethod
    def _parse_size_to_bytes(size: str) -> int | None:
        return download_utils.parse_size_to_bytes(size)

    @staticmethod
    def _format_bytes(value: int) -> str:
        return download_utils.format_bytes(value)

    @classmethod
    def _format_download_size_progress(cls, percent: float, total_size: str) -> str:
        return download_utils.format_download_size_progress(percent, total_size)

    def _log_download_percent_steps(
        self,
        percent: float,
        size: str,
        speed: str,
        eta: str,
    ) -> None:
        target = max(0, min(100, int(percent)))
        start = max(0, getattr(self, "download_last_percent_logged", -1) + 1)
        if target < start:
            return
        if size:
            self.download_last_size = size
        size_token = size or getattr(self, "download_last_size", "")
        for value in range(start, target + 1):
            progress_line = f"[progress] {value}%"
            size_info = self._format_download_size_progress(value, size_token)
            if size_info:
                progress_line += f" • {size_info}"
            if speed:
                progress_line += f" • {speed}"
            if eta:
                progress_line += f" • ETA {eta}"
            self._append_download_log(progress_line)
        self.download_last_percent_logged = target

    def _update_download_progress(
        self, percent: float, size: str, speed: str, eta: str
    ) -> None:
        percent = max(0.0, min(100.0, float(percent)))
        total = max(1, self.download_total)
        self.download_overall_progress.set_segments(self.download_completed, total, percent)
        self.download_current_progress.configure(value=percent)
        idx = getattr(self, "_current_download_card_index", None)
        if idx is not None:
            bar = getattr(self, "_moment_mini_bars", {}).get(idx)
            if bar:
                bar.configure(value=percent)
        overall_percent = ((self.download_completed + (percent / 100.0)) / total) * 100.0
        details = f"Clip {percent:.1f}% • Global {overall_percent:.1f}%"
        size_progress = self._format_download_size_progress(percent, size)
        if size_progress:
            details += f" • {size_progress}"
        if speed:
            details += f" • {speed}"
        if eta:
            details += f" • ETA {eta}"
        self.download_detail_var.set(details)
        self._set_download_phase("téléchargement des données")

    def _reset_download_ui(self) -> None:
        self.download_summary_var.set("Aucun téléchargement en cours.")
        self.download_detail_var.set("Aucun téléchargement pour le moment.")
        self._set_download_phase("en attente.")
        self.download_overall_progress.configure(value=0, maximum=100, mode="determinate")
        self.download_overall_progress.clear_segments()
        self.download_overall_progress.set_state("normal")
        self.download_current_progress.configure(value=0, maximum=100, mode="determinate")
        self.download_current_progress.set_state("normal")
        self.download_last_percent_logged = -1
        self.download_last_size = ""
        self.download_log.configure(state="normal")
        self.download_log.delete("1.0", tk.END)
        self.download_log.configure(state="disabled")
        for bar in self._moment_mini_bars.values():
            bar.configure(value=0, mode="determinate")
            bar.set_state("normal")
        self._current_download_card_index = None

    def generate(self) -> None:
        """Launch background transcript generation."""
        self._recover_stale_busy_state()
        if self.busy:
            self._set_status("Un traitement est déjà en cours…", busy=True)
            return

        if self.download_active:
            messagebox.showinfo(
                "Téléchargement en cours",
                "Merci d'attendre la fin du téléchargement avant de générer.",
            )
            return

        url = self._get_entry_value(self.url_entry)
        if not url:
            messagebox.showwarning("Champ manquant", "Colle un lien YouTube à transcrire.")
            return
        try:
            extract_video_id(url)
        except VideoIdExtractionError:
            message = (
                "La transcription fonctionne uniquement avec une vidéo YouTube.\n\n"
                "Pour ce lien, utilise « Télécharger vidéo » ou « Télécharger audio »."
            )
            messagebox.showerror("Transcription YouTube uniquement", message)
            self._append_output("Erreur: lien non compatible avec la transcription YouTube.")
            self._set_status("Choisis un lien YouTube pour transcrire, ou télécharge le média.", busy=False, error=True)
            return

        languages = self._parse_languages(self._get_entry_value(self.languages_entry))
        output_format = self._selected_output_format()
        include_most_viewed = self.most_viewed_var.get()
        most_viewed_limit = self._get_most_viewed_limit()

        self.last_url = url
        self._set_status("Analyse de la vidéo en cours…", busy=True)
        self.output_text.delete("1.0", tk.END)
        self._render_most_viewed_cards([])
        self.last_most_viewed_moments = []
        self.last_transcript_chunks = []
        self._update_stats("")
        self.meta_var.set("")
        self.cancel_event.clear()
        self.current_job_id += 1
        job_id = self.current_job_id

        thread = threading.Thread(
            target=self._run_generation,
            args=(
                job_id,
                url,
                languages,
                output_format,
                include_most_viewed,
                most_viewed_limit,
            ),
            daemon=True,
        )
        self.generation_thread = thread
        thread.start()

    def _run_generation(
        self,
        job_id: int,
        url: str,
        languages: Optional[List[str]],
        output_format: str,
        include_most_viewed: bool,
        most_viewed_limit: int,
    ) -> None:
        try:
            result = generate_transcript_with_format(
                url,
                languages=languages,
                output_format=output_format,
                include_most_viewed_moments=include_most_viewed,
                most_viewed_limit=most_viewed_limit,
            )
        except (VideoIdExtractionError, TranscriptRetrievalError) as error:
            if self._should_ignore_result(job_id):
                return
            self.master.after(0, self._handle_error, str(error))
            return
        except Exception as error:
            if self._should_ignore_result(job_id):
                return
            LOGGER.exception("Unhandled generation error in GUI thread")
            self.master.after(0, self._handle_error, f"Erreur inattendue: {error}")
            return
        finally:
            self.generation_thread = None

        if self._should_ignore_result(job_id):
            return
        self.master.after(
            0,
            self._display_result,
            result.lines,
            result.raw_transcript,
            result.used_language,
            output_format,
            result.most_viewed_moments,
        )

    def _handle_error(self, message: str) -> None:
        LOGGER.warning("GUI error: %s", message)
        self._set_status("Erreur lors de la récupération.", busy=False, error=True)
        self._append_output(f"Erreur: {message}")
        messagebox.showerror("Impossible de récupérer le script", message)

    def _display_result(
        self,
        lines: List[str],
        transcript_chunks: List[dict] | None,
        used_language: str | None,
        output_format: str,
        most_viewed_moments,
    ) -> None:
        self.last_transcript_chunks = list(transcript_chunks or [])
        self.output_text.insert(tk.END, "\n".join(lines))
        if output_format != "json":
            self._apply_transcript_tags(lines)
        self.output_text.tag_add("sel", "1.0", tk.END)
        self.output_text.focus_set()
        format_label = self.output_format_lookup.get(output_format, output_format)
        meta_parts = [f"Format: {format_label}"]
        if used_language:
            meta_parts.append(f"Langue utilisée: {used_language}")
        self.meta_var.set(" | ".join(meta_parts))
        self._set_status("Transcription récupérée.", busy=False)
        self._update_stats("\n".join(lines))
        if most_viewed_moments is not None:
            self.last_most_viewed_moments = most_viewed_moments
            self._render_most_viewed_cards(most_viewed_moments)

    def save_transcript(self) -> None:
        """Save current transcript to a file."""
        content = self.output_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Aucune donnée", "Génère d'abord un script.")
            return

        output_format = self._selected_output_format()
        if output_format == "json":
            defext = ".json"
            types = [("Fichier JSON", "*.json"), ("Tous les fichiers", "*.*")]
        else:
            defext = ".txt"
            types = [("Fichier texte", "*.txt"), ("Tous les fichiers", "*.*")]

        file_path = filedialog.asksaveasfilename(
            defaultextension=defext,
            filetypes=types,
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(content)
        except OSError as error:
            messagebox.showerror("Enregistrement impossible", str(error))
        else:
            self._set_status(f"Script enregistré dans {file_path}.", busy=False)

    def _copy_youtube_chapters(self) -> None:
        if not self.last_most_viewed_moments:
            messagebox.showinfo(
                "Aucun moment détecté",
                "Transcris une vidéo d'abord pour détecter les moments forts.",
            )
            return
        lines = ["0:00 Introduction"]
        for moment in self.last_most_viewed_moments:
            ts = seconds_to_timestamp(moment.minute_index * 60)
            excerpt = moment.excerpt[:60].strip().rstrip("…").rstrip(".")
            lines.append(f"{ts} {excerpt}")
        self.master.clipboard_clear()
        self.master.clipboard_append("\n".join(lines))
        self._set_status("Chapitres YouTube copiés ✓", busy=False, success=True)

    def export_moments(self) -> None:
        if not self.last_most_viewed_moments:
            messagebox.showinfo(
                "Aucune donnée",
                "Génère d'abord les moments forts estimés pour exporter.",
            )
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[
                ("Fichier CSV", "*.csv"),
                ("Fichier texte", "*.txt"),
                ("Fichier JSON", "*.json"),
                ("Tous les fichiers", "*.*"),
            ],
            initialfile="moments_forts_estimes",
        )
        if not file_path:
            return
        try:
            extension = Path(file_path).suffix.lower()
            if extension == ".json":
                payload = {
                    "moments": [moment.to_dict() for moment in self.last_most_viewed_moments],
                    "source_url": self.last_url,
                }
                with open(file_path, "w", encoding="utf-8") as file:
                    json.dump(payload, file, ensure_ascii=False, indent=2)
            elif extension == ".txt":
                lines = format_most_viewed_moments(
                    self.last_most_viewed_moments, include_header=True
                )
                with open(file_path, "w", encoding="utf-8") as file:
                    file.write("\n".join(lines))
            else:
                export_most_viewed_csv(file_path, self.last_most_viewed_moments)
        except OSError as error:
            messagebox.showerror("Export impossible", str(error))
        else:
            self._set_status("Moments exportés.", busy=False)

    def download_clips(self) -> None:
        if not self.last_most_viewed_moments:
            messagebox.showinfo(
                "Aucune donnée",
                "Génère d'abord les moments forts estimés pour télécharger les extraits.",
            )
            return
        url = self.last_url or self._get_entry_value(self.url_entry)
        if not url:
            messagebox.showinfo("Aucune URL", "Ajoute une URL pour télécharger.")
            return
        yt_dlp_cmd = self._resolve_yt_dlp_cmd()
        if yt_dlp_cmd is None:
            messagebox.showerror(
                "Dépendance manquante",
                "Le binaire 'yt-dlp' est requis pour télécharger les extraits.\n"
                "macOS: brew install yt-dlp\n"
                "Windows: winget install yt-dlp.yt-dlp\n"
                "Linux: sudo apt install yt-dlp",
            )
            return
        if self._resolve_system_tool("ffmpeg") is None:
            messagebox.showerror(
                "Dépendance manquante",
                "Le binaire 'ffmpeg' est requis pour découper les extraits.\n"
                "macOS: brew install ffmpeg\n"
                "Windows: winget install Gyan.FFmpeg\n"
                "Linux: sudo apt install ffmpeg",
            )
            return

        output_dir = self._pick_download_dir()
        if not output_dir:
            return

        duration = self._get_clip_duration()
        video_format = self._get_video_format()
        shorts_mode = self._selected_download_aspect_mode() == "shorts"
        logo_options = self._selected_download_logo_options()
        if logo_options is None:
            return
        lower_third_config = self._selected_download_lower_third_config()
        if self._download_lower_third_enabled() and lower_third_config is None:
            return
        value_add_options = self._selected_value_add_options()
        if value_add_options is None:
            return
        lower_third_interval = self._get_download_lower_third_interval()
        lower_third_display_duration = (
            self._get_download_lower_third_display_duration()
        )
        subtitles_enabled = (
            bool(self.download_subtitles_enabled_var.get())
            and bool(self.last_transcript_chunks)
            and url == self.last_url
        )
        subtitle_style = self._selected_download_subtitle_style()
        video_effect = self._selected_download_video_effect()
        self._enqueue_downloads(
            self.last_most_viewed_moments,
            url,
            output_dir,
            duration,
            video_format,
            yt_dlp_cmd,
            shorts_mode=shorts_mode,
            **logo_options,
            **value_add_options,
            lower_third_config=lower_third_config,
            lower_third_interval=lower_third_interval,
            lower_third_display_duration=lower_third_display_duration,
            subtitles_enabled=subtitles_enabled,
            subtitle_style=subtitle_style,
            video_effect=video_effect,
        )

    def download_single_clip(self, moment) -> None:
        url = self.last_url or self._get_entry_value(self.url_entry)
        if not url:
            messagebox.showinfo("Aucune URL", "Ajoute une URL pour télécharger.")
            return
        yt_dlp_cmd = self._resolve_yt_dlp_cmd()
        if yt_dlp_cmd is None:
            messagebox.showerror(
                "Dépendance manquante",
                "Le binaire 'yt-dlp' est requis pour télécharger les extraits.\n"
                "macOS: brew install yt-dlp\n"
                "Windows: winget install yt-dlp.yt-dlp\n"
                "Linux: sudo apt install yt-dlp",
            )
            return
        if self._resolve_system_tool("ffmpeg") is None:
            messagebox.showerror(
                "Dépendance manquante",
                "Le binaire 'ffmpeg' est requis pour découper les extraits.\n"
                "macOS: brew install ffmpeg\n"
                "Windows: winget install Gyan.FFmpeg\n"
                "Linux: sudo apt install ffmpeg",
            )
            return

        output_dir = self._pick_download_dir()
        if not output_dir:
            return

        duration = self._get_clip_duration()
        video_format = self._get_video_format()
        shorts_mode = self._selected_download_aspect_mode() == "shorts"
        logo_options = self._selected_download_logo_options()
        if logo_options is None:
            return
        lower_third_config = self._selected_download_lower_third_config()
        if self._download_lower_third_enabled() and lower_third_config is None:
            return
        value_add_options = self._selected_value_add_options()
        if value_add_options is None:
            return
        lower_third_interval = self._get_download_lower_third_interval()
        lower_third_display_duration = (
            self._get_download_lower_third_display_duration()
        )
        subtitles_enabled = (
            bool(self.download_subtitles_enabled_var.get())
            and bool(self.last_transcript_chunks)
            and url == self.last_url
        )
        subtitle_style = self._selected_download_subtitle_style()
        video_effect = self._selected_download_video_effect()
        self._enqueue_downloads(
            [moment],
            url,
            output_dir,
            duration,
            video_format,
            yt_dlp_cmd,
            shorts_mode=shorts_mode,
            **logo_options,
            **value_add_options,
            lower_third_config=lower_third_config,
            lower_third_interval=lower_third_interval,
            lower_third_display_duration=lower_third_display_duration,
            subtitles_enabled=subtitles_enabled,
            subtitle_style=subtitle_style,
            video_effect=video_effect,
        )

    def preview_single_clip(self, moment) -> None:
        self._recover_stale_busy_state()
        if self.busy:
            self._set_status("Un traitement est déjà en cours…", busy=True)
            return
        if self.download_active:
            messagebox.showinfo(
                "Téléchargement en cours",
                "Merci d'attendre la fin du téléchargement avant de prévisualiser.",
            )
            return

        url = self.last_url or self._get_entry_value(self.url_entry)
        if not url:
            messagebox.showinfo("Aucune URL", "Ajoute une URL pour prévisualiser.")
            return

        yt_dlp_cmd = self._resolve_yt_dlp_cmd()
        if yt_dlp_cmd is None:
            messagebox.showerror(
                "Dépendance manquante",
                "Le binaire 'yt-dlp' est requis pour prévisualiser un extrait.\n"
                "macOS: brew install yt-dlp\n"
                "Windows: winget install yt-dlp.yt-dlp\n"
                "Linux: sudo apt install yt-dlp",
            )
            return
        if self._resolve_system_tool("ffmpeg") is None:
            messagebox.showerror(
                "Dépendance manquante",
                "Le binaire 'ffmpeg' est requis pour générer la prévisualisation.\n"
                "macOS: brew install ffmpeg\n"
                "Windows: winget install Gyan.FFmpeg\n"
                "Linux: sudo apt install ffmpeg",
            )
            return

        logo_options = self._selected_download_logo_options()
        if logo_options is None:
            return
        lower_third_config = self._selected_download_lower_third_config()
        if self._download_lower_third_enabled() and lower_third_config is None:
            return
        value_add_options = self._selected_value_add_options()
        if value_add_options is None:
            return

        start = int(moment.minute_index * 60)
        duration = min(8, self._get_clip_duration())
        output_dir = tempfile.mkdtemp(prefix="youtube-script-preview-")
        subtitles_enabled = (
            bool(self.download_subtitles_enabled_var.get())
            and bool(self.last_transcript_chunks)
            and url == self.last_url
        )
        item = {
            "url": url,
            "output_dir": output_dir,
            "start": start,
            "duration": duration,
            "format": self._get_video_format(),
            "yt_dlp_cmd": yt_dlp_cmd,
            "shorts": self._selected_download_aspect_mode() == "shorts",
            **logo_options,
            **value_add_options,
            "lower_third_config": lower_third_config,
            "lower_third_interval": self._get_download_lower_third_interval(),
            "lower_third_display_duration": (
                self._get_download_lower_third_display_duration()
            ),
            "subtitles_enabled": subtitles_enabled,
            "subtitle_style": self._selected_download_subtitle_style(),
            "subtitle_offset_ms": self._get_subtitle_offset_ms(),
            "subtitle_chunks": copy.deepcopy(self.last_transcript_chunks)
            if subtitles_enabled
            else [],
            "video_effect": self._selected_download_video_effect(),
            "clip_label": self._build_moment_filename_label(moment),
        }

        self.cancel_event.clear()
        self.current_job_id += 1
        job_id = self.current_job_id
        self._set_status("Génération de l'aperçu…", busy=True)
        self._set_download_phase("prévisualisation en cours")
        self.download_detail_var.set("Création d'un aperçu temporaire…")
        self._append_download_log(
            f"Prévisualisation temporaire: {seconds_to_timestamp(start)} → "
            f"{seconds_to_timestamp(start + duration)}"
        )
        thread = threading.Thread(
            target=self._preview_worker,
            args=(job_id, item),
            daemon=True,
        )
        self.preview_thread = thread
        thread.start()

    def _preview_worker(self, job_id: int, item: dict) -> None:
        try:
            final_path = self._render_preview_clip(item)
        except RuntimeError as error:
            if self._should_ignore_result(job_id):
                return
            self.master.after(0, self._finish_preview_ui, False, str(error), None)
            return
        finally:
            self.preview_thread = None

        if self._should_ignore_result(job_id):
            return
        self.master.after(0, self._finish_preview_ui, True, "", final_path)

    @staticmethod
    def _logo_ratio_options_from_item(item: dict) -> dict:
        scale_percent = item.get(
            "logo_scale_percent",
            download_utils.DEFAULT_LOGO_SCALE_PERCENT,
        )
        width_source = item.get("logo_width_ratio")
        logo_width_ratio = (
            download_utils.normalize_logo_width_ratio(width_source)
            if width_source is not None
            else download_utils.logo_scale_percent_to_width_ratio(scale_percent)
        )
        x_source = item.get("logo_x_ratio")
        y_source = item.get("logo_y_ratio")
        if x_source is None or y_source is None:
            logo_x_ratio, logo_y_ratio = download_utils.logo_position_to_ratios(
                item.get("logo_position", download_utils.DEFAULT_LOGO_POSITION),
                logo_width_ratio,
            )
        else:
            logo_x_ratio = download_utils.normalize_logo_x_ratio(
                x_source,
                logo_width_ratio,
            )
            logo_y_ratio = download_utils.normalize_logo_y_ratio(y_source)
        options = {
            "logo_width_ratio": logo_width_ratio,
            "logo_x_ratio": logo_x_ratio,
            "logo_y_ratio": logo_y_ratio,
        }
        if item.get("logo_original_width") is not None:
            options["logo_original_width"] = item.get("logo_original_width")
        if item.get("logo_original_height") is not None:
            options["logo_original_height"] = item.get("logo_original_height")
        return options

    def _render_preview_clip(self, item: dict) -> Path:
        start = int(item["start"])
        duration = int(item["duration"])
        end = start + duration
        start_ts = seconds_to_timestamp(start)
        end_ts = seconds_to_timestamp(end)
        video_format = str(item.get("format", "mp4"))
        output_dir = Path(str(item.get("output_dir", "")))
        output_dir.mkdir(parents=True, exist_ok=True)
        existing_files = {
            str(path.resolve())
            for path in output_dir.glob("*")
            if path.is_file()
        }
        reported_output_path = ""
        output_template = "preview_%(title).60s.%(ext)s"
        cmd = [
            *item["yt_dlp_cmd"],
            "--no-playlist",
            "--download-sections",
            f"*{start_ts}-{end_ts}",
            *download_utils.build_best_video_download_args(video_format),
            "--paths",
            str(output_dir),
            "-o",
            output_template,
            item["url"],
        ]

        self.master.after(0, self._set_download_phase, "téléchargement de l'aperçu")
        try:
            self.download_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            assert self.download_process.stderr is not None
            for line in self.download_process.stderr:
                clean = line.strip()
                if clean:
                    self.master.after(0, self._append_download_log, clean)
                dest_match = DOWNLOAD_DEST_RE.search(clean)
                merger_match = DOWNLOAD_MERGER_RE.search(clean)
                already_match = DOWNLOAD_ALREADY_RE.search(clean)
                if dest_match:
                    reported_output_path = dest_match.group(1).strip()
                elif merger_match:
                    reported_output_path = merger_match.group(1).strip()
                elif already_match:
                    reported_output_path = already_match.group(1).strip()
            code = self.download_process.wait()
        except OSError as error:
            raise RuntimeError(str(error)) from error
        finally:
            self.download_process = None

        if self.cancel_event.is_set():
            raise RuntimeError("Prévisualisation annulée.")
        if code != 0:
            raise RuntimeError("La prévisualisation a échoué.")

        downloaded_path = self._resolve_downloaded_path(
            output_dir=output_dir,
            video_format=video_format,
            existing_files=existing_files,
            reported_output_path=reported_output_path,
        )
        if not downloaded_path:
            raise RuntimeError("Impossible de retrouver le fichier de prévisualisation.")

        self.master.after(0, self._set_download_phase, "application des effets")
        variant_kwargs = {
            "to_shorts": bool(item.get("shorts")),
            "logo_path": item.get("logo_path", "")
            if item.get("logo_enabled")
            else "",
            "logo_position": str(
                item.get("logo_position", download_utils.DEFAULT_LOGO_POSITION)
            ),
            "logo_size_mode": str(item.get("logo_size_mode", "relative")),
            "logo_scale_percent": int(
                item.get(
                    "logo_scale_percent",
                    download_utils.DEFAULT_LOGO_SCALE_PERCENT,
                )
            ),
            "logo_opacity_percent": int(item.get("logo_opacity_percent", 100)),
            "logo_display_duration": item.get("logo_display_duration") or None,
            "shorts_blur_bg": bool(item.get("shorts_blur_bg", True)),
            "lower_third_config": item.get("lower_third_config"),
            "clip_duration": float(item.get("duration", 0) or 0),
            "intro_outro_enabled": bool(item.get("intro_outro_enabled", False)),
            "intro_outro_channel_name": str(
                item.get("intro_outro_channel_name", "")
            ),
            "intro_outro_hold_duration": float(item.get("intro_outro_hold_duration", 1.5) or 1.5),
            "intro_outro_bg_color": str(item.get("intro_outro_bg_color", "0x000000@0.75") or "0x000000@0.75"),
            "intro_outro_text_color": str(item.get("intro_outro_text_color", "#FFFFFF") or "#FFFFFF"),
            "progress_bar_enabled": bool(item.get("progress_bar_enabled", False)),
            "animated_watermark_enabled": bool(
                item.get("animated_watermark_enabled", False)
            ),
            "watermark_logo_path": str(item.get("watermark_logo_path", "")),
            "lower_third_interval": int(
                item.get(
                    "lower_third_interval",
                    lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS,
                )
            ),
            "lower_third_display_duration": int(
                item.get(
                    "lower_third_display_duration",
                    lower_third.DEFAULT_DISPLAY_DURATION_SECONDS,
                )
            ),
            **self._logo_ratio_options_from_item(item),
        }
        if item.get("subtitles_enabled"):
            variant_kwargs.update(
                {
                    "subtitle_chunks": item.get("subtitle_chunks", []),
                    "subtitle_start": float(item.get("start", 0) or 0),
                    "subtitle_duration": float(item.get("duration", 0) or 0),
                    "subtitle_offset_ms": int(item.get("subtitle_offset_ms", 0) or 0),
                    "subtitle_style": str(item.get("subtitle_style", "impact")),
                }
            )
        video_effect = str(item.get("video_effect", "none"))
        if video_effect != "none":
            variant_kwargs["video_effect"] = video_effect
        variant_kwargs["preview_width"] = 1080
        return self._build_download_variant(downloaded_path, **variant_kwargs)

    def _finish_preview_ui(
        self,
        success: bool,
        message: str,
        final_path: Path | None,
    ) -> None:
        if not success:
            self._set_status("Erreur lors de la prévisualisation.", busy=False, error=True)
            self._set_download_phase("prévisualisation échouée")
            if message and message != "Prévisualisation annulée.":
                messagebox.showerror("Prévisualisation impossible", message)
            return
        if final_path is None:
            self._set_status("Aucun aperçu généré.", busy=False, error=True)
            return
        self.last_downloaded_file = str(final_path)
        self.download_detail_var.set(f"Aperçu: {final_path.name}")
        self._set_download_phase("aperçu prêt")
        self._append_download_log(f"Aperçu généré: {final_path}")
        self._set_status("Aperçu prêt ✓", busy=False, success=True)
        webbrowser.open(final_path.resolve().as_uri())

    def download_full_video(self) -> None:
        self._download_full_media(audio_only=False)

    def download_audio_only(self) -> None:
        self._download_full_media(audio_only=True)

    def _download_full_media(self, *, audio_only: bool) -> None:
        url_entry = getattr(self, "url_entry", None)
        current_url = self._get_entry_value(url_entry) if url_entry is not None else ""
        url = current_url or self.last_url
        if not url:
            messagebox.showinfo("Aucune URL", "Ajoute un lien à télécharger.")
            return

        yt_dlp_cmd = self._resolve_yt_dlp_cmd()
        if yt_dlp_cmd is None:
            messagebox.showerror(
                "Dépendance manquante",
                "Le binaire 'yt-dlp' est requis pour télécharger une vidéo ou un audio depuis un lien.\n"
                "macOS: brew install yt-dlp\n"
                "Windows: winget install yt-dlp.yt-dlp\n"
                "Linux: sudo apt install yt-dlp",
            )
            return

        if audio_only and self._resolve_system_tool("ffmpeg") is None:
            messagebox.showerror(
                "Dépendance manquante",
                "Le binaire 'ffmpeg' est requis pour exporter en MP3.\n"
                "macOS: brew install ffmpeg\n"
                "Windows: winget install Gyan.FFmpeg\n"
                "Linux: sudo apt install ffmpeg",
            )
            return

        logo_options = {
            "logo_enabled": False,
            "logo_path": "",
            "logo_position": download_utils.DEFAULT_LOGO_POSITION,
            "logo_size_mode": "relative",
            "logo_scale_percent": download_utils.DEFAULT_LOGO_SCALE_PERCENT,
            "logo_opacity_percent": 100,
            "logo_width_ratio": download_utils.DEFAULT_LOGO_WIDTH_RATIO,
            "logo_x_ratio": download_utils.DEFAULT_LOGO_X_RATIO,
            "logo_y_ratio": download_utils.DEFAULT_LOGO_Y_RATIO,
            "logo_original_width": None,
            "logo_original_height": None,
        }
        creative_options = {
            "subtitles_enabled": False,
            "subtitle_style": "impact",
            "video_effect": "none",
            "lower_third_config": None,
            "lower_third_interval": lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS,
            "lower_third_display_duration": lower_third.DEFAULT_DISPLAY_DURATION_SECONDS,
            "intro_outro_enabled": False,
            "intro_outro_channel_name": "",
            "progress_bar_enabled": False,
            "animated_watermark_enabled": False,
            "watermark_logo_path": "",
            "shorts_mode": False,
        }
        if not audio_only:
            shorts_mode = (
                self._selected_download_aspect_mode() == "shorts"
                if hasattr(self, "download_aspect_ratio_var")
                and hasattr(self, "download_aspect_ratio_lookup")
                else False
            )
            logo_options = self._selected_full_video_logo_options()
            if logo_options is None:
                return
            lower_third_config = self._selected_download_lower_third_config()
            if (
                self._download_lower_third_enabled()
                and lower_third_config is None
            ):
                return
            value_add_options = self._selected_value_add_options()
            if value_add_options is None:
                return
            subtitle_enabled_var = getattr(self, "download_subtitles_enabled_var", None)
            subtitles_enabled = (
                bool(subtitle_enabled_var.get())
                if subtitle_enabled_var is not None
                and hasattr(subtitle_enabled_var, "get")
                else False
            )
            subtitle_style = (
                self._selected_download_subtitle_style()
                if hasattr(self, "download_subtitle_style_var")
                and hasattr(self, "download_subtitle_style_lookup")
                else "impact"
            )
            video_effect = (
                self._selected_download_video_effect()
                if hasattr(self, "download_video_effect_var")
                and hasattr(self, "download_video_effect_lookup")
                else "none"
            )
            creative_options = {
                "subtitles_enabled": (
                    subtitles_enabled
                    and bool(getattr(self, "last_transcript_chunks", []))
                    and url == self.last_url
                ),
                "subtitle_style": subtitle_style,
                "video_effect": video_effect,
                "lower_third_config": lower_third_config,
                "lower_third_interval": self._get_download_lower_third_interval(),
                "lower_third_display_duration": (
                    self._get_download_lower_third_display_duration()
                ),
                "shorts_mode": shorts_mode,
                **value_add_options,
            }
            needs_processing = (
                bool(shorts_mode)
                or bool(logo_options.get("logo_enabled") and logo_options.get("logo_path"))
                or bool(creative_options["subtitles_enabled"])
                or creative_options["lower_third_config"] is not None
                or bool(creative_options["intro_outro_enabled"])
                or bool(creative_options["progress_bar_enabled"])
                or bool(creative_options["animated_watermark_enabled"])
                or creative_options["video_effect"] != "none"
            )
            if needs_processing and self._resolve_system_tool("ffmpeg") is None:
                messagebox.showerror(
                    "Dépendance manquante",
                    "Le binaire 'ffmpeg' est requis pour convertir le format, intégrer un logo, "
                    "un lower third, des sous-titres ou un effet vidéo.\n"
                    "macOS: brew install ffmpeg\n"
                    "Windows: winget install Gyan.FFmpeg\n"
                    "Linux: sudo apt install ffmpeg",
                )
                return

        output_dir = self._pick_download_dir()
        if not output_dir:
            return

        self._enqueue_media_download(
            url=url,
            output_dir=output_dir,
            video_format=self._get_video_format(),
            yt_dlp_cmd=yt_dlp_cmd,
            kind="audio" if audio_only else "full_video",
            **logo_options,
            **creative_options,
        )

    def _resolve_yt_dlp_cmd(self) -> List[str] | None:
        path = self._resolve_system_tool("yt-dlp")
        if path:
            cmd = [path]
        elif importlib.util.find_spec("yt_dlp") is not None:
            cmd = [sys.executable, "-m", "yt_dlp"]
        else:
            return None
        browser = self._selected_cookies_browser()
        if browser:
            # Avec cookies : laisser yt-dlp choisir le client (le cookie contient la session)
            cmd += ["--cookies-from-browser", browser]
        else:
            # Sans cookies : android_vr ne demande ni PO Token ni JS challenge
            cmd += ["--extractor-args", "youtube:player_client=android_vr"]
        return cmd

    def _selected_cookies_browser(self) -> str:
        label = getattr(self, "ytdlp_cookies_browser_var", None)
        if label is None:
            return ""
        return {
            "Chrome": "chrome",
            "Firefox": "firefox",
            "Safari": "safari",
            "Edge": "edge",
            "Brave": "brave",
        }.get(label.get(), "")

    @staticmethod
    def _prepend_to_path(directory: str) -> None:
        path_parts = [
            part
            for part in os.environ.get("PATH", "").split(os.pathsep)
            if part
        ]
        if directory in path_parts:
            return
        os.environ["PATH"] = os.pathsep.join([directory, *path_parts])

    @classmethod
    def _resolve_system_tool(cls, executable: str) -> str | None:
        path = shutil.which(executable)
        if path:
            return path

        for directory in COMMON_TOOL_DIRS:
            candidate = Path(directory) / executable
            if candidate.is_file() and os.access(candidate, os.X_OK):
                cls._prepend_to_path(directory)
                return str(candidate)
        return None

    def _pick_download_dir(self) -> str:
        output_dir = filedialog.askdirectory(
            title="Choisir le dossier de destination",
            initialdir=self.last_download_dir or None,
        )
        if output_dir:
            self.last_download_dir = output_dir
        return output_dir

    def select_download_logo(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Choisir un logo",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.webp"),
                ("Tous les fichiers", "*.*"),
            ],
            initialdir=self.last_download_dir or None,
        )
        if not file_path:
            return
        self._set_entry_text(self.download_logo_entry, file_path)
        self._redraw_logo_preview()
        self._save_gui_settings()

    def _validated_download_logo_path(self) -> str | None:
        raw_path = self._get_entry_value(self.download_logo_entry)
        if not raw_path:
            return ""
        logo_path = Path(raw_path).expanduser()
        if not logo_path.exists() or not logo_path.is_file():
            messagebox.showerror(
                "Logo introuvable",
                f"Le fichier logo est introuvable:\n{logo_path}",
            )
            return None
        return str(logo_path)

    def _build_logo_config(self) -> LogoConfig | None:
        enabled_var = getattr(self, "download_logo_enabled_var", None)
        enabled = (
            bool(enabled_var.get())
            if enabled_var is not None and hasattr(enabled_var, "get")
            else False
        )
        if not enabled:
            return None

        logo_path = self._current_download_logo_path()
        if not logo_path:
            messagebox.showwarning(
                "Logo manquant",
                "Sélectionne un logo ou décoche « Intégrer le logo ».",
            )
            return None

        try:
            return LogoConfig.from_gui_state(
                {
                    "logo_path": logo_path,
                    "logo_position": self._selected_download_logo_position(),
                    "logo_size_mode": self._selected_download_logo_size_mode(),
                    "logo_size": self._get_download_logo_scale_percent(),
                    "logo_opacity": self._get_download_logo_opacity_percent(),
                    "download_logo_x_ratio": self._get_download_logo_x_ratio(),
                    "download_logo_y_ratio": self._get_download_logo_y_ratio(),
                }
            )
        except (FileNotFoundError, ValueError) as error:
            messagebox.showerror("Configuration logo invalide", str(error))
            return None

    def _logo_options_from_config(self, config: LogoConfig) -> dict:
        return {
            "logo_enabled": True,
            "logo_path": str(config.path),
            "logo_position": download_utils.normalize_logo_position(config.position),
            "logo_size_mode": config.size_mode,
            "logo_scale_percent": int(round(config.slider_value)),
            "logo_opacity_percent": int(round(config.opacity * 100)),
            "logo_display_duration": self._get_download_logo_duration(),
            "shorts_blur_bg": bool(getattr(self, "download_shorts_blur_var", None) and self.download_shorts_blur_var.get()),
            "logo_width_ratio": self._get_download_logo_width_ratio(),
            "logo_x_ratio": self._get_download_logo_x_ratio(),
            "logo_y_ratio": self._get_download_logo_y_ratio(),
            "logo_original_width": config.original_width,
            "logo_original_height": config.original_height,
        }

    def _selected_download_logo_options(self) -> dict | None:
        enabled_var = getattr(self, "download_logo_enabled_var", None)
        logo_enabled = (
            bool(enabled_var.get())
            if enabled_var is not None and hasattr(enabled_var, "get")
            else False
        )
        if logo_enabled:
            config = self._build_logo_config()
            return self._logo_options_from_config(config) if config is not None else None
        return {
            "logo_enabled": False,
            "logo_path": "",
            "logo_position": self._selected_download_logo_position(),
            "logo_size_mode": self._selected_download_logo_size_mode(),
            "logo_scale_percent": self._get_download_logo_scale_percent(),
            "logo_opacity_percent": self._get_download_logo_opacity_percent(),
            "logo_display_duration": self._get_download_logo_duration(),
            "shorts_blur_bg": bool(getattr(self, "download_shorts_blur_var", None) and self.download_shorts_blur_var.get()),
            "logo_width_ratio": self._get_download_logo_width_ratio(),
            "logo_x_ratio": self._get_download_logo_x_ratio(),
            "logo_y_ratio": self._get_download_logo_y_ratio(),
            "logo_original_width": None,
            "logo_original_height": None,
        }

    def _selected_full_video_logo_options(self) -> dict | None:
        logo_enabled_var = getattr(self, "download_logo_enabled_var", None)
        logo_enabled = (
            bool(logo_enabled_var.get())
            if logo_enabled_var is not None and hasattr(logo_enabled_var, "get")
            else False
        )
        if not logo_enabled:
            return {
                "logo_enabled": False,
                "logo_path": "",
                "logo_position": download_utils.DEFAULT_LOGO_POSITION,
                "logo_size_mode": "relative",
                "logo_scale_percent": download_utils.DEFAULT_LOGO_SCALE_PERCENT,
                "logo_opacity_percent": 100,
                "logo_width_ratio": download_utils.DEFAULT_LOGO_WIDTH_RATIO,
                "logo_x_ratio": download_utils.DEFAULT_LOGO_X_RATIO,
                "logo_y_ratio": download_utils.DEFAULT_LOGO_Y_RATIO,
                "logo_original_width": None,
                "logo_original_height": None,
            }

        logo_config = self._build_logo_config()
        if logo_config is None:
            return None
        if self._resolve_system_tool("ffmpeg") is None:
            messagebox.showerror(
                "Dépendance manquante",
                "Le binaire 'ffmpeg' est requis pour intégrer un logo à la vidéo.\n"
                "macOS: brew install ffmpeg\n"
                "Windows: winget install Gyan.FFmpeg\n"
                "Linux: sudo apt install ffmpeg",
            )
            return None

        return self._logo_options_from_config(logo_config)

    def _on_download_logo_toggle(self) -> None:
        self._update_download_logo_controls_state()

    def _update_download_logo_controls_state(self) -> None:
        enabled_var = getattr(self, "download_logo_enabled_var", None)
        if enabled_var is None:
            return
        enabled = enabled_var.get()
        needs_logo_path = enabled or self._animated_watermark_enabled()
        if getattr(self, "busy", False):
            state = "disabled"
        else:
            state = "normal" if needs_logo_path else "disabled"
        scale_state = "normal" if enabled and state != "disabled" else "disabled"
        fixed_logo_state = "normal" if enabled and state != "disabled" else "disabled"
        fixed_logo_combo_state = (
            "readonly" if fixed_logo_state != "disabled" else "disabled"
        )
        if (
            fixed_logo_state != "disabled"
            and self._selected_download_logo_size_mode() == "original"
        ):
            scale_state = "disabled"
        widgets = (
            ("download_logo_entry", state),
            ("download_logo_button", state),
            ("download_logo_position_combo", fixed_logo_combo_state),
            ("download_logo_size_mode_combo", fixed_logo_combo_state),
            ("download_logo_size_scale", scale_state),
            ("download_logo_opacity_scale", fixed_logo_state),
        )
        for name, widget_state in widgets:
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(state=widget_state)
        preview_canvas = getattr(self, "download_logo_preview_canvas", None)
        if preview_canvas is not None:
            preview_canvas.configure(cursor="hand2" if fixed_logo_state != "disabled" else "")
        self._redraw_logo_preview()

    def _on_logo_size_change(self, value: str) -> None:
        try:
            percent = int(round(float(value)))
        except (TypeError, ValueError):
            percent = self._get_download_logo_scale_percent()
        percent = max(20, min(80, percent))
        previous_width_ratio = self._get_download_logo_width_ratio()
        previous_x_ratio = self._get_download_logo_x_ratio()
        previous_y_ratio = self._get_download_logo_y_ratio()
        selected_position = (
            self._selected_download_logo_position()
            if hasattr(self, "download_logo_position_var")
            and hasattr(self, "download_logo_position_lookup")
            else download_utils.DEFAULT_LOGO_POSITION
        )
        self.download_logo_size_var.set(percent)
        self.download_logo_size_label_var.set(
            self._download_logo_size_label(percent, self._selected_download_logo_size_mode())
        )
        if hasattr(self, "download_logo_width_ratio_var"):
            new_width_ratio = download_utils.logo_scale_percent_to_width_ratio(percent)
            self.download_logo_width_ratio_var.set(new_width_ratio)
            if (
                hasattr(self, "download_logo_x_ratio_var")
                and hasattr(self, "download_logo_y_ratio_var")
                and download_utils.logo_ratios_match_position(
                    selected_position,
                    previous_width_ratio,
                    previous_x_ratio,
                    previous_y_ratio,
                )
            ):
                logo_x_ratio, logo_y_ratio = download_utils.logo_position_to_ratios(
                    selected_position,
                    new_width_ratio,
                )
                self.download_logo_x_ratio_var.set(logo_x_ratio)
                self.download_logo_y_ratio_var.set(logo_y_ratio)
        self._redraw_logo_preview()

    @staticmethod
    def _download_logo_size_label(percent: int, mode: str = "relative") -> str:
        if mode == "original":
            return "Original · max 30% vidéo"
        video_percent = video_renderer.logo_frame_width_percent(percent)
        return f"{percent}% · {video_percent}% vidéo"

    def _get_download_logo_scale_percent(self) -> int:
        try:
            value = int(round(float(self.download_logo_size_var.get())))
        except (AttributeError, TypeError, ValueError):
            return download_utils.DEFAULT_LOGO_SCALE_PERCENT
        return max(20, min(80, value))

    def _get_download_logo_width_ratio(self) -> float:
        value = (
            self.download_logo_width_ratio_var.get()
            if hasattr(self, "download_logo_width_ratio_var")
            else download_utils.logo_scale_percent_to_width_ratio(
                self._get_download_logo_scale_percent()
            )
        )
        return download_utils.normalize_logo_width_ratio(value)

    def _get_download_logo_x_ratio(self) -> float:
        value = (
            self.download_logo_x_ratio_var.get()
            if hasattr(self, "download_logo_x_ratio_var")
            else download_utils.DEFAULT_LOGO_X_RATIO
        )
        return download_utils.normalize_logo_x_ratio(
            value,
            self._get_download_logo_width_ratio(),
        )

    def _get_download_logo_y_ratio(self) -> float:
        value = (
            self.download_logo_y_ratio_var.get()
            if hasattr(self, "download_logo_y_ratio_var")
            else download_utils.DEFAULT_LOGO_Y_RATIO
        )
        return download_utils.normalize_logo_y_ratio(value)

    def _selected_download_logo_size_mode(self) -> str:
        var = getattr(self, "download_logo_size_mode_var", None)
        lookup = getattr(self, "download_logo_size_mode_lookup", {})
        label = var.get() if var is not None and hasattr(var, "get") else ""
        value = lookup.get(label, "relative")
        return value if value in {"relative", "original"} else "relative"

    def _on_logo_opacity_change(self, value: str) -> None:
        try:
            percent = int(round(float(value)))
        except (TypeError, ValueError):
            percent = self._get_download_logo_opacity_percent()
        percent = max(10, min(100, percent))
        self.download_logo_opacity_var.set(percent)
        self.download_logo_opacity_label_var.set(f"{percent}%")

    def _get_download_logo_opacity_percent(self) -> int:
        try:
            value = int(round(float(self.download_logo_opacity_var.get())))
        except (TypeError, ValueError):
            return 100
        return max(10, min(100, value))

    def _get_download_logo_duration(self) -> float | None:
        var = getattr(self, "download_logo_duration_var", None)
        try:
            value = int(var.get()) if var is not None else 0
        except (TypeError, ValueError, AttributeError):
            return None
        return float(value) if value > 0 else None

    def _get_subtitle_offset_ms(self) -> int:
        var = getattr(self, "download_subtitle_offset_var", None)
        try:
            return int(var.get()) if var is not None else 0
        except (TypeError, ValueError, AttributeError):
            return 0

    def _selected_download_logo_position(self) -> str:
        label = self.download_logo_position_var.get()
        return download_utils.normalize_logo_position(
            self.download_logo_position_lookup.get(
                label,
                download_utils.DEFAULT_LOGO_POSITION,
            )
        )

    def _logo_preview_canvas_size(self) -> tuple[int, int]:
        aspect_mode = (
            self._selected_download_aspect_mode()
            if hasattr(self, "download_aspect_ratio_var")
            and hasattr(self, "download_aspect_ratio_lookup")
            else "landscape"
        )
        if aspect_mode == "shorts":
            return 158, 280
        return 280, 158

    def _logo_preview_source_size(self) -> tuple[int, int] | None:
        logo_path = self._current_download_logo_path()
        if not logo_path:
            return None
        path = Path(logo_path).expanduser()
        if not path.exists() or not path.is_file():
            return None
        try:
            with Image.open(path) as image:
                return image.size
        except Exception:
            return None

    def _logo_preview_width_ratio(self, portrait_preview: bool) -> float:
        mode = self._selected_download_logo_size_mode()
        source_size = self._logo_preview_source_size()
        if mode == "original" and source_size is not None:
            target_width = 1080 if portrait_preview else 1920
            video_format = "9:16" if portrait_preview else "16:9"
            logo_width_px = video_renderer.compute_logo_width(
                mode,
                self._get_download_logo_scale_percent(),
                target_width,
                video_format,
                original_logo_width=source_size[0],
            )
            return max(0.01, min(0.30, logo_width_px / target_width))
        base_width_ratio = self._get_download_logo_width_ratio()
        return download_utils.effective_logo_width_ratio(
            base_width_ratio,
            portrait=portrait_preview,
        )

    def _logo_preview_bounds(self, width: int, height: int) -> tuple[int, int, int, int]:
        portrait_preview = height > width
        width_ratio = self._logo_preview_width_ratio(portrait_preview)
        base_width_ratio = self._get_download_logo_width_ratio()
        x_ratio = self._get_download_logo_x_ratio()
        y_ratio = self._get_download_logo_y_ratio()
        selected_position = (
            self._selected_download_logo_position()
            if hasattr(self, "download_logo_position_var")
            and hasattr(self, "download_logo_position_lookup")
            else download_utils.DEFAULT_LOGO_POSITION
        )
        source_size = self._logo_preview_source_size()
        aspect_ratio = (
            source_size[1] / source_size[0]
            if source_size is not None and source_size[0]
            else 0.36
        )
        logo_width = max(14, int(width * width_ratio))
        logo_height = max(12, int(logo_width * aspect_ratio))
        if download_utils.logo_ratios_match_position(
            selected_position,
            base_width_ratio,
            x_ratio,
            y_ratio,
        ):
            x, y = video_renderer.resolve_logo_position(
                selected_position,
                0.0,
                0.0,
                width,
                height,
                logo_width,
                logo_height,
            )
        else:
            x_ratio = download_utils.normalize_logo_x_ratio(x_ratio, width_ratio)
            y_ratio = download_utils.normalize_logo_y_ratio(y_ratio)
            x, y = video_renderer.resolve_logo_position(
                "custom",
                x_ratio,
                y_ratio,
                width,
                height,
                logo_width,
                logo_height,
            )
        return x, y, logo_width, logo_height

    def _redraw_logo_preview(self) -> None:
        canvas = getattr(self, "download_logo_preview_canvas", None)
        if canvas is None:
            return
        width, height = self._logo_preview_canvas_size()
        try:
            canvas.configure(width=width, height=height)
            canvas.delete("all")
        except tk.TclError:
            return

        enabled_var = getattr(self, "download_logo_enabled_var", None)
        enabled = (
            bool(enabled_var.get())
            if enabled_var is not None and hasattr(enabled_var, "get")
            else True
        )
        frame_fill = self.palette["bg_alt"]
        border = self.palette["shadow"]
        canvas.create_rectangle(
            1,
            1,
            width - 2,
            height - 2,
            fill=frame_fill,
            outline=border,
        )
        for fraction in (1 / 3, 2 / 3):
            x = int(width * fraction)
            y = int(height * fraction)
            canvas.create_line(x, 2, x, height - 2, fill=self.palette["canvas_grid"])
            canvas.create_line(2, y, width - 2, y, fill=self.palette["canvas_grid"])

        logo_path = self._current_download_logo_path()
        logo_x, logo_y, logo_width, logo_height = self._logo_preview_bounds(
            width,
            height,
        )
        if not logo_path or not Path(logo_path).expanduser().exists():
            canvas.create_text(
                width // 2,
                height // 2,
                text="Aucun logo chargé",
                fill=self.palette["muted"],
                font=(self.font_family, 9),
            )
            return

        try:
            image = Image.open(Path(logo_path).expanduser()).convert("RGBA")
            resized = image.resize(
                (max(1, logo_width), max(1, logo_height)),
                Image.Resampling.LANCZOS,
            )
            opacity = self._get_download_logo_opacity_percent() / 100.0
            if not enabled:
                opacity *= 0.35
            red, green, blue, alpha = resized.split()
            alpha = alpha.point(lambda value: int(value * opacity))
            resized.putalpha(alpha)
            self._logo_preview_tk = ImageTk.PhotoImage(resized)
            canvas.create_image(
                logo_x,
                logo_y,
                anchor="nw",
                image=self._logo_preview_tk,
                tags=("logo",),
            )
        except Image.DecompressionBombError:
            canvas.create_text(
                width // 2,
                height // 2,
                text="Logo trop grand pour l'aperçu",
                fill=self.palette["danger"],
                font=(self.font_family, 8),
            )
        except Exception as error:
            canvas.create_text(
                width // 2,
                height // 2,
                text=f"Erreur chargement logo : {error}",
                fill=self.palette["danger"],
                font=(self.font_family, 8),
            )

    def _draw_logo_preview(self) -> None:
        self._redraw_logo_preview()

    def _on_logo_preview_press(self, event: tk.Event) -> None:
        if not bool(self.download_logo_enabled_var.get()) or getattr(self, "busy", False):
            return
        width, height = self._logo_preview_canvas_size()
        logo_x, logo_y, logo_width, logo_height = self._logo_preview_bounds(
            width,
            height,
        )
        if logo_x <= event.x <= logo_x + logo_width and logo_y <= event.y <= logo_y + logo_height:
            self._logo_preview_drag_offset = (event.x - logo_x, event.y - logo_y)
        else:
            self._logo_preview_drag_offset = (logo_width // 2, logo_height // 2)
            self._on_logo_preview_drag(event)

    def _on_logo_preview_drag(self, event: tk.Event) -> None:
        if not bool(self.download_logo_enabled_var.get()) or getattr(self, "busy", False):
            return
        width, height = self._logo_preview_canvas_size()
        _logo_x, _logo_y, logo_width, logo_height = self._logo_preview_bounds(
            width,
            height,
        )
        offset_x, offset_y = getattr(
            self,
            "_logo_preview_drag_offset",
            (logo_width // 2, logo_height // 2),
        )
        x = max(0, min(width - logo_width, int(event.x - offset_x)))
        y = max(0, min(height - logo_height, int(event.y - offset_y)))
        self.download_logo_x_ratio_var.set(x / width)
        self.download_logo_y_ratio_var.set(y / height)
        self._redraw_logo_preview()

    def _selected_download_subtitle_style(self) -> str:
        label = self.download_subtitle_style_var.get()
        style = self.download_subtitle_style_lookup.get(label, "impact")
        return subtitle_renderer.normalize_subtitle_style(style)

    def _selected_download_video_effect(self) -> str:
        label = self.download_video_effect_var.get()
        effect = self.download_video_effect_lookup.get(label, "none")
        return subtitle_renderer.normalize_video_effect(effect)

    def _selected_download_preset(self) -> str:
        label = self.download_preset_var.get()
        key = self.download_preset_lookup.get(label, "custom")
        return video_presets.normalize_preset_key(key)

    def _selected_download_aspect_mode(self) -> str:
        label = self.download_aspect_ratio_var.get()
        mode = self.download_aspect_ratio_lookup.get(label, "landscape")
        return mode if mode in {"landscape", "shorts"} else "landscape"

    def _get_video_format(self) -> str:
        value = (self.video_format_var.get() or "mp4").strip().lower()
        return value if value in {"mp4", "webm"} else "mp4"

    def _enqueue_downloads(
        self,
        moments: List,
        url: str,
        output_dir: str,
        duration: int,
        video_format: str,
        yt_dlp_cmd: List[str],
        *,
        shorts_mode: bool,
        logo_enabled: bool,
        logo_path: str,
        logo_position: str,
        logo_size_mode: str,
        logo_scale_percent: int,
        logo_opacity_percent: int,
        logo_width_ratio: float = download_utils.DEFAULT_LOGO_WIDTH_RATIO,
        logo_x_ratio: float = download_utils.DEFAULT_LOGO_X_RATIO,
        logo_y_ratio: float = download_utils.DEFAULT_LOGO_Y_RATIO,
        logo_original_width: int | None = None,
        logo_original_height: int | None = None,
        logo_display_duration: float | None = None,
        shorts_blur_bg: bool = True,
        lower_third_config: lower_third.LowerThirdConfig | None = None,
        lower_third_interval: int = lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS,
        lower_third_display_duration: int = lower_third.DEFAULT_DISPLAY_DURATION_SECONDS,
        intro_outro_enabled: bool = False,
        intro_outro_channel_name: str = "",
        intro_outro_hold_duration: float = 1.5,
        intro_outro_bg_color: str = "0x000000@0.75",
        intro_outro_text_color: str = "#FFFFFF",
        progress_bar_enabled: bool = False,
        animated_watermark_enabled: bool = False,
        watermark_logo_path: str = "",
        subtitles_enabled: bool = False,
        subtitle_style: str = "impact",
        subtitle_offset_ms: int = 0,
        video_effect: str = "none",
    ) -> None:
        subtitles_allowed = subtitles_enabled and url == getattr(self, "last_url", "")
        transcript_chunks = (
            copy.deepcopy(getattr(self, "last_transcript_chunks", []))
            if subtitles_allowed
            else []
        )
        for moment in moments:
            start = moment.minute_index * 60
            clip_label = self._build_moment_filename_label(moment)
            title_cache = getattr(self, "video_title_cache", {})
            cached_title = ""
            if isinstance(title_cache, dict):
                cached_title = str(title_cache.get(url, "")).strip()
            self.download_queue.append(
                {
                    "url": url,
                    "output_dir": output_dir,
                    "start": start,
                    "duration": duration,
                    "format": video_format,
                    "yt_dlp_cmd": yt_dlp_cmd,
                    "shorts": shorts_mode,
                    "logo_enabled": logo_enabled,
                    "logo_path": logo_path,
                    "logo_position": logo_position,
                    "logo_size_mode": logo_size_mode,
                    "logo_scale_percent": logo_scale_percent,
                    "logo_opacity_percent": logo_opacity_percent,
                    "logo_width_ratio": logo_width_ratio,
                    "logo_x_ratio": logo_x_ratio,
                    "logo_y_ratio": logo_y_ratio,
                    "logo_original_width": logo_original_width,
                    "logo_original_height": logo_original_height,
                    "logo_display_duration": logo_display_duration,
                    "shorts_blur_bg": shorts_blur_bg,
                    "lower_third_config": copy.deepcopy(lower_third_config),
                    "lower_third_interval": lower_third_interval,
                    "lower_third_display_duration": lower_third_display_duration,
                    "intro_outro_enabled": intro_outro_enabled,
                    "intro_outro_channel_name": intro_outro_channel_name,
                    "intro_outro_hold_duration": intro_outro_hold_duration if hasattr(self, "download_intro_outro_hold_var") else 1.5,
                    "intro_outro_bg_color": intro_outro_bg_color if hasattr(self, "download_intro_outro_bg_color_var") else "0x000000@0.75",
                    "intro_outro_text_color": intro_outro_text_color if hasattr(self, "download_intro_outro_text_color_var") else "#FFFFFF",
                    "progress_bar_enabled": progress_bar_enabled,
                    "animated_watermark_enabled": animated_watermark_enabled,
                    "watermark_logo_path": watermark_logo_path,
                    "subtitles_enabled": bool(transcript_chunks),
                    "subtitle_style": subtitle_style,
                    "subtitle_offset_ms": subtitle_offset_ms,
                    "subtitle_chunks": transcript_chunks,
                    "video_effect": video_effect,
                    "clip_label": clip_label,
                    "video_title": cached_title,
                    "card_index": next(
                        (
                            i for i, m in enumerate(getattr(self, "last_most_viewed_moments", []))
                            if m is moment or m.minute_index == moment.minute_index
                        ),
                        None,
                    ),
                }
            )

        if self.download_active:
            # Include current clip already in progress when extending the queue.
            self.download_total = self.download_completed + len(self.download_queue) + 1
            self.download_overall_progress.set_segments(
                self.download_completed, self.download_total, 0.0
            )
            self.master.after(
                0,
                self._append_download_log,
                f"Ajout de {len(moments)} extrait(s) à la file d'attente.",
            )
            return

        self.download_completed = 0
        self.download_total = len(self.download_queue)
        self._start_download_ui(self.download_total)
        if not self.download_active:
            self.download_active = True
            self.download_cancel.clear()
            thread = threading.Thread(target=self._download_worker, daemon=True)
            self.download_thread = thread
            thread.start()

    def _enqueue_media_download(
        self,
        *,
        url: str,
        output_dir: str,
        video_format: str,
        yt_dlp_cmd: List[str],
        kind: str,
        logo_enabled: bool = False,
        logo_path: str = "",
        logo_position: str = download_utils.DEFAULT_LOGO_POSITION,
        logo_size_mode: str = "relative",
        logo_scale_percent: int = download_utils.DEFAULT_LOGO_SCALE_PERCENT,
        logo_opacity_percent: int = 100,
        logo_width_ratio: float = download_utils.DEFAULT_LOGO_WIDTH_RATIO,
        logo_x_ratio: float = download_utils.DEFAULT_LOGO_X_RATIO,
        logo_y_ratio: float = download_utils.DEFAULT_LOGO_Y_RATIO,
        logo_original_width: int | None = None,
        logo_original_height: int | None = None,
        logo_display_duration: float | None = None,
        shorts_blur_bg: bool = True,
        lower_third_config: lower_third.LowerThirdConfig | None = None,
        lower_third_interval: int = lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS,
        lower_third_display_duration: int = lower_third.DEFAULT_DISPLAY_DURATION_SECONDS,
        intro_outro_enabled: bool = False,
        intro_outro_channel_name: str = "",
        intro_outro_hold_duration: float = 1.5,
        intro_outro_bg_color: str = "0x000000@0.75",
        intro_outro_text_color: str = "#FFFFFF",
        progress_bar_enabled: bool = False,
        animated_watermark_enabled: bool = False,
        watermark_logo_path: str = "",
        subtitles_enabled: bool = False,
        subtitle_style: str = "impact",
        video_effect: str = "none",
        shorts_mode: bool = False,
    ) -> None:
        normalized_kind = kind if kind in {"full_video", "audio"} else "full_video"
        item_format = "mp3" if normalized_kind == "audio" else video_format
        media_shorts_mode = normalized_kind == "full_video" and bool(shorts_mode)
        media_logo_enabled = normalized_kind == "full_video" and logo_enabled and bool(logo_path)
        media_lower_third_config = (
            copy.deepcopy(lower_third_config)
            if normalized_kind == "full_video"
            else None
        )
        media_intro_outro_enabled = (
            normalized_kind == "full_video" and bool(intro_outro_enabled)
        )
        media_progress_bar_enabled = (
            normalized_kind == "full_video" and bool(progress_bar_enabled)
        )
        media_animated_watermark_enabled = (
            normalized_kind == "full_video" and bool(animated_watermark_enabled)
        )
        media_subtitles_enabled = (
            normalized_kind == "full_video"
            and subtitles_enabled
            and bool(getattr(self, "last_transcript_chunks", []))
            and url == getattr(self, "last_url", "")
        )
        title_cache = getattr(self, "video_title_cache", {})
        cached_title = ""
        if isinstance(title_cache, dict):
            cached_title = str(title_cache.get(url, "")).strip()

        self.download_queue.append(
            {
                "kind": normalized_kind,
                "url": url,
                "output_dir": output_dir,
                "start": 0,
                "duration": 0,
                "format": item_format,
                "yt_dlp_cmd": yt_dlp_cmd,
                "shorts": media_shorts_mode,
                "logo_enabled": media_logo_enabled,
                "logo_path": logo_path if media_logo_enabled else "",
                "logo_position": logo_position,
                "logo_size_mode": logo_size_mode,
                "logo_scale_percent": logo_scale_percent,
                "logo_opacity_percent": logo_opacity_percent,
                "logo_width_ratio": logo_width_ratio,
                "logo_x_ratio": logo_x_ratio,
                "logo_y_ratio": logo_y_ratio,
                "logo_original_width": logo_original_width if media_logo_enabled else None,
                "logo_original_height": logo_original_height if media_logo_enabled else None,
                "logo_display_duration": logo_display_duration,
                "shorts_blur_bg": shorts_blur_bg,
                "lower_third_config": media_lower_third_config,
                "lower_third_interval": lower_third_interval,
                "lower_third_display_duration": lower_third_display_duration,
                "intro_outro_enabled": media_intro_outro_enabled,
                "intro_outro_channel_name": intro_outro_channel_name
                if media_intro_outro_enabled
                else "",
                "intro_outro_hold_duration": intro_outro_hold_duration,
                "intro_outro_bg_color": intro_outro_bg_color,
                "intro_outro_text_color": intro_outro_text_color,
                "progress_bar_enabled": media_progress_bar_enabled,
                "animated_watermark_enabled": media_animated_watermark_enabled,
                "watermark_logo_path": watermark_logo_path
                if media_animated_watermark_enabled
                else "",
                "subtitles_enabled": media_subtitles_enabled,
                "subtitle_style": subtitle_style,
                "subtitle_chunks": copy.deepcopy(
                    getattr(self, "last_transcript_chunks", [])
                )
                if media_subtitles_enabled
                else [],
                "video_effect": video_effect if normalized_kind == "full_video" else "none",
                "video_title": cached_title,
            }
        )

        if self.download_active:
            self.download_total = self.download_completed + len(self.download_queue) + 1
            self.download_overall_progress.set_segments(
                self.download_completed, self.download_total, 0.0
            )
            queued_label = "audio" if normalized_kind == "audio" else "vidéo entière"
            self.master.after(
                0,
                self._append_download_log,
                f"Ajout d'un téléchargement {queued_label} à la file d'attente.",
            )
            return

        self.download_completed = 0
        self.download_total = len(self.download_queue)
        self._start_download_ui(self.download_total)
        if not self.download_active:
            self.download_active = True
            self.download_cancel.clear()
            thread = threading.Thread(target=self._download_worker, daemon=True)
            self.download_thread = thread
            thread.start()

    def _set_active_card_index(self, idx: int | None) -> None:
        self._current_download_card_index = idx
        if idx is not None:
            bar = self._moment_mini_bars.get(idx)
            if bar:
                bar.configure(mode="indeterminate")

    def _download_worker(self) -> None:
        errors: List[str] = []
        try:
            while self.download_queue and not self.download_cancel.is_set():
                item = self.download_queue.pop(0)
                self.master.after(0, self._set_active_card_index, item.get("card_index"))
                index = self.download_completed + 1
                item_kind = str(item.get("kind", "clip")).strip() or "clip"
                self.download_last_percent_logged = -1
                self.download_last_size = ""
                yt_dlp_cmd = item.get("yt_dlp_cmd")
                if isinstance(yt_dlp_cmd, (list, tuple)):
                    title_cmd = list(yt_dlp_cmd)
                else:
                    title_cmd = []
                item["video_title"] = self._resolve_video_title(
                    str(item.get("url", "")).strip(),
                    title_cmd,
                )
                self.master.after(
                    0,
                    self._set_download_summary,
                    index,
                    self.download_total,
                    int(item.get("start", 0)),
                    int(item.get("duration", 0)),
                    str(item.get("format", "")),
                    item.get("video_title", ""),
                    bool(item.get("shorts")),
                    bool(item.get("logo_enabled") and item.get("logo_path")),
                    item.get(
                        "logo_position",
                        download_utils.DEFAULT_LOGO_POSITION,
                    ),
                    item.get("logo_size_mode", "relative"),
                    item.get(
                        "logo_scale_percent",
                        download_utils.DEFAULT_LOGO_SCALE_PERCENT,
                    ),
                    item.get("logo_opacity_percent", 100),
                    bool(item.get("subtitles_enabled") and item.get("subtitle_chunks")),
                    item.get("subtitle_style", "impact"),
                    item.get("video_effect", "none"),
                    item_kind,
                )
                if item_kind == "audio":
                    log_line = f"Audio {index}/{self.download_total} : téléchargement de la piste audio"
                elif item_kind == "full_video":
                    log_line = (
                        f"Vidéo {index}/{self.download_total} : téléchargement de la vidéo complète"
                    )
                else:
                    start_seconds = int(item.get("start", 0))
                    duration_seconds = int(item.get("duration", 0))
                    log_line = (
                        f"Clip {index}/{self.download_total} : {seconds_to_timestamp(start_seconds)} → "
                        f"{seconds_to_timestamp(start_seconds + duration_seconds)}"
                    )
                self.master.after(0, self._append_download_log, log_line)
                self.master.after(0, self._log_download_percent_steps, 0.0, "", "", "")
                if item_kind in {"full_video", "audio"}:
                    success, error = self._download_media_item(item)
                else:
                    success, error = self._download_clip(item)
                if not success and error:
                    errors.append(error)
                self.download_completed += 1
                self.master.after(
                    0, self._update_download_ui, self.download_completed, self.download_total
                )
        except Exception as error:
            LOGGER.exception("Unhandled download error in GUI thread")
            errors.append(f"Erreur inattendue: {error}")
        finally:
            cancelled = self.download_cancel.is_set()
            success = not errors and not cancelled
            message = errors[-1] if errors else ""
            self.master.after(0, self._finish_download_ui, success, message, cancelled)
            self.download_active = False
            self.download_queue = []
            self.download_cancel.clear()
            self.download_thread = None

    def _build_media_download_command(self, item: dict) -> List[str]:
        return download_utils.build_media_download_command(item)

    def _download_media_item(self, item: dict) -> tuple[bool, str]:
        media_kind = str(item.get("kind", "full_video")).strip().lower()
        video_format = str(item.get("format", "mp4")).strip().lower() or "mp4"
        output_dir = Path(str(item.get("output_dir", "")).strip() or ".")
        existing_files = {
            str(path.resolve())
            for path in output_dir.glob("*")
            if path.is_file()
        }
        reported_output_path = ""
        cmd = self._build_media_download_command(item)
        saw_progress = False
        stderr_lines: list[str] = []
        self.master.after(0, self._set_download_phase, "démarrage de yt-dlp")
        try:
            self.download_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            assert self.download_process.stderr is not None
            for line in self.download_process.stderr:
                if self.download_cancel.is_set():
                    self.download_process.terminate()
                    break
                clean = line.strip()
                if clean:
                    self.master.after(0, self._append_download_log, clean)
                    stderr_lines.append(clean)
                dest_match = DOWNLOAD_DEST_RE.search(clean)
                merger_match = DOWNLOAD_MERGER_RE.search(clean)
                already_match = DOWNLOAD_ALREADY_RE.search(clean)
                if dest_match:
                    reported_output_path = dest_match.group(1).strip()
                    self.master.after(
                        0, self._set_download_phase, "préparation du fichier de destination"
                    )
                elif merger_match:
                    reported_output_path = merger_match.group(1).strip()
                    self.master.after(
                        0, self._set_download_phase, "fusion audio/vidéo en cours"
                    )
                elif already_match:
                    reported_output_path = already_match.group(1).strip()
                    self.master.after(
                        0, self._set_download_phase, "fichier déjà téléchargé"
                    )
                if reported_output_path:
                    self.master.after(
                        0,
                        self.download_detail_var.set,
                        f"Fichier: {Path(reported_output_path).name}",
                    )
                match = DOWNLOAD_PROGRESS_RE.search(clean)
                if match:
                    saw_progress = True
                    percent = float(match.group(1))
                    size = match.group(2) or ""
                    speed = match.group(3) or ""
                    eta = match.group(4) or ""
                    self.master.after(
                        0, self._update_download_progress, percent, size, speed, eta
                    )
                    self.master.after(
                        0, self._log_download_percent_steps, percent, size, speed, eta
                    )
            code = self.download_process.wait()
        except OSError as error:
            return False, str(error)
        finally:
            self.download_process = None

        if self.download_cancel.is_set():
            return False, ""
        if code != 0:
            return False, _diagnose_ytdlp_error(stderr_lines)

        if saw_progress:
            self.master.after(
                0,
                self._log_download_percent_steps,
                100.0,
                self.download_last_size,
                "",
                "",
            )
        else:
            self.master.after(0, self._update_download_progress, 100.0, "", "", "")
        self.master.after(0, self._set_download_phase, "finalisation du téléchargement")

        downloaded_path = self._resolve_downloaded_path(
            output_dir=output_dir,
            video_format=video_format,
            existing_files=existing_files,
            reported_output_path=reported_output_path,
        )
        if not downloaded_path:
            return True, ""

        final_path = downloaded_path
        if media_kind == "full_video":
            try:
                variant_kwargs = {
                    "to_shorts": bool(item.get("shorts", False)),
                    "logo_path": item.get("logo_path", "")
                    if item.get("logo_enabled")
                    else "",
                    "logo_position": str(
                        item.get("logo_position", download_utils.DEFAULT_LOGO_POSITION)
                    ),
                    "logo_size_mode": str(item.get("logo_size_mode", "relative")),
                    "logo_scale_percent": int(
                        item.get(
                            "logo_scale_percent",
                            download_utils.DEFAULT_LOGO_SCALE_PERCENT,
                        )
                    ),
                    "logo_opacity_percent": int(item.get("logo_opacity_percent", 100)),
                    "logo_display_duration": item.get("logo_display_duration") or None,
                    "shorts_blur_bg": bool(item.get("shorts_blur_bg", True)),
                    "lower_third_config": item.get("lower_third_config"),
                    "intro_outro_enabled": bool(
                        item.get("intro_outro_enabled", False)
                    ),
                    "intro_outro_channel_name": str(
                        item.get("intro_outro_channel_name", "")
                    ),
                    "intro_outro_hold_duration": float(item.get("intro_outro_hold_duration", 1.5) or 1.5),
                    "intro_outro_bg_color": str(item.get("intro_outro_bg_color", "0x000000@0.75") or "0x000000@0.75"),
                    "intro_outro_text_color": str(item.get("intro_outro_text_color", "#FFFFFF") or "#FFFFFF"),
                    "progress_bar_enabled": bool(
                        item.get("progress_bar_enabled", False)
                    ),
                    "animated_watermark_enabled": bool(
                        item.get("animated_watermark_enabled", False)
                    ),
                    "watermark_logo_path": str(item.get("watermark_logo_path", "")),
                    "lower_third_interval": int(
                        item.get(
                            "lower_third_interval",
                            lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS,
                        )
                    ),
                    "lower_third_display_duration": int(
                        item.get(
                            "lower_third_display_duration",
                            lower_third.DEFAULT_DISPLAY_DURATION_SECONDS,
                        )
                    ),
                    **self._logo_ratio_options_from_item(item),
                }
                if item.get("subtitles_enabled"):
                    variant_kwargs.update(
                        {
                            "subtitle_chunks": item.get("subtitle_chunks", []),
                            "subtitle_start": 0.0,
                            "subtitle_duration": None,
                            "subtitle_offset_ms": int(item.get("subtitle_offset_ms", 0) or 0),
                            "subtitle_style": str(item.get("subtitle_style", "impact")),
                        }
                    )
                video_effect = str(item.get("video_effect", "none"))
                if video_effect != "none":
                    variant_kwargs["video_effect"] = video_effect
                final_path = self._build_download_variant(downloaded_path, **variant_kwargs)
            except RuntimeError as error:
                return False, str(error)
        else:
            item["shorts"] = False
            item["logo_enabled"] = False
            item["logo_path"] = ""
            item["subtitles_enabled"] = False
            item["subtitle_chunks"] = []
            item["video_effect"] = "none"
        if media_kind not in {"full_video", "audio"}:
            item["kind"] = "full_video"
        if final_path.suffix:
            item["format"] = final_path.suffix.lstrip(".").lower()
        self._record_download_history(item, final_path)
        self.last_downloaded_file = str(final_path)
        self.master.after(0, self.download_detail_var.set, f"Fichier: {final_path.name}")
        self.master.after(0, self._set_download_phase, "téléchargement terminé")
        if final_path != downloaded_path:
            self.master.after(
                0,
                self._append_download_log,
                f"Vidéo avec logo générée: {final_path.name}",
            )
        self._cleanup_intermediate_download(downloaded_path, final_path)
        return True, ""

    def _download_clip(self, item: dict) -> tuple[bool, str]:
        start = item["start"]
        duration = item["duration"]
        end = start + duration
        start_ts = seconds_to_timestamp(start)
        end_ts = seconds_to_timestamp(end)
        start_file = self._filename_timestamp(start)
        end_file = self._filename_timestamp(end)
        video_format = item["format"]
        clip_label = self._sanitize_filename_text(str(item.get("clip_label", "extrait")))
        output_dir = Path(item["output_dir"])
        existing_files = {
            str(path.resolve())
            for path in output_dir.glob("*")
            if path.is_file()
        }
        reported_output_path = ""
        output_template = f"{clip_label}_{start_file}-{end_file}.%(ext)s"

        cmd = [
            *item["yt_dlp_cmd"],
            "--no-playlist",
            "--download-sections",
            f"*{start_ts}-{end_ts}",
            *download_utils.build_best_video_download_args(video_format),
            "--paths",
            item["output_dir"],
            "-o",
            output_template,
            item["url"],
        ]
        saw_progress = False
        stderr_lines: list[str] = []
        self.master.after(0, self._set_download_phase, "démarrage de yt-dlp")
        try:
            self.download_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            assert self.download_process.stderr is not None
            for line in self.download_process.stderr:
                if self.download_cancel.is_set():
                    self.download_process.terminate()
                    break
                clean = line.strip()
                if clean:
                    self.master.after(0, self._append_download_log, clean)
                    stderr_lines.append(clean)
                dest_match = DOWNLOAD_DEST_RE.search(clean)
                merger_match = DOWNLOAD_MERGER_RE.search(clean)
                already_match = DOWNLOAD_ALREADY_RE.search(clean)
                if dest_match:
                    reported_output_path = dest_match.group(1).strip()
                    self.master.after(
                        0, self._set_download_phase, "préparation du fichier de destination"
                    )
                elif merger_match:
                    reported_output_path = merger_match.group(1).strip()
                    self.master.after(
                        0, self._set_download_phase, "fusion audio/vidéo en cours"
                    )
                elif already_match:
                    reported_output_path = already_match.group(1).strip()
                    self.master.after(
                        0, self._set_download_phase, "fichier déjà téléchargé"
                    )
                if reported_output_path:
                    self.master.after(
                        0,
                        self.download_detail_var.set,
                        f"Fichier: {Path(reported_output_path).name}",
                    )
                match = DOWNLOAD_PROGRESS_RE.search(clean)
                if match:
                    saw_progress = True
                    percent = float(match.group(1))
                    size = match.group(2) or ""
                    speed = match.group(3) or ""
                    eta = match.group(4) or ""
                    self.master.after(
                        0, self._update_download_progress, percent, size, speed, eta
                    )
                    self.master.after(
                        0, self._log_download_percent_steps, percent, size, speed, eta
                    )
            code = self.download_process.wait()
        except OSError as error:
            return False, str(error)
        finally:
            self.download_process = None

        if self.download_cancel.is_set():
            return False, ""
        if code != 0:
            return False, _diagnose_ytdlp_error(stderr_lines)

        if saw_progress:
            self.master.after(
                0,
                self._log_download_percent_steps,
                100.0,
                self.download_last_size,
                "",
                "",
            )
        else:
            self.master.after(0, self._update_download_progress, 100.0, "", "", "")
        self.master.after(0, self._set_download_phase, "finalisation du clip")

        downloaded_path = self._resolve_downloaded_path(
            output_dir=output_dir,
            video_format=video_format,
            existing_files=existing_files,
            reported_output_path=reported_output_path,
        )
        if not downloaded_path:
            return True, ""

        try:
            variant_kwargs = {
                "to_shorts": bool(item.get("shorts")),
                "logo_path": item.get("logo_path", "")
                if item.get("logo_enabled")
                else "",
                "logo_position": str(
                    item.get("logo_position", download_utils.DEFAULT_LOGO_POSITION)
                ),
                "logo_size_mode": str(item.get("logo_size_mode", "relative")),
                "logo_scale_percent": int(
                    item.get(
                        "logo_scale_percent",
                        download_utils.DEFAULT_LOGO_SCALE_PERCENT,
                    )
                ),
                "logo_opacity_percent": int(item.get("logo_opacity_percent", 100)),
                "logo_display_duration": item.get("logo_display_duration") or None,
            "shorts_blur_bg": bool(item.get("shorts_blur_bg", True)),
                "lower_third_config": item.get("lower_third_config"),
                "clip_duration": float(item.get("duration", 0) or 0),
                "intro_outro_enabled": bool(item.get("intro_outro_enabled", False)),
                "intro_outro_channel_name": str(
                    item.get("intro_outro_channel_name", "")
                ),
                "intro_outro_hold_duration": float(item.get("intro_outro_hold_duration", 1.5) or 1.5),
                "intro_outro_bg_color": str(item.get("intro_outro_bg_color", "0x000000@0.75") or "0x000000@0.75"),
                "intro_outro_text_color": str(item.get("intro_outro_text_color", "#FFFFFF") or "#FFFFFF"),
                "progress_bar_enabled": bool(item.get("progress_bar_enabled", False)),
                "animated_watermark_enabled": bool(
                    item.get("animated_watermark_enabled", False)
                ),
                "watermark_logo_path": str(item.get("watermark_logo_path", "")),
                "lower_third_interval": int(
                    item.get(
                        "lower_third_interval",
                        lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS,
                    )
                ),
                "lower_third_display_duration": int(
                    item.get(
                        "lower_third_display_duration",
                        lower_third.DEFAULT_DISPLAY_DURATION_SECONDS,
                    )
                ),
                **self._logo_ratio_options_from_item(item),
            }
            if item.get("subtitles_enabled"):
                variant_kwargs.update(
                    {
                        "subtitle_chunks": item.get("subtitle_chunks", []),
                        "subtitle_start": float(item.get("start", 0) or 0),
                        "subtitle_duration": float(item.get("duration", 0) or 0),
                        "subtitle_offset_ms": int(item.get("subtitle_offset_ms", 0) or 0),
                        "subtitle_style": str(item.get("subtitle_style", "impact")),
                    }
                )
            video_effect = str(item.get("video_effect", "none"))
            if video_effect != "none":
                variant_kwargs["video_effect"] = video_effect
            final_path = self._build_download_variant(downloaded_path, **variant_kwargs)
        except RuntimeError as error:
            return False, str(error)

        self._record_download_history(item, final_path)
        self.last_downloaded_file = str(final_path)
        self.master.after(0, self.download_detail_var.set, f"Fichier: {final_path.name}")
        self.master.after(0, self._set_download_phase, "téléchargement terminé")
        if final_path != downloaded_path:
            self.master.after(
                0,
                self._append_download_log,
                f"Variant générée: {final_path.name}",
            )
        self._cleanup_intermediate_download(downloaded_path, final_path)
        return True, ""

    def _cleanup_intermediate_download(self, source_path: Path, final_path: Path) -> None:
        if final_path == source_path:
            return
        try:
            source_path.unlink(missing_ok=True)
        except OSError as error:
            self.master.after(
                0,
                self._append_download_log,
                f"Impossible de supprimer le fichier intermédiaire: {error}",
            )

    @staticmethod
    def _download_variant_suffix(
        to_shorts: bool,
        has_logo: bool,
        has_subtitles: bool = False,
        has_lower_third: bool = False,
        has_intro_outro: bool = False,
        has_progress_bar: bool = False,
        has_watermark: bool = False,
        video_effect: str = "none",
        subtitle_style: str = "impact",
    ) -> str:
        return download_utils.download_variant_suffix(
            to_shorts,
            has_logo,
            has_subtitles=has_subtitles,
            has_lower_third=has_lower_third,
            has_intro_outro=has_intro_outro,
            has_progress_bar=has_progress_bar,
            has_watermark=has_watermark,
            video_effect=video_effect,
            subtitle_style=subtitle_style,
        )

    @classmethod
    def _download_variant_output_path(
        cls,
        input_path: Path,
        to_shorts: bool,
        has_logo: bool,
        has_subtitles: bool = False,
        has_lower_third: bool = False,
        has_intro_outro: bool = False,
        has_progress_bar: bool = False,
        has_watermark: bool = False,
        video_effect: str = "none",
        subtitle_style: str = "impact",
    ) -> Path:
        return download_utils.download_variant_output_path(
            input_path,
            to_shorts,
            has_logo,
            has_subtitles=has_subtitles,
            has_lower_third=has_lower_third,
            has_intro_outro=has_intro_outro,
            has_progress_bar=has_progress_bar,
            has_watermark=has_watermark,
            video_effect=video_effect,
            subtitle_style=subtitle_style,
        )

    def _resolve_downloaded_path(
        self,
        *,
        output_dir: Path,
        video_format: str,
        existing_files: set[str],
        reported_output_path: str,
    ) -> Path | None:
        if reported_output_path:
            candidate = Path(reported_output_path.strip().strip('"'))
            if not candidate.is_absolute():
                candidate = output_dir / candidate
            if candidate.exists() and candidate.is_file():
                return candidate

        candidates = [
            path
            for path in output_dir.glob(f"*.{video_format}")
            if path.is_file() and path.stat().st_size > 0
        ]
        if not candidates:
            candidates = [
                path
                for path in output_dir.iterdir()
                if path.is_file()
                and path.suffix.lower() in download_utils.COMMON_VIDEO_EXTENSIONS
                and path.stat().st_size > 0
            ]
        if not candidates:
            return None
        new_files = [
            path for path in candidates if str(path.resolve()) not in existing_files
        ]
        # Never fall back to pre-existing files: they might be stale render
        # outputs from a previous session, not the freshly downloaded clip.
        if not new_files:
            return None
        return max(new_files, key=lambda path: path.stat().st_mtime)

    def _build_download_variant(
        self,
        input_path: Path,
        *,
        to_shorts: bool,
        logo_path: str,
        logo_position: str = download_utils.DEFAULT_LOGO_POSITION,
        logo_size_mode: str = "relative",
        logo_scale_percent: int = download_utils.DEFAULT_LOGO_SCALE_PERCENT,
        logo_opacity_percent: int = 100,
        logo_width_ratio: float | None = None,
        logo_x_ratio: float | None = None,
        logo_y_ratio: float | None = None,
        logo_original_width: int | None = None,
        logo_original_height: int | None = None,
        subtitle_chunks: List[dict] | None = None,
        subtitle_start: float = 0.0,
        subtitle_duration: float | None = None,
        subtitle_offset_ms: int = 0,
        clip_duration: float | None = None,
        lower_third_interval: float = lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS,
        lower_third_display_duration: float = lower_third.DEFAULT_DISPLAY_DURATION_SECONDS,
        intro_outro_enabled: bool = False,
        intro_outro_channel_name: str = "",
        intro_outro_hold_duration: float = 1.5,
        intro_outro_bg_color: str = "0x000000@0.75",
        intro_outro_text_color: str = "#FFFFFF",
        progress_bar_enabled: bool = False,
        animated_watermark_enabled: bool = False,
        watermark_logo_path: str = "",
        subtitle_style: str = "impact",
        video_effect: str = "none",
        lower_third_config: lower_third.LowerThirdConfig | None = None,
        preview_width: int | None = None,
        logo_display_duration: float | None = None,
        shorts_blur_bg: bool = True,
    ) -> Path:
        ffmpeg_path = self._resolve_system_tool("ffmpeg")
        if ffmpeg_path is None:
            raise RuntimeError(
                "ffmpeg est requis pour générer les variantes vidéo créatives."
            )
        options = video_renderer.VideoRenderOptions(
            input_path=input_path,
            ffmpeg_path=ffmpeg_path,
            to_shorts=to_shorts,
            logo_path=logo_path,
            logo_position=logo_position,
            logo_size_mode=logo_size_mode,
            logo_scale_percent=logo_scale_percent,
            logo_opacity_percent=logo_opacity_percent,
            logo_width_ratio=logo_width_ratio,
            logo_x_ratio=logo_x_ratio,
            logo_y_ratio=logo_y_ratio,
            logo_original_width=logo_original_width,
            logo_original_height=logo_original_height,
            subtitle_chunks=subtitle_chunks,
            subtitle_start=subtitle_start,
            subtitle_duration=subtitle_duration,
            subtitle_offset_ms=subtitle_offset_ms,
            clip_duration=clip_duration,
            lower_third_interval=lower_third_interval,
            lower_third_display_duration=lower_third_display_duration,
            intro_outro_enabled=intro_outro_enabled,
            intro_outro_channel_name=intro_outro_channel_name,
            intro_outro_hold_duration=intro_outro_hold_duration,
            intro_outro_bg_color=intro_outro_bg_color,
            intro_outro_text_color=intro_outro_text_color,
            progress_bar_enabled=progress_bar_enabled,
            animated_watermark_enabled=animated_watermark_enabled,
            watermark_logo_path=watermark_logo_path,
            subtitle_style=subtitle_style,
            video_effect=video_effect,
            lower_third_config=lower_third_config,
            preview_width=preview_width,
            logo_display_duration=logo_display_duration if (logo_display_duration or 0) > 0 else None,
            shorts_blur_bg=shorts_blur_bg,
        )
        # Probe total duration for render progress (clip_duration first, then ffprobe)
        _total_dur = float(clip_duration or 0)
        if not _total_dur:
            try:
                _total_dur = float(
                    video_renderer._probe_media_duration(ffmpeg_path, input_path) or 0
                )
            except Exception:
                _total_dur = 0.0

        def _progress_runner(cmd, *, check, stdout, stderr, text):
            if not hasattr(self, "master"):
                return subprocess.run(cmd, check=check, stdout=stdout, stderr=stderr, text=text)
            # Reset bar and switch to render phase in UI
            self.master.after(0, lambda: self.download_current_progress.configure(value=0))
            self.master.after(0, self._set_download_phase, "rendu ffmpeg…")

            # Inject -progress pipe:1 before the output file (last arg)
            output_file = cmd[-1]
            progress_cmd = list(cmd[:-1]) + ["-progress", "pipe:1", output_file]

            _encode_start = time.monotonic()

            proc = subprocess.Popen(
                progress_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stderr_lines: list[str] = []

            def _read_stderr() -> None:
                for line in proc.stderr:
                    stderr_lines.append(line.rstrip())

            t = threading.Thread(target=_read_stderr, daemon=True)
            t.start()

            for line in proc.stdout:
                if line.startswith("out_time_us="):
                    try:
                        us = int(line.strip().split("=")[1])
                        elapsed = time.monotonic() - _encode_start
                        if _total_dur > 0:
                            pct = min(99.0, (us / 1_000_000) / _total_dur * 100)
                            self.master.after(
                                0, lambda p=pct: self.download_current_progress.configure(value=p)
                            )
                            if pct > 1.0:
                                remaining = max(0.0, elapsed / (pct / 100.0) - elapsed)
                                rem_m, rem_s = int(remaining) // 60, int(remaining) % 60
                                time_str = f"reste ~{rem_m}:{rem_s:02d}"
                            else:
                                time_str = "calcul…"
                            self.master.after(
                                0, self._set_download_phase,
                                f"rendu ffmpeg… {pct:.0f}% • {time_str}",
                            )
                        else:
                            elapsed_s = int(elapsed)
                            elapsed_str = f"{elapsed_s // 60}:{elapsed_s % 60:02d}"
                            self.master.after(
                                0, self._set_download_phase,
                                f"rendu ffmpeg… {elapsed_str}",
                            )
                    except (ValueError, IndexError):
                        pass

            t.join()
            proc.wait()

            if check and proc.returncode != 0:
                raise subprocess.CalledProcessError(
                    proc.returncode, cmd, stderr="\n".join(stderr_lines)
                )
            return subprocess.CompletedProcess(cmd, proc.returncode)

        return video_renderer.render_video_variant(options, runner=_progress_runner)

    @staticmethod
    def _logo_overlay_x_expr(position: str, margin: int = 36) -> str:
        return download_utils.logo_overlay_x_expr(position, margin)

    @staticmethod
    def _logo_overlay_y_expr(position: str, margin: int = 36) -> str:
        return download_utils.logo_overlay_y_expr(position, margin)

    @staticmethod
    def _logo_opacity_ratio(percent: int) -> float:
        return download_utils.logo_opacity_ratio(percent)

    def _start_download_ui(self, total: int) -> None:
        self._set_busy_state(True)
        self._reset_download_ui()
        if hasattr(self, "_download_status_shadow"):
            self._download_status_shadow.grid()
        self.download_overall_progress.set_segments(0, total, 0.0)
        self.download_current_progress.configure(maximum=100, value=0, mode="indeterminate")
        self.download_summary_var.set(f"Téléchargement 0/{total} • 0%")
        self.download_detail_var.set("Préparation du téléchargement…")
        self._set_download_phase("initialisation de la file")
        self.status_var.set("Téléchargement en cours…")
        self._append_download_log("Démarrage du téléchargement.")

    def _update_download_ui(self, completed: int, total: int) -> None:
        total_safe = max(1, total)
        overall_percent = (completed / total_safe) * 100.0
        self.download_overall_progress.set_segments(completed, total, 0.0)
        self.download_current_progress.configure(value=0)
        # Mark the just-completed clip's mini-bar as success
        idx = getattr(self, "_current_download_card_index", None)
        if idx is not None:
            bar = getattr(self, "_moment_mini_bars", {}).get(idx)
            if bar:
                bar.configure(value=100)
                bar.set_state("success")
        self.download_detail_var.set(f"Global {overall_percent:.1f}%")
        if completed >= total:
            self.download_summary_var.set(
                f"Téléchargement terminé ({completed}/{total}) • 100%"
            )
            self._set_download_phase("tous les clips sont traités")
        else:
            self.download_current_progress.configure(mode="indeterminate")
            self.download_summary_var.set(
                f"Téléchargement {completed}/{total} • {overall_percent:.1f}%"
            )
            self._set_download_phase("préparation du clip suivant")

    def _finish_download_ui(self, success: bool, message: str, cancelled: bool) -> None:
        if cancelled:
            self.download_overall_progress.clear_segments()
            self.download_overall_progress.set_state("error")
            self.download_current_progress.configure(mode="determinate", value=0)
            self.download_current_progress.set_state("error")
            self._set_status("Téléchargement annulé.", busy=False)
            self.download_detail_var.set("Téléchargement annulé.")
            self._set_download_phase("annulé par l'utilisateur")
            self._append_download_log("Téléchargement annulé.")
            self.master.after(3000, self._hide_download_status)
            return
        if success:
            total = self.download_total
            self.download_overall_progress.set_segments(total, total, 0.0)
            self.download_current_progress.configure(mode="determinate", value=100)
            self.download_current_progress.set_state("success")
            self._set_status(
                "Extraction terminée avec succès ✓", busy=False, success=True
            )
            self.download_detail_var.set("✔ Téléchargement terminé · 📁 Fichier prêt")
            self._set_download_phase("terminé")
            self._append_download_log("Téléchargements terminés.")
            if sys.platform == "darwin":
                label = f"{total} fichier(s) prêt(s)" if total > 1 else "Fichier prêt"
                subprocess.Popen(
                    [
                        "osascript", "-e",
                        f'display notification "{label}" with title "Téléchargement terminé" sound name "Glass"',
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            self.master.after(5000, self._hide_download_status)
        else:
            self.download_overall_progress.clear_segments()
            self.download_overall_progress.set_state("error")
            self.download_current_progress.configure(mode="determinate", value=0)
            self.download_current_progress.set_state("error")
            self._set_status("Erreur lors du téléchargement.", busy=False, error=True)
            self.download_detail_var.set("Erreur lors du téléchargement.")
            self._set_download_phase("échec")
            if message:
                messagebox.showerror("Téléchargement impossible", message)
            self.master.after(8000, self._hide_download_status)

    def _hide_download_status(self) -> None:
        if self.download_active:
            return
        if hasattr(self, "_download_status_shadow"):
            self._download_status_shadow.grid_remove()

    def copy_to_clipboard(self) -> None:
        content = self.output_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Aucune donnée", "Rien à copier pour le moment.")
            return
        self.master.clipboard_clear()
        self.master.clipboard_append(content)
        self._set_status("Transcription copiée ✓", busy=False, success=True)

    def clear_form(self) -> None:
        self._set_entry_text(self.url_entry, "")
        self._set_entry_text(self.languages_entry, "")
        self._restore_placeholder(self.url_entry)
        self._restore_placeholder(self.languages_entry)
        self.output_text.delete("1.0", tk.END)
        self._render_most_viewed_cards([])
        self.last_most_viewed_moments = []
        self.last_transcript_chunks = []
        self.meta_var.set("")
        self._update_stats("")
        self._set_status("Formulaire réinitialisé.", busy=False)

    def paste_url(self) -> None:
        self._paste_into_entry(self.url_entry)

    def preview_video(self) -> None:
        self.open_url()

    def open_url(self) -> None:
        url = self._get_entry_value(self.url_entry)
        if not url:
            messagebox.showinfo("Aucun lien", "Colle un lien vidéo à ouvrir.")
            return
        webbrowser.open(url)

    def cancel(self) -> None:
        if not self.busy:
            return
        if self.download_active:
            self.download_cancel.set()
            if self.download_process and self.download_process.poll() is None:
                self.download_process.terminate()
            self.download_queue = []
            self.status_var.set("Annulation du téléchargement…")
            self._set_download_phase("annulation en cours")
            return
        if self.download_process and self.download_process.poll() is None:
            self.cancel_event.set()
            self.current_job_id += 1
            self.download_process.terminate()
            self._set_status("Traitement annulé.", busy=False)
            return
        self.cancel_event.set()
        self.current_job_id += 1
        self._set_status("Annulation demandée.", busy=False)

    def _set_status(
        self, message: str, *, busy: bool, error: bool = False, success: bool = False
    ) -> None:
        self.status_var.set(message)
        if busy:
            self._set_busy_state(True)
            if not self.download_active:
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
        else:
            self._set_busy_state(False)
            self.progress.stop()
        if error:
            self.style.configure("Status.TLabel", foreground=self.palette["status_error"])
        elif success:
            self.style.configure("Status.TLabel", foreground=self.palette["success"])
        else:
            self.style.configure("Status.TLabel", foreground=self.palette["accent"])

    @staticmethod
    def _parse_languages(raw: str) -> Optional[List[str]]:
        langs = [part.strip() for part in raw.split(",") if part.strip()]
        return langs or None

    def _apply_placeholder(self, entry: ttk.Entry, placeholder: str) -> None:
        entry._placeholder_text = placeholder
        current_value = entry.get().strip()
        if current_value:
            entry.configure(style="Normal.TEntry")
            entry._placeholder_active = False
        else:
            entry.delete(0, tk.END)
            entry.insert(0, placeholder)
            entry.configure(style="Placeholder.TEntry")
            entry._placeholder_active = True
        entry.bind("<FocusIn>", lambda event: self._clear_placeholder(entry))
        entry.bind("<FocusOut>", lambda event: self._restore_placeholder(entry))

    def _clear_placeholder(self, entry: ttk.Entry) -> None:
        if getattr(entry, "_placeholder_active", False):
            entry.delete(0, tk.END)
            entry.configure(style="Normal.TEntry")
            entry._placeholder_active = False

    def _restore_placeholder(self, entry: ttk.Entry) -> None:
        if entry.get().strip():
            return
        placeholder = getattr(entry, "_placeholder_text", "")
        if not placeholder:
            return
        entry.delete(0, tk.END)
        entry.insert(0, placeholder)
        entry.configure(style="Placeholder.TEntry")
        entry._placeholder_active = True

    def _get_entry_value(self, entry: ttk.Entry) -> str:
        value = entry.get().strip()
        if getattr(entry, "_placeholder_active", False):
            placeholder = getattr(entry, "_placeholder_text", "").strip()
            if value and value != placeholder:
                entry._placeholder_active = False
                if isinstance(entry, ttk.Entry):
                    entry.configure(style="Normal.TEntry")
                return value
            return ""
        return value

    def _set_entry_text(self, entry: ttk.Entry, value: str) -> None:
        if isinstance(entry, ttk.Entry):
            entry.configure(style="Normal.TEntry")
        entry.delete(0, tk.END)
        entry.insert(0, value)
        entry._placeholder_active = False

    def _paste_into_entry(self, entry: ttk.Entry) -> None:
        try:
            text = self.master.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Presse-papiers vide", "Aucune donnée à coller.")
            return
        self._set_entry_text(entry, text)

    def _selected_output_format(self) -> str:
        label = self.output_format_var.get()
        return self.output_format_reverse.get(label, "text")

    def _update_stats(self, content: str) -> None:
        lines = content.splitlines() if content else []
        chars = len(content)
        self.stats_var.set(f"Lignes: {len(lines)} | Caractères: {chars}")

    def _append_output(self, message: str) -> None:
        if self.output_text.get("1.0", tk.END).strip():
            self.output_text.insert(tk.END, "\n")
        self.output_text.insert(tk.END, message)
        self._update_stats(self.output_text.get("1.0", tk.END).strip())

    def _style_text_widget(
        self, widget: scrolledtext.ScrolledText, *, background: str
    ) -> None:
        widget.configure(
            background=background,
            foreground=self.palette["text"],
            insertbackground=self.palette["text"],
            selectbackground=self.palette["select"],
            highlightbackground=self.palette["border"],
            highlightcolor=self.palette["accent"],
            relief="flat",
            borderwidth=1,
        )
        widget.configure(spacing1=2, spacing2=6, spacing3=2)

    def _get_most_viewed_limit(self) -> int:
        try:
            value = int(self.most_viewed_count_var.get())
        except (TypeError, ValueError):
            return 5
        return max(1, min(20, value))

    def _get_clip_duration(self) -> int:
        try:
            value = int(self.clip_duration_var.get())
        except (TypeError, ValueError):
            return 60
        return max(10, min(300, value))

    def _has_active_background_task(self) -> bool:
        if self.download_active:
            return True
        for thread in (
            self.generation_thread,
            self.download_thread,
            getattr(self, "preview_thread", None),
        ):
            if thread and thread.is_alive():
                return True
        return bool(self.download_process and self.download_process.poll() is None)

    def _recover_stale_busy_state(self) -> None:
        if self.busy and not self._has_active_background_task():
            LOGGER.warning("Recovering stale busy UI state.")
            self._set_status("Prêt.", busy=False)

    def _set_busy_state(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        widget_names = (
            "generate_button",
            "copy_button",
            "clear_button",
            "save_button",
            "download_moments_button",
            "options_toggle_button",
            "download_clips_button",
            "download_full_video_button",
            "download_audio_button",
            "download_toggle_button",
            "download_history_refresh_button",
            "download_history_clear_button",
            "download_preset_combo",
            "download_aspect_ratio_combo",
            "download_logo_check",
            "download_video_logo_check",
            "download_logo_button",
            "download_logo_size_mode_combo",
            "download_logo_size_scale",
            "download_logo_opacity_scale",
            "download_logo_position_combo",
            "download_intro_outro_check",
            "download_progress_bar_check",
            "download_animated_watermark_check",
            "download_lower_third_check",
            "download_lower_third_name_entry",
            "download_lower_third_tagline_entry",
            "download_lower_third_subscribe_check",
            "download_lower_third_bg_button",
            "download_lower_third_accent_button",
            "download_lower_third_interval_scale",
            "download_lower_third_display_duration_scale",
            "download_subtitles_check",
            "download_subtitle_style_combo",
            "download_video_effect_combo",
            "preview_video_button",
            "quick_transcribe_button",
            "quick_download_full_video_button",
            "quick_download_audio_button",
        )
        for name in widget_names:
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(state=state)
        for widget in getattr(self, "_moment_action_buttons", []):
            if widget is not None:
                widget.configure(state=state)
        cancel_button = getattr(self, "cancel_button", None)
        if cancel_button is not None:
            cancel_button.configure(state="normal" if busy else "disabled")
        self._update_value_add_controls_state()
        self._update_download_logo_controls_state()
        self._update_lower_third_controls_state()
        if not busy:
            self._update_generate_state()

    def _update_generate_state(self) -> None:
        self._recover_stale_busy_state()
        if self.busy:
            self.generate_button.configure(state="disabled")
            for name in (
                "preview_video_button",
                "quick_transcribe_button",
                "quick_download_full_video_button",
                "quick_download_audio_button",
            ):
                widget = getattr(self, name, None)
                if widget is not None:
                    widget.configure(state="disabled")
            return
        has_url = bool(self._get_entry_value(self.url_entry))
        self.generate_button.configure(state="normal" if has_url else "disabled")
        for name in (
            "preview_video_button",
            "quick_transcribe_button",
            "quick_download_full_video_button",
            "quick_download_audio_button",
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(state="normal" if has_url else "disabled")

    def _should_ignore_result(self, job_id: int) -> bool:
        return self.cancel_event.is_set() or job_id != self.current_job_id

    def _bind_shortcuts(self) -> None:
        self.master.bind("<Control-Return>", lambda event: self.generate())
        self.master.bind("<Control-v>", self._handle_paste_shortcut)
        self.master.bind("<Control-V>", self._handle_paste_shortcut)
        self.master.bind("<Control-Home>", self.scroll_to_top)
        self.master.bind("<Control-End>", self.scroll_to_bottom)
        self.master.bind("<Alt-Up>", lambda event: self._scroll_main_page(-1))
        self.master.bind("<Alt-Down>", lambda event: self._scroll_main_page(1))

    def _handle_paste_shortcut(self, event: tk.Event) -> str | None:
        widget = self.master.focus_get()
        if widget in (
            self.url_entry,
            self.languages_entry,
            self.download_logo_entry,
        ):
            self._paste_into_entry(widget)
            return "break"
        return None


def main() -> None:
    root = tk.Tk()
    app = TranscriptApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
