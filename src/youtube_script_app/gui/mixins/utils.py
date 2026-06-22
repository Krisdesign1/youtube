"""Utility mixin: entry helpers, status, stats, shortcuts, settings accessors."""

from __future__ import annotations

import copy
import json
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
from typing import List, Optional

from ..constants import LOGGER
from ...base import (
    OUTPUT_FORMATS,
    VideoIdExtractionError,
    extract_video_id,
    export_most_viewed_csv,
    format_most_viewed_moments,
    generate_transcript_with_format,
    TranscriptRetrievalError,
    seconds_to_timestamp,
)
from ...settings import (
    coerce_bool,
    default_gui_settings,
    load_gui_settings,
    normalize_gui_settings,
    save_gui_settings,
    DOWNLOAD_LOGO_PLACEHOLDER,
)
from ...downloads import utils as download_utils
from ...core import subtitle_renderer
from ...video import presets as video_presets


class UtilsMixin:
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

    @staticmethod
    def _parse_languages(raw: str) -> Optional[List[str]]:
        langs = [part.strip() for part in raw.split(",") if part.strip()]
        return langs or None

    def _update_stats(self, content: str) -> None:
        lines = content.splitlines() if content else []
        chars = len(content)
        self.stats_var.set(f"Lignes: {len(lines)} | Caractères: {chars}")

    def _append_output(self, message: str) -> None:
        if self.output_text.get("1.0", tk.END).strip():
            self.output_text.insert(tk.END, "\n")
        self.output_text.insert(tk.END, message)
        self._update_stats(self.output_text.get("1.0", tk.END).strip())

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

    # --- Settings accessors ---------------------------------------------------

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

    def _get_subtitle_offset_ms(self) -> int:
        var = getattr(self, "download_subtitle_offset_var", None)
        try:
            return int(var.get()) if var is not None else 0
        except (TypeError, ValueError, AttributeError):
            return 0

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
        from ...core import lower_third

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
