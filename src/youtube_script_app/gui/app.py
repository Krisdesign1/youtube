"""Main application class: TranscriptApp and entry point."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import List

from ..base import OUTPUT_FORMATS
from ..downloads import utils as download_utils
from ..core import lower_third
from ..video import presets as video_presets
from ..settings import load_gui_settings

from .theme import THEME, DARK_THEME
from .widgets.progress import _CanvasProgress
from .mixins.layout import LayoutMixin
from .mixins.options import OptionsMixin
from .mixins.theme_mixin import ThemeMixin
from .mixins.download import DownloadMixin
from .mixins.history_mixin import HistoryMixin
from .mixins.logo import LogoMixin
from .mixins.transcript import TranscriptMixin
from .mixins.utils import UtilsMixin


class TranscriptApp(
    LayoutMixin,
    OptionsMixin,
    ThemeMixin,
    DownloadMixin,
    HistoryMixin,
    LogoMixin,
    TranscriptMixin,
    UtilsMixin,
):
    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        master.title("Générateur de script YouTube")
        master.minsize(900, 600)
        master.resizable(True, True)

        self._dark_mode: bool = False
        self.palette: dict = dict(THEME)

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
        self.download_logo_size_var = tk.IntVar(value=download_utils.DEFAULT_LOGO_SCALE_PERCENT)
        self.download_logo_size_label_var = tk.StringVar(
            value=self._download_logo_size_label(download_utils.DEFAULT_LOGO_SCALE_PERCENT)
        )
        self.download_logo_width_ratio_var = tk.DoubleVar(value=download_utils.DEFAULT_LOGO_WIDTH_RATIO)
        self.download_logo_x_ratio_var = tk.DoubleVar(value=download_utils.DEFAULT_LOGO_X_RATIO)
        self.download_logo_y_ratio_var = tk.DoubleVar(value=download_utils.DEFAULT_LOGO_Y_RATIO)
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
        self.download_lower_third_bg_color_var = tk.StringVar(value=lower_third.DEFAULT_BG_COLOR)
        self.download_lower_third_accent_color_var = tk.StringVar(value=lower_third.DEFAULT_ACCENT_COLOR)
        self.download_lower_third_interval_var = tk.IntVar(value=lower_third.DEFAULT_DISPLAY_INTERVAL_SECONDS)
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
        self.download_summary_var = tk.StringVar(value="Aucun téléchargement en cours.")
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
        self.download_queue_lock = threading.Lock()
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
        self.url_var.trace_add("write", lambda *args: self.master.after_idle(self._update_generate_state))
        self.download_aspect_ratio_var.trace_add("write", self._on_download_aspect_change)
        self.download_preset_var.trace_add("write", self._on_download_preset_change)
        self.video_format_var.trace_add("write", self._on_download_preferences_change)
        self.clip_duration_var.trace_add("write", self._on_download_preferences_change)
        self.download_logo_enabled_var.trace_add("write", self._on_download_preferences_change)
        self.download_logo_position_var.trace_add("write", self._on_download_logo_position_change)
        self.download_logo_size_mode_var.trace_add("write", self._on_download_logo_size_mode_change)
        self.download_logo_size_var.trace_add("write", self._on_download_preferences_change)
        self.download_logo_width_ratio_var.trace_add("write", self._on_download_preferences_change)
        self.download_logo_x_ratio_var.trace_add("write", self._on_download_preferences_change)
        self.download_logo_y_ratio_var.trace_add("write", self._on_download_preferences_change)
        self.download_logo_opacity_var.trace_add("write", self._on_download_preferences_change)
        self.download_subtitles_enabled_var.trace_add("write", self._on_download_preferences_change)
        self.download_subtitle_style_var.trace_add("write", self._on_download_preferences_change)
        self.download_video_effect_var.trace_add("write", self._on_download_preferences_change)
        self.download_intro_outro_enabled_var.trace_add("write", self._on_value_add_change)
        self.download_progress_bar_enabled_var.trace_add("write", self._on_value_add_change)
        self.download_animated_watermark_enabled_var.trace_add("write", self._on_value_add_change)
        self.download_lower_third_enabled_var.trace_add("write", self._on_lower_third_change)
        self.download_lower_third_position_var.trace_add("write", self._on_lower_third_change)
        self.download_lower_third_name_var.trace_add("write", self._on_download_preferences_change)
        self.download_lower_third_name_var.trace_add("write", lambda *_: self._redraw_lower_third_preview())
        self.download_lower_third_tagline_var.trace_add("write", self._on_download_preferences_change)
        self.download_lower_third_tagline_var.trace_add("write", lambda *_: self._redraw_lower_third_preview())
        self.download_lower_third_subscribe_var.trace_add("write", self._on_download_preferences_change)
        self.download_lower_third_subscribe_var.trace_add("write", lambda *_: self._redraw_lower_third_preview())
        self.download_lower_third_bg_color_var.trace_add("write", self._on_lower_third_color_change)
        self.download_lower_third_accent_color_var.trace_add("write", self._on_lower_third_color_change)
        self.download_lower_third_interval_var.trace_add("write", self._on_lower_third_timing_change)
        self.download_lower_third_display_duration_var.trace_add("write", self._on_lower_third_timing_change)
        self.download_lower_third_title_scale_var.trace_add("write", self._on_lower_third_preview_change)
        self.download_lower_third_tagline_scale_var.trace_add("write", self._on_lower_third_preview_change)
        self.download_lower_third_subscribe_text_var.trace_add("write", self._on_lower_third_preview_change)
        self.download_lower_third_bg_opacity_var.trace_add("write", self._on_lower_third_preview_change)
        self.download_lower_third_valign_var.trace_add("write", self._on_lower_third_preview_change)
        self.download_logo_entry.bind("<FocusOut>", self._on_download_logo_focus_out, add="+")

        for _var_name in (
            "download_logo_enabled_var",
            "download_logo_position_var",
            "download_subtitles_enabled_var",
            "download_subtitle_style_var",
            "download_lower_third_enabled_var",
            "download_lower_third_position_var",
            "download_progress_bar_enabled_var",
            "download_aspect_ratio_var",
        ):
            _var = getattr(self, _var_name, None)
            if _var is not None:
                _var.trace_add("write", self._refresh_video_mockup)

        self._update_generate_state()
        self._update_config_summary()
        self._bind_shortcuts()


def main() -> None:
    root = tk.Tk()
    TranscriptApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
