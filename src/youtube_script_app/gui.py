"""Tkinter GUI for generating YouTube video transcripts."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
from typing import List, Optional

from .downloads import history as history_store
from .downloads import utils as download_utils
from .core import subtitle_renderer
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
COMMON_TOOL_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)


class TranscriptApp:
    """Simple GUI wrapper around the CLI transcript generator."""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("Générateur de script YouTube")
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
            "Taille originale": "original",
            "Personnalisée": "relative",
        }
        self.download_logo_size_mode_var = tk.StringVar(value="Personnalisée")
        self.download_logo_size_var = tk.IntVar(value=58)
        self.download_logo_size_label_var = tk.StringVar(value="58%")
        self.download_logo_opacity_var = tk.IntVar(value=100)
        self.download_logo_opacity_label_var = tk.StringVar(value="100%")
        self.download_logo_position_var = tk.StringVar(value="Milieu")
        self.download_logo_position_lookup = {
            "Haut": "top",
            "Milieu": "center",
            "Bas": "bottom",
        }
        self.download_subtitles_enabled_var = tk.BooleanVar(value=True)
        self.download_subtitle_style_lookup = {
            "Impact TikTok": "impact",
            "Moderne blanc": "modern",
            "Cinéma": "cinema",
            "Boîte noire": "box",
            "Minimal": "minimal",
        }
        self.download_subtitle_style_var = tk.StringVar(value="Impact TikTok")
        self.download_video_effect_lookup = {
            "Aucun": "none",
            "Noir et blanc": "black_white",
            "Contraste fort": "contrast",
            "Cinéma sombre": "cinematic",
            "Vintage": "vintage",
        }
        self.download_video_effect_var = tk.StringVar(value="Aucun")
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
            "write", self._on_download_preferences_change
        )
        self.download_preset_var.trace_add("write", self._on_download_preset_change)
        self.video_format_var.trace_add("write", self._on_download_preferences_change)
        self.clip_duration_var.trace_add("write", self._on_download_preferences_change)
        self.download_logo_enabled_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_logo_position_var.trace_add(
            "write", self._on_download_preferences_change
        )
        self.download_logo_size_mode_var.trace_add(
            "write", self._on_download_logo_size_mode_change
        )
        self.download_logo_size_var.trace_add(
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
        self.download_logo_entry.bind(
            "<FocusOut>", self._on_download_logo_focus_out, add="+"
        )
        self._update_generate_state()
        self._bind_shortcuts()

    def _apply_blue_theme(self) -> None:
        self.palette = {
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
        }
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
            padding=(12, 7),
            font=font_main,
        )
        self.style.map(
            "TButton",
            background=[("active", "#e0e4f8"), ("disabled", "#eaecf6")],
        )
        self.style.configure(
            "Primary.TButton",
            background=self.palette["accent"],
            foreground="#ffffff",
            padding=(22, 13),
            font=font_button,
        )
        self.style.map(
            "Primary.TButton",
            background=[
                ("active", self.palette["accent_dark"]),
                ("disabled", "#9b9bd4"),
            ],
            foreground=[("disabled", "#e8e8f5")],
        )
        self.style.configure(
            "Secondary.TButton",
            background="#ffffff",
            foreground=self.palette["muted"],
            padding=(11, 8),
            font=font_main,
            bordercolor=self.palette["border"],
        )
        self.style.map(
            "Secondary.TButton",
            background=[("active", "#f0eeff"), ("disabled", "#f5f6fb")],
            foreground=[("active", self.palette["accent"]), ("disabled", "#9aa0be")],
        )
        self.style.configure(
            "TEntry",
            fieldbackground="#ffffff",
            foreground=self.palette["text"],
            bordercolor=self.palette["border"],
        )
        self.style.configure(
            "Normal.TEntry",
            fieldbackground="#ffffff",
            foreground=self.palette["text"],
        )
        self.style.configure(
            "Placeholder.TEntry",
            fieldbackground="#f3f1ff",
            foreground="#7b82aa",
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
            background="#ebebff",
            foreground=self.palette["accent"],
            padding=(13, 9),
            font=font_main,
            bordercolor=self.palette["border"],
        )
        self.style.map(
            "SoftPrimary.TButton",
            background=[("active", "#ddddf8"), ("disabled", "#f0f0ff")],
            foreground=[("active", self.palette["accent_dark"]), ("disabled", "#94a3b8")],
        )
        self.style.configure(
            "Subtle.TButton",
            background="#f4f5fb",
            foreground=self.palette["muted"],
            padding=(9, 6),
            font=font_subtle,
            bordercolor=self.palette["border"],
        )
        self.style.map(
            "Subtle.TButton",
            background=[("active", "#e8eaf6"), ("disabled", "#f1f3f9")],
            foreground=[("active", self.palette["accent"]), ("disabled", "#9aa0be")],
        )
        self.style.map(
            "Link.TButton",
            foreground=[("active", self.palette["accent_dark"])],
            background=[("active", self.palette["card"])],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground="#ffffff",
            foreground=self.palette["text"],
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

    def _center_container(self) -> None:
        self.master.bind("<Configure>", self._on_root_resize)
        self._on_root_resize()

    def _on_root_resize(self, event: tk.Event | None = None) -> None:
        if not hasattr(self, "_content_container"):
            return
        width = self.master.winfo_width()
        if width <= 1:
            width = self.master.winfo_screenwidth()
        extra = max(0, width - self._content_max_width)
        side = max(self._content_padding, int(extra / 2))
        self._content_container.configure(padding=(side, self._content_padding))

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
        container.grid_rowconfigure(5, weight=1)
        self._content_container = container
        self._content_max_width = 1200
        self._content_padding = 18
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
            fg="#ffffff",
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
        self.scroll_top_button = ttk.Button(
            nav_buttons,
            text="↑ Haut",
            command=self.scroll_to_top,
            style="Secondary.TButton",
        )
        self.scroll_top_button.grid(row=0, column=0, sticky="ew")
        self.scroll_bottom_button = ttk.Button(
            nav_buttons,
            text="↓ Bas",
            command=self.scroll_to_bottom,
            style="Secondary.TButton",
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
            "#6366f1", "#7c3aed", "#a855f7", "#6366f1", "#4f46e5",
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
        ttk.Button(
            url_actions,
            text="📋 Coller l'URL",
            command=self.paste_url,
            style="SoftPrimary.TButton",
        ).grid(row=0, column=0, sticky="w")
        self.preview_video_button = ttk.Button(
            url_actions,
            text="▶ Voir la vidéo",
            command=self.preview_video,
            style="Secondary.TButton",
        )
        self.preview_video_button.grid(row=0, column=1, sticky="w", padx=(10, 0))

        quick_actions = tk.Frame(url_card, bg=self.palette["card"])
        quick_actions.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 14))
        quick_actions.grid_columnconfigure(0, weight=1)
        quick_actions.grid_columnconfigure(1, weight=1)
        quick_actions.grid_columnconfigure(2, weight=1)

        self.quick_transcribe_button = ttk.Button(
            quick_actions,
            text="Transcription YouTube",
            command=self.generate,
            style="Primary.TButton",
        )
        self.quick_transcribe_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.quick_download_full_video_button = ttk.Button(
            quick_actions,
            text="⬇ Télécharger vidéo",
            command=self.download_full_video,
            style="Secondary.TButton",
        )
        self.quick_download_full_video_button.grid(row=0, column=1, sticky="ew", padx=6)

        self.quick_download_audio_button = ttk.Button(
            quick_actions,
            text="🎵 Télécharger audio",
            command=self.download_audio_only,
            style="Secondary.TButton",
        )
        self.quick_download_audio_button.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        self._apply_placeholder(self.url_entry, "https://www.youtube.com/watch?v=... ou lien social")

        options_shadow = tk.Frame(container, bg=self.palette["shadow"])
        options_shadow.grid(row=2, column=0, sticky="ew", pady=(0, 14))
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
        self.options_body.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 14))
        self.options_body.grid_columnconfigure(0, weight=1)

        ttk.Label(
            self.options_body,
            text="Langues (séparées par des virgules)",
            style="Card.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.languages_entry = ttk.Entry(
            self.options_body, textvariable=self.languages_var, style="Normal.TEntry"
        )
        self.languages_entry.grid(row=1, column=0, sticky="ew", pady=(6, 10))
        self._apply_placeholder(self.languages_entry, "fr,en")

        ttk.Label(self.options_body, text="Format de sortie", style="Card.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        self.format_combo = ttk.Combobox(
            self.options_body,
            textvariable=self.output_format_var,
            values=list(self.output_format_lookup.values()),
            state="readonly",
        )
        self.format_combo.grid(row=3, column=0, sticky="w", pady=(6, 10))

        ttk.Checkbutton(
            self.options_body,
            text="Moments forts estimés",
            variable=self.most_viewed_var,
            style="Card.TCheckbutton",
        ).grid(row=4, column=0, sticky="w")
        count_row = tk.Frame(self.options_body, bg=self.palette["card"])
        count_row.grid(row=5, column=0, sticky="w", pady=(6, 0))
        ttk.Label(count_row, text="Nombre", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.most_viewed_spin = ttk.Spinbox(
            count_row,
            from_=1,
            to=20,
            width=5,
            textvariable=self.most_viewed_count_var,
        )
        self.most_viewed_spin.grid(row=0, column=1, sticky="w", padx=(10, 0))

        duration_row = tk.Frame(self.options_body, bg=self.palette["card"])
        duration_row.grid(row=6, column=0, sticky="w", pady=(10, 0))
        ttk.Label(duration_row, text="Durée extrait (s)", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.clip_duration_spin = ttk.Spinbox(
            duration_row,
            from_=10,
            to=300,
            increment=10,
            width=5,
            textvariable=self.clip_duration_var,
        )
        self.clip_duration_spin.grid(row=0, column=1, sticky="w", padx=(10, 0))

        format_row = tk.Frame(self.options_body, bg=self.palette["card"])
        format_row.grid(row=7, column=0, sticky="w", pady=(10, 0))
        ttk.Label(format_row, text="Format vidéo", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.video_format_combo = ttk.Combobox(
            format_row,
            textvariable=self.video_format_var,
            values=["mp4", "webm"],
            state="readonly",
            width=6,
        )
        self.video_format_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))

        preset_row = tk.Frame(self.options_body, bg=self.palette["card"])
        preset_row.grid(row=8, column=0, sticky="w", pady=(10, 0))
        ttk.Label(preset_row, text="Preset créatif", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.download_preset_combo = ttk.Combobox(
            preset_row,
            textvariable=self.download_preset_var,
            values=list(self.download_preset_lookup.keys()),
            state="readonly",
            width=18,
        )
        self.download_preset_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))

        aspect_row = tk.Frame(self.options_body, bg=self.palette["card"])
        aspect_row.grid(row=9, column=0, sticky="w", pady=(10, 0))
        ttk.Label(aspect_row, text="Format final", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.download_aspect_ratio_combo = ttk.Combobox(
            aspect_row,
            textvariable=self.download_aspect_ratio_var,
            values=list(self.download_aspect_ratio_lookup.keys()),
            state="readonly",
            width=14,
        )
        self.download_aspect_ratio_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.download_logo_check = ttk.Checkbutton(
            self.options_body,
            text="Intégrer le logo",
            variable=self.download_logo_enabled_var,
            command=self._on_download_logo_toggle,
            style="Card.TCheckbutton",
        )
        self.download_logo_check.grid(row=10, column=0, sticky="w", pady=(8, 0))

        logo_row = tk.Frame(self.options_body, bg=self.palette["card"])
        logo_row.grid(row=11, column=0, sticky="ew", pady=(8, 0))
        logo_row.grid_columnconfigure(0, weight=1)
        ttk.Label(
            logo_row,
            text="Logo à intégrer (facultatif)",
            style="Card.TLabel",
        ).grid(row=0, column=0, sticky="w")
        logo_input = tk.Frame(logo_row, bg=self.palette["card"])
        logo_input.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        logo_input.grid_columnconfigure(0, weight=1)
        self.download_logo_entry = ttk.Entry(
            logo_input,
            textvariable=self.download_logo_var,
            style="Normal.TEntry",
        )
        self.download_logo_entry.grid(row=0, column=0, sticky="ew")
        self.download_logo_button = ttk.Button(
            logo_input,
            text="Choisir…",
            command=self.select_download_logo,
            style="Secondary.TButton",
        )
        self.download_logo_button.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self._apply_placeholder(self.download_logo_entry, DOWNLOAD_LOGO_PLACEHOLDER)

        logo_position_row = tk.Frame(self.options_body, bg=self.palette["card"])
        logo_position_row.grid(row=12, column=0, sticky="ew", pady=(8, 0))
        logo_position_row.grid_columnconfigure(0, weight=1)
        ttk.Label(
            logo_position_row,
            text="Position du logo",
            style="Card.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.download_logo_position_combo = ttk.Combobox(
            logo_position_row,
            textvariable=self.download_logo_position_var,
            values=list(self.download_logo_position_lookup.keys()),
            state="readonly",
            width=12,
        )
        self.download_logo_position_combo.grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )

        logo_size_mode_row = tk.Frame(self.options_body, bg=self.palette["card"])
        logo_size_mode_row.grid(row=13, column=0, sticky="ew", pady=(8, 0))
        logo_size_mode_row.grid_columnconfigure(0, weight=1)
        ttk.Label(
            logo_size_mode_row,
            text="Mode taille logo",
            style="Card.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.download_logo_size_mode_combo = ttk.Combobox(
            logo_size_mode_row,
            textvariable=self.download_logo_size_mode_var,
            values=list(self.download_logo_size_mode_lookup.keys()),
            state="readonly",
            width=18,
        )
        self.download_logo_size_mode_combo.grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )

        logo_size_row = tk.Frame(self.options_body, bg=self.palette["card"])
        logo_size_row.grid(row=14, column=0, sticky="ew", pady=(8, 0))
        logo_size_row.grid_columnconfigure(0, weight=1)
        ttk.Label(logo_size_row, text="Taille logo", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            logo_size_row,
            textvariable=self.download_logo_size_label_var,
            style="CardMuted.TLabel",
        ).grid(row=0, column=1, sticky="e")
        self.download_logo_size_scale = ttk.Scale(
            logo_size_row,
            from_=20,
            to=80,
            variable=self.download_logo_size_var,
            orient="horizontal",
            command=self._on_logo_size_change,
        )
        self.download_logo_size_scale.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        logo_opacity_row = tk.Frame(self.options_body, bg=self.palette["card"])
        logo_opacity_row.grid(row=15, column=0, sticky="ew", pady=(8, 0))
        logo_opacity_row.grid_columnconfigure(0, weight=1)
        ttk.Label(logo_opacity_row, text="Opacité logo", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            logo_opacity_row,
            textvariable=self.download_logo_opacity_label_var,
            style="CardMuted.TLabel",
        ).grid(row=0, column=1, sticky="e")
        self.download_logo_opacity_scale = ttk.Scale(
            logo_opacity_row,
            from_=10,
            to=100,
            variable=self.download_logo_opacity_var,
            orient="horizontal",
            command=self._on_logo_opacity_change,
        )
        self.download_logo_opacity_scale.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        self.download_subtitles_check = ttk.Checkbutton(
            self.options_body,
            text="Ajouter sous-titres",
            variable=self.download_subtitles_enabled_var,
            style="Card.TCheckbutton",
        )
        self.download_subtitles_check.grid(row=16, column=0, sticky="w", pady=(10, 0))

        subtitle_style_row = tk.Frame(self.options_body, bg=self.palette["card"])
        subtitle_style_row.grid(row=17, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            subtitle_style_row,
            text="Design sous-titres",
            style="Card.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.download_subtitle_style_combo = ttk.Combobox(
            subtitle_style_row,
            textvariable=self.download_subtitle_style_var,
            values=list(self.download_subtitle_style_lookup.keys()),
            state="readonly",
            width=16,
        )
        self.download_subtitle_style_combo.grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )

        video_effect_row = tk.Frame(self.options_body, bg=self.palette["card"])
        video_effect_row.grid(row=18, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            video_effect_row,
            text="Effet vidéo",
            style="Card.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.download_video_effect_combo = ttk.Combobox(
            video_effect_row,
            textvariable=self.download_video_effect_var,
            values=list(self.download_video_effect_lookup.keys()),
            state="readonly",
            width=16,
        )
        self.download_video_effect_combo.grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )
        self._update_download_logo_controls_state()

        self.options_body.grid_remove()

        cta_shadow = tk.Frame(container, bg=self.palette["shadow"])
        cta_shadow.grid(row=3, column=0, sticky="ew", pady=(4, 12))
        cta_card = tk.Frame(cta_shadow, bg=self.palette["card"])
        cta_card.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        cta_card.grid_columnconfigure(0, weight=1)

        ttk.Label(
            cta_card,
            text="Transcription YouTube",
            style="CardMuted.TLabel",
        ).grid(row=0, column=0, sticky="n", pady=(14, 4))
        self.generate_button = ttk.Button(
            cta_card,
            text="Transcrire la vidéo YouTube",
            command=self.generate,
            style="Primary.TButton",
        )
        self.generate_button.grid(
            row=1, column=0, sticky="ew", padx=160, pady=(0, 16), ipadx=30
        )

        actions = tk.Frame(container, bg=self.palette["bg"])
        actions.grid(row=4, column=0, sticky="ew", pady=(0, 16))
        actions.grid_columnconfigure(0, weight=1)

        actions_right = tk.Frame(actions, bg=self.palette["bg"])
        actions_right.grid(row=0, column=1, sticky="e")

        self.save_button = ttk.Button(
            actions_right,
            text="Enregistrer",
            command=self.save_transcript,
            style="Subtle.TButton",
        )
        self.save_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.download_moments_button = ttk.Button(
            actions_right,
            text="Exporter liste",
            command=self.export_moments,
            style="Subtle.TButton",
        )
        self.download_moments_button.grid(row=0, column=1, sticky="ew", padx=6)

        self.clear_button = ttk.Button(
            actions_right,
            text="Réinitialiser",
            command=self.clear_form,
            style="Subtle.TButton",
        )
        self.clear_button.grid(row=0, column=2, sticky="ew", padx=6)

        self.cancel_button = ttk.Button(
            actions_right,
            text="Annuler",
            command=self.cancel,
            state="disabled",
            style="Subtle.TButton",
        )
        self.cancel_button.grid(row=0, column=3, sticky="ew", padx=(6, 0))

        transcript_shadow = tk.Frame(container, bg=self.palette["shadow"])
        transcript_shadow.grid(row=5, column=0, sticky="nsew", pady=(0, 16))
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
        self.copy_button = ttk.Button(
            transcript_header,
            text="📋 Copier",
            command=self.copy_to_clipboard,
            style="Secondary.TButton",
        )
        self.copy_button.grid(row=0, column=1, sticky="e")

        self.output_text = scrolledtext.ScrolledText(
            transcript_card, wrap=tk.WORD, height=18, font=(self.mono_family, 11)
        )
        self.output_text.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self._style_text_widget(self.output_text, background=self.palette["bg_alt"])
        self._configure_transcript_tags()

        moments_shadow = tk.Frame(container, bg=self.palette["shadow"])
        moments_shadow.grid(row=6, column=0, sticky="ew", pady=(0, 16))
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
        self.download_clips_button = ttk.Button(
            moments_header,
            text="⬇ Télécharger extraits",
            command=self.download_clips,
            style="Secondary.TButton",
        )
        self.download_clips_button.grid(row=0, column=2, sticky="e")

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
        download_shadow.grid(row=7, column=0, sticky="ew", pady=(0, 14))
        download_card = tk.Frame(download_shadow, bg=self.palette["card"])
        download_card.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        download_card.grid_columnconfigure(0, weight=1)
        download_header = tk.Frame(download_card, bg=self.palette["card"])
        download_header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 6))
        download_header.grid_columnconfigure(0, weight=1)

        ttk.Label(
            download_header, text="Téléchargements multi-réseaux", style="CardTitle.TLabel"
        ).grid(row=0, column=0, sticky="w")

        download_header_right = tk.Frame(download_header, bg=self.palette["card"])
        download_header_right.grid(row=0, column=1, sticky="e")
        ttk.Label(
            download_header_right,
            textvariable=self.download_summary_var,
            style="CardMuted.TLabel",
        ).grid(row=0, column=0, sticky="e", padx=(0, 10))
        self.download_toggle_button = ttk.Button(
            download_header_right,
            text="Voir les détails techniques",
            command=self.toggle_download_logs,
            style="Link.TButton",
        )
        self.download_toggle_button.grid(row=0, column=1, sticky="e")

        download_actions = tk.Frame(download_card, bg=self.palette["card"])
        download_actions.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(2, 8))
        download_actions.grid_columnconfigure(0, weight=1)
        download_actions.grid_columnconfigure(1, weight=1)

        self.download_full_video_button = ttk.Button(
            download_actions,
            text="⬇ Télécharger la vidéo entière",
            command=self.download_full_video,
            style="Secondary.TButton",
        )
        self.download_full_video_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.download_audio_button = ttk.Button(
            download_actions,
            text="🎵 Télécharger l'audio (MP3)",
            command=self.download_audio_only,
            style="Secondary.TButton",
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

        self.download_overall_progress = ttk.Progressbar(
            download_card,
            mode="determinate",
            maximum=1,
            value=0,
            style="Blue.Horizontal.TProgressbar",
        )
        self.download_overall_progress.grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(4, 4)
        )

        self.download_current_progress = ttk.Progressbar(
            download_card,
            mode="determinate",
            maximum=100,
            value=0,
            style="Blue.Horizontal.TProgressbar",
        )
        self.download_current_progress.grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 8)
        )

        ttk.Label(
            download_card, textvariable=self.download_detail_var, style="CardMuted.TLabel"
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=16)
        ttk.Label(
            download_card, textvariable=self.download_phase_var, style="CardMuted.TLabel"
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 0))

        self.download_log = scrolledtext.ScrolledText(
            download_card, wrap=tk.WORD, height=5, font=(self.mono_family, 9)
        )
        self.download_log.grid(
            row=6, column=0, columnspan=2, sticky="ew", padx=16, pady=(8, 16)
        )
        self.download_log.configure(state="disabled")
        self._style_text_widget(self.download_log, background=self.palette["bg_alt"])
        self.download_log.grid_remove()

        history_header = tk.Frame(download_card, bg=self.palette["card"])
        history_header.grid(row=7, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 6))
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
            row=8, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16)
        )
        self.download_history_text.configure(state="disabled")
        self._style_text_widget(self.download_history_text, background=self.palette["bg_alt"])

        feedback_frame = ttk.Frame(container)
        feedback_frame.grid(row=8, column=0, sticky="ew", pady=(6, 0))
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
                fg="#ffffff",
                font=(self.font_family, 10, "bold"),
                pady=3,
            )
            badge.grid(row=0, column=0, sticky="w")

            if is_top:
                tk.Label(
                    badge_row,
                    text="  ★ Recommandé  ",
                    bg=self.palette["success"],
                    fg="#ffffff",
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
            foreground="#7b8aa8",
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
        logo_position: str = "center",
        logo_size_mode: str = "relative",
        logo_scale_percent: int = 58,
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
                position_label = {"top": "haut", "center": "milieu", "bottom": "bas"}.get(
                    logo_position, "milieu"
                )
                size_label = (
                    "taille originale"
                    if logo_size_mode == "original"
                    else f"{logo_scale_percent}%"
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
            position_label = {"top": "haut", "center": "milieu", "bottom": "bas"}.get(
                logo_position, "milieu"
            )
            size_label = (
                "taille originale"
                if logo_size_mode == "original"
                else f"{logo_scale_percent}%"
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
                "download_subtitles_enabled": subtitles_enabled,
                "download_subtitle_style": subtitle_style,
                "download_video_effect": video_effect,
                "download_preset": download_preset,
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

        selected_position = str(snapshot.get("download_logo_position", "center"))
        selected_position_label = next(
            (
                label
                for label, value in self.download_logo_position_lookup.items()
                if value == selected_position
            ),
            "Milieu",
        )
        self.download_logo_position_var.set(selected_position_label)

        selected_size_mode = str(snapshot.get("download_logo_size_mode", "relative"))
        selected_size_mode_label = next(
            (
                label
                for label, value in self.download_logo_size_mode_lookup.items()
                if value == selected_size_mode
            ),
            "Personnalisée",
        )
        self.download_logo_size_mode_var.set(selected_size_mode_label)

        logo_scale_percent = int(snapshot.get("download_logo_scale_percent", 58))
        self.download_logo_size_var.set(logo_scale_percent)
        self.download_logo_size_label_var.set(f"{logo_scale_percent}%")

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
        self._update_download_logo_controls_state()

    def _on_download_preferences_change(self, *_: object) -> None:
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
        self._update_download_logo_controls_state()
        self._save_gui_settings()

    def _on_download_logo_focus_out(self, _event: tk.Event) -> None:
        self._save_gui_settings()

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
        overall_percent = ((self.download_completed + (percent / 100.0)) / total) * 100.0
        overall_percent = max(0.0, min(100.0, overall_percent))
        self.download_overall_progress.configure(value=overall_percent)
        self.download_current_progress.configure(value=percent)
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
        self.download_overall_progress.configure(value=0, maximum=100)
        self.download_current_progress.configure(value=0, maximum=100)
        self.download_last_percent_logged = -1
        self.download_last_size = ""
        self.download_log.configure(state="normal")
        self.download_log.delete("1.0", tk.END)
        self.download_log.configure(state="disabled")

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
        logo_enabled = self.download_logo_enabled_var.get()
        logo_position = self._selected_download_logo_position()
        subtitles_enabled = (
            bool(self.download_subtitles_enabled_var.get())
            and bool(self.last_transcript_chunks)
        )
        subtitle_style = self._selected_download_subtitle_style()
        video_effect = self._selected_download_video_effect()
        logo_path = ""
        if logo_enabled:
            logo_path = self._validated_download_logo_path()
            if logo_path is None:
                return
            if not logo_path:
                messagebox.showwarning(
                    "Logo manquant",
                    "Sélectionne un logo ou décoche « Intégrer le logo ».",
                )
                return
        logo_scale_percent = self._get_download_logo_scale_percent()
        logo_opacity_percent = self._get_download_logo_opacity_percent()
        self._enqueue_downloads(
            self.last_most_viewed_moments,
            url,
            output_dir,
            duration,
            video_format,
            yt_dlp_cmd,
            shorts_mode=shorts_mode,
            logo_enabled=logo_enabled,
            logo_path=logo_path,
            logo_position=logo_position,
            logo_size_mode=self._selected_download_logo_size_mode(),
            logo_scale_percent=logo_scale_percent,
            logo_opacity_percent=logo_opacity_percent,
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
        logo_enabled = self.download_logo_enabled_var.get()
        logo_position = self._selected_download_logo_position()
        subtitles_enabled = (
            bool(self.download_subtitles_enabled_var.get())
            and bool(self.last_transcript_chunks)
        )
        subtitle_style = self._selected_download_subtitle_style()
        video_effect = self._selected_download_video_effect()
        logo_path = ""
        if logo_enabled:
            logo_path = self._validated_download_logo_path()
            if logo_path is None:
                return
            if not logo_path:
                messagebox.showwarning(
                    "Logo manquant",
                    "Sélectionne un logo ou décoche « Intégrer le logo ».",
                )
                return
        logo_scale_percent = self._get_download_logo_scale_percent()
        logo_opacity_percent = self._get_download_logo_opacity_percent()
        self._enqueue_downloads(
            [moment],
            url,
            output_dir,
            duration,
            video_format,
            yt_dlp_cmd,
            shorts_mode=shorts_mode,
            logo_enabled=logo_enabled,
            logo_path=logo_path,
            logo_position=logo_position,
            logo_size_mode=self._selected_download_logo_size_mode(),
            logo_scale_percent=logo_scale_percent,
            logo_opacity_percent=logo_opacity_percent,
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

        logo_enabled = self.download_logo_enabled_var.get()
        logo_position = self._selected_download_logo_position()
        logo_path = ""
        if logo_enabled:
            logo_path = self._validated_download_logo_path()
            if logo_path is None:
                return
            if not logo_path:
                messagebox.showwarning(
                    "Logo manquant",
                    "Sélectionne un logo ou décoche « Intégrer le logo ».",
                )
                return

        start = int(moment.minute_index * 60)
        duration = min(8, self._get_clip_duration())
        output_dir = tempfile.mkdtemp(prefix="youtube-script-preview-")
        subtitles_enabled = (
            bool(self.download_subtitles_enabled_var.get())
            and bool(self.last_transcript_chunks)
        )
        item = {
            "url": url,
            "output_dir": output_dir,
            "start": start,
            "duration": duration,
            "format": self._get_video_format(),
            "yt_dlp_cmd": yt_dlp_cmd,
            "shorts": self._selected_download_aspect_mode() == "shorts",
            "logo_enabled": logo_enabled,
            "logo_path": logo_path,
            "logo_position": logo_position,
            "logo_size_mode": self._selected_download_logo_size_mode(),
            "logo_scale_percent": self._get_download_logo_scale_percent(),
            "logo_opacity_percent": self._get_download_logo_opacity_percent(),
            "subtitles_enabled": subtitles_enabled,
            "subtitle_style": self._selected_download_subtitle_style(),
            "subtitle_chunks": list(self.last_transcript_chunks)
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
            "-S",
            f"ext:{video_format}",
            "--merge-output-format",
            video_format,
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
            "logo_position": str(item.get("logo_position", "center")),
            "logo_size_mode": str(item.get("logo_size_mode", "relative")),
            "logo_scale_percent": int(item.get("logo_scale_percent", 58)),
            "logo_opacity_percent": int(item.get("logo_opacity_percent", 100)),
        }
        if item.get("subtitles_enabled"):
            variant_kwargs.update(
                {
                    "subtitle_chunks": item.get("subtitle_chunks", []),
                    "subtitle_start": float(item.get("start", 0) or 0),
                    "subtitle_duration": float(item.get("duration", 0) or 0),
                    "subtitle_style": str(item.get("subtitle_style", "impact")),
                }
            )
        video_effect = str(item.get("video_effect", "none"))
        if video_effect != "none":
            variant_kwargs["video_effect"] = video_effect
        variant_kwargs["preview_width"] = 540
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
            "logo_position": "center",
            "logo_size_mode": "relative",
            "logo_scale_percent": 58,
            "logo_opacity_percent": 100,
        }
        creative_options = {
            "subtitles_enabled": False,
            "subtitle_style": "impact",
            "video_effect": "none",
        }
        if not audio_only:
            logo_options = self._selected_full_video_logo_options()
            if logo_options is None:
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
            }
            needs_processing = (
                bool(logo_options.get("logo_enabled") and logo_options.get("logo_path"))
                or bool(creative_options["subtitles_enabled"])
                or creative_options["video_effect"] != "none"
            )
            if needs_processing and self._resolve_system_tool("ffmpeg") is None:
                messagebox.showerror(
                    "Dépendance manquante",
                    "Le binaire 'ffmpeg' est requis pour intégrer un logo, "
                    "des sous-titres ou un effet vidéo.\n"
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
            return [path]
        if importlib.util.find_spec("yt_dlp") is not None:
            return [sys.executable, "-m", "yt_dlp"]
        return None

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

    def _selected_full_video_logo_options(self) -> dict | None:
        logo_enabled_var = getattr(self, "download_logo_enabled_var", None)
        logo_enabled = (
            bool(logo_enabled_var.get())
            if logo_enabled_var is not None and hasattr(logo_enabled_var, "get")
            else False
        )
        logo_path = ""
        logo_position = "center"
        if hasattr(self, "download_logo_position_var") and hasattr(
            self, "download_logo_position_lookup"
        ):
            logo_position = self._selected_download_logo_position()
        logo_scale_percent = (
            self._get_download_logo_scale_percent()
            if hasattr(self, "download_logo_size_var")
            else 58
        )
        logo_opacity_percent = (
            self._get_download_logo_opacity_percent()
            if hasattr(self, "download_logo_opacity_var")
            else 100
        )
        logo_size_mode = (
            self._selected_download_logo_size_mode()
            if hasattr(self, "download_logo_size_mode_var")
            and hasattr(self, "download_logo_size_mode_lookup")
            else "relative"
        )

        if logo_enabled:
            logo_path = self._validated_download_logo_path()
            if logo_path is None:
                return None
            if not logo_path:
                messagebox.showwarning(
                    "Logo manquant",
                    "Sélectionne un logo ou décoche « Ajouter le logo à la vidéo ».",
                )
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

        return {
            "logo_enabled": logo_enabled,
            "logo_path": logo_path,
            "logo_position": logo_position,
            "logo_size_mode": logo_size_mode,
            "logo_scale_percent": logo_scale_percent,
            "logo_opacity_percent": logo_opacity_percent,
        }

    def _on_download_logo_toggle(self) -> None:
        self._update_download_logo_controls_state()

    def _update_download_logo_controls_state(self) -> None:
        enabled_var = getattr(self, "download_logo_enabled_var", None)
        if enabled_var is None:
            return
        enabled = enabled_var.get()
        if getattr(self, "busy", False):
            state = "disabled"
        else:
            state = "normal" if enabled else "disabled"
        combo_state = "readonly" if state != "disabled" else "disabled"
        logo_size_mode = (
            self._selected_download_logo_size_mode()
            if hasattr(self, "download_logo_size_mode_var")
            and hasattr(self, "download_logo_size_mode_lookup")
            else "relative"
        )
        size_state = state if logo_size_mode == "relative" else "disabled"
        widgets = (
            ("download_logo_entry", state),
            ("download_logo_button", state),
            ("download_logo_position_combo", combo_state),
            ("download_logo_size_mode_combo", combo_state),
            ("download_logo_size_scale", size_state),
            ("download_logo_opacity_scale", state),
        )
        for name, widget_state in widgets:
            widget = getattr(self, name, None)
            if widget is not None:
                widget.configure(state=widget_state)

    def _on_logo_size_change(self, value: str) -> None:
        try:
            percent = int(round(float(value)))
        except (TypeError, ValueError):
            percent = self._get_download_logo_scale_percent()
        percent = max(20, min(80, percent))
        self.download_logo_size_var.set(percent)
        self.download_logo_size_label_var.set(f"{percent}%")

    def _get_download_logo_scale_percent(self) -> int:
        try:
            value = int(round(float(self.download_logo_size_var.get())))
        except (TypeError, ValueError):
            return 58
        return max(20, min(80, value))

    def _selected_download_logo_size_mode(self) -> str:
        label = self.download_logo_size_mode_var.get()
        mode = self.download_logo_size_mode_lookup.get(label, "relative")
        return mode if mode in {"original", "relative"} else "relative"

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

    def _selected_download_logo_position(self) -> str:
        label = self.download_logo_position_var.get()
        return self.download_logo_position_lookup.get(label, "center")

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
        subtitles_enabled: bool = False,
        subtitle_style: str = "impact",
        video_effect: str = "none",
    ) -> None:
        transcript_chunks = (
            list(getattr(self, "last_transcript_chunks", []))
            if subtitles_enabled
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
                    "subtitles_enabled": bool(transcript_chunks),
                    "subtitle_style": subtitle_style,
                    "subtitle_chunks": transcript_chunks,
                    "video_effect": video_effect,
                    "clip_label": clip_label,
                    "video_title": cached_title,
                }
            )

        if self.download_active:
            # Include current clip already in progress when extending the queue.
            self.download_total = self.download_completed + len(self.download_queue) + 1
            total_safe = max(1, self.download_total)
            overall_percent = (self.download_completed / total_safe) * 100.0
            self.download_overall_progress.configure(maximum=100, value=overall_percent)
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
        logo_position: str = "center",
        logo_size_mode: str = "relative",
        logo_scale_percent: int = 58,
        logo_opacity_percent: int = 100,
        subtitles_enabled: bool = False,
        subtitle_style: str = "impact",
        video_effect: str = "none",
    ) -> None:
        normalized_kind = kind if kind in {"full_video", "audio"} else "full_video"
        item_format = "mp3" if normalized_kind == "audio" else video_format
        media_logo_enabled = normalized_kind == "full_video" and logo_enabled and bool(logo_path)
        media_subtitles_enabled = (
            normalized_kind == "full_video"
            and subtitles_enabled
            and bool(getattr(self, "last_transcript_chunks", []))
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
                "shorts": False,
                "logo_enabled": media_logo_enabled,
                "logo_path": logo_path if media_logo_enabled else "",
                "logo_position": logo_position,
                "logo_size_mode": logo_size_mode,
                "logo_scale_percent": logo_scale_percent,
                "logo_opacity_percent": logo_opacity_percent,
                "subtitles_enabled": media_subtitles_enabled,
                "subtitle_style": subtitle_style,
                "subtitle_chunks": list(getattr(self, "last_transcript_chunks", []))
                if media_subtitles_enabled
                else [],
                "video_effect": video_effect if normalized_kind == "full_video" else "none",
                "video_title": cached_title,
            }
        )

        if self.download_active:
            self.download_total = self.download_completed + len(self.download_queue) + 1
            total_safe = max(1, self.download_total)
            overall_percent = (self.download_completed / total_safe) * 100.0
            self.download_overall_progress.configure(maximum=100, value=overall_percent)
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

    def _download_worker(self) -> None:
        errors: List[str] = []
        try:
            while self.download_queue and not self.download_cancel.is_set():
                item = self.download_queue.pop(0)
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
                    item.get("logo_position", "center"),
                    item.get("logo_size_mode", "relative"),
                    item.get("logo_scale_percent", 58),
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
            return False, "Le téléchargement a échoué."

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
        item["shorts"] = False
        if media_kind == "full_video":
            try:
                variant_kwargs = {
                    "to_shorts": False,
                    "logo_path": item.get("logo_path", "")
                    if item.get("logo_enabled")
                    else "",
                    "logo_position": str(item.get("logo_position", "center")),
                    "logo_size_mode": str(item.get("logo_size_mode", "relative")),
                    "logo_scale_percent": int(item.get("logo_scale_percent", 58)),
                    "logo_opacity_percent": int(item.get("logo_opacity_percent", 100)),
                }
                if item.get("subtitles_enabled"):
                    variant_kwargs.update(
                        {
                            "subtitle_chunks": item.get("subtitle_chunks", []),
                            "subtitle_start": 0.0,
                            "subtitle_duration": None,
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
            "-S",
            f"ext:{video_format}",
            "--merge-output-format",
            video_format,
            "--paths",
            item["output_dir"],
            "-o",
            output_template,
            item["url"],
        ]
        saw_progress = False
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
            return False, "Le téléchargement a échoué."

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
                "logo_position": str(item.get("logo_position", "center")),
                "logo_size_mode": str(item.get("logo_size_mode", "relative")),
                "logo_scale_percent": int(item.get("logo_scale_percent", 58)),
                "logo_opacity_percent": int(item.get("logo_opacity_percent", 100)),
            }
            if item.get("subtitles_enabled"):
                variant_kwargs.update(
                    {
                        "subtitle_chunks": item.get("subtitle_chunks", []),
                        "subtitle_start": float(item.get("start", 0) or 0),
                        "subtitle_duration": float(item.get("duration", 0) or 0),
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
        video_effect: str = "none",
        subtitle_style: str = "impact",
    ) -> str:
        return download_utils.download_variant_suffix(
            to_shorts,
            has_logo,
            has_subtitles=has_subtitles,
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
        video_effect: str = "none",
        subtitle_style: str = "impact",
    ) -> Path:
        return download_utils.download_variant_output_path(
            input_path,
            to_shorts,
            has_logo,
            has_subtitles=has_subtitles,
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
            if path.is_file()
        ]
        if not candidates:
            return None
        new_files = [
            path for path in candidates if str(path.resolve()) not in existing_files
        ]
        pool = new_files or candidates
        return max(pool, key=lambda path: path.stat().st_mtime)

    def _build_download_variant(
        self,
        input_path: Path,
        *,
        to_shorts: bool,
        logo_path: str,
        logo_position: str = "center",
        logo_size_mode: str = "relative",
        logo_scale_percent: int = 58,
        logo_opacity_percent: int = 100,
        subtitle_chunks: List[dict] | None = None,
        subtitle_start: float = 0.0,
        subtitle_duration: float | None = None,
        subtitle_style: str = "impact",
        video_effect: str = "none",
        preview_width: int | None = None,
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
            subtitle_chunks=subtitle_chunks,
            subtitle_start=subtitle_start,
            subtitle_duration=subtitle_duration,
            subtitle_style=subtitle_style,
            video_effect=video_effect,
            preview_width=preview_width,
        )
        return video_renderer.render_video_variant(options, runner=subprocess.run)

    @staticmethod
    def _logo_overlay_y_expr(position: str, margin: int = 36) -> str:
        return download_utils.logo_overlay_y_expr(position, margin)

    @staticmethod
    def _logo_opacity_ratio(percent: int) -> float:
        return download_utils.logo_opacity_ratio(percent)

    def _start_download_ui(self, total: int) -> None:
        self._set_busy_state(True)
        self._reset_download_ui()
        self.download_overall_progress.configure(maximum=100, value=0)
        self.download_current_progress.configure(maximum=100, value=0)
        self.download_summary_var.set(f"Téléchargement 0/{total} • 0%")
        self.download_detail_var.set("Préparation du téléchargement…")
        self._set_download_phase("initialisation de la file")
        self.status_var.set("Téléchargement en cours…")
        self._append_download_log("Démarrage du téléchargement.")

    def _update_download_ui(self, completed: int, total: int) -> None:
        total_safe = max(1, total)
        overall_percent = (completed / total_safe) * 100.0
        self.download_overall_progress.configure(maximum=100, value=overall_percent)
        self.download_current_progress.configure(value=0)
        self.download_detail_var.set(f"Global {overall_percent:.1f}%")
        if completed >= total:
            self.download_summary_var.set(
                f"Téléchargement terminé ({completed}/{total}) • 100%"
            )
            self._set_download_phase("tous les clips sont traités")
        else:
            self.download_summary_var.set(
                f"Téléchargement {completed}/{total} • {overall_percent:.1f}%"
            )
            self._set_download_phase("préparation du clip suivant")

    def _finish_download_ui(self, success: bool, message: str, cancelled: bool) -> None:
        if cancelled:
            self._set_status("Téléchargement annulé.", busy=False)
            self.download_detail_var.set("Téléchargement annulé.")
            self._set_download_phase("annulé par l'utilisateur")
            self._append_download_log("Téléchargement annulé.")
            return
        if success:
            self._set_status(
                "Extraction terminée avec succès ✓", busy=False, success=True
            )
            self.download_detail_var.set("✔ Téléchargement terminé · 📁 Fichier prêt")
            self._set_download_phase("terminé")
            self._append_download_log("Téléchargements terminés.")
        else:
            self._set_status("Erreur lors du téléchargement.", busy=False, error=True)
            self.download_detail_var.set("Erreur lors du téléchargement.")
            self._set_download_phase("échec")
            if message:
                messagebox.showerror("Téléchargement impossible", message)

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
            self.style.configure("Status.TLabel", foreground="#b91c1c")
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
        self._update_download_logo_controls_state()
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
