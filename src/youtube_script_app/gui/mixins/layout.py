"""Layout mixin: main canvas, scrolling, hero header, and full widget tree construction."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, scrolledtext

from ..constants import LOGGER
from ..widgets.progress import _CanvasProgress
from ...core import lower_third
from ...settings import DOWNLOAD_LOGO_PLACEHOLDER


class LayoutMixin:
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
        self.manual_cut_button = self._button(
            transcript_header,
            text="✂ Couper",
            command=self._open_manual_cut_dialog,
            variant="secondary",
        )
        self.manual_cut_button.grid(row=0, column=1, sticky="e", padx=(0, 8))

        self.copy_button = self._button(
            transcript_header,
            text="Copier",
            command=self.copy_to_clipboard,
            variant="tertiary",
        )
        self.copy_button.grid(row=0, column=2, sticky="e")

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
