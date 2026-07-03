"""Download mixin: enqueue, worker, clip/media download, progress, UI state."""

from __future__ import annotations

import copy
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import ttk
from typing import List

from ..constants import (
    LOGGER,
    COMMON_TOOL_DIRS,
    DOWNLOAD_PROGRESS_RE,
    DOWNLOAD_DEST_RE,
    DOWNLOAD_MERGER_RE,
    DOWNLOAD_ALREADY_RE,
    _diagnose_ytdlp_error,
)
from ...downloads import utils as download_utils
from ...core import lower_third, subtitle_renderer
from ...base import seconds_to_timestamp, VideoIdExtractionError
from ...video import renderer as video_renderer
from ...video import presets as video_presets


class DownloadMixin:

    # ------------------------------------------------------------------ #
    # Download log UI helpers
    # ------------------------------------------------------------------ #

    def _append_download_log(self, line: str) -> None:
        if not line:
            return
        self.download_log.configure(state="normal")
        self.download_log.insert(tk.END, f"{line}\n")
        try:
            if int(float(self.download_log.index("end-1c").split(".")[0])) > 200:
                self.download_log.delete("1.0", "2.0")
        except (ValueError, IndexError):
            pass
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

    # ------------------------------------------------------------------ #
    # Download progress tracking
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Download UI lifecycle
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Public download entry points
    # ------------------------------------------------------------------ #

    def download_full_video(self) -> None:
        self._download_full_media(audio_only=False)

    def download_audio_only(self) -> None:
        self._download_full_media(audio_only=True)

    def _download_full_media(self, *, audio_only: bool) -> None:
        import importlib.util as _ilu
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

    def download_custom_clip(self, start: float, end: float) -> None:
        """Download a manually-selected clip between start and end seconds."""
        from types import SimpleNamespace
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

        duration = max(1, int(round(end - start)))
        start_ts = seconds_to_timestamp(int(start))
        end_ts = seconds_to_timestamp(int(start) + duration)
        moment = SimpleNamespace(
            minute_index=start / 60,
            excerpt=f"{start_ts} → {end_ts}",
            score=0,
        )
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
            lower_third_interval=self._get_download_lower_third_interval(),
            lower_third_display_duration=self._get_download_lower_third_display_duration(),
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
        old_preview_dir = getattr(self, "_preview_tmpdir", None)
        if old_preview_dir and os.path.isdir(old_preview_dir):
            shutil.rmtree(old_preview_dir, ignore_errors=True)
        output_dir = tempfile.mkdtemp(prefix="youtube-script-preview-")
        self._preview_tmpdir = output_dir
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
        output_dir: str = item.get("output_dir", "")
        try:
            final_path = self._render_preview_clip(item)
        except RuntimeError as error:
            if output_dir and os.path.isdir(output_dir):
                shutil.rmtree(output_dir, ignore_errors=True)
            if self._should_ignore_result(job_id):
                return
            self.master.after(0, self._finish_preview_ui, False, str(error), None)
            return
        finally:
            self.preview_thread = None

        if self._should_ignore_result(job_id):
            if output_dir and os.path.isdir(output_dir):
                shutil.rmtree(output_dir, ignore_errors=True)
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
            if self.download_process.stderr is None:
                raise RuntimeError("Impossible d'ouvrir le flux stderr du processus.")

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

    # ------------------------------------------------------------------ #
    # yt-dlp / ffmpeg resolution
    # ------------------------------------------------------------------ #

    def _resolve_yt_dlp_cmd(self) -> List[str] | None:
        import importlib.util as _ilu
        path = self._resolve_system_tool("yt-dlp")
        if path:
            cmd = [path]
        elif _ilu.find_spec("yt_dlp") is not None and not getattr(sys, "frozen", False):
            # sys.executable points to the frozen .exe in PyInstaller — unusable as a Python runner
            cmd = [sys.executable, "-m", "yt_dlp"]
        else:
            return None
        cmd += ["--no-update"]
        browser = self._selected_cookies_browser()
        if browser:
            cmd += ["--cookies-from-browser", browser]
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
            candidates = [Path(directory) / executable]
            if sys.platform == "win32" and not executable.lower().endswith(".exe"):
                candidates.append(Path(directory) / (executable + ".exe"))
            for candidate in candidates:
                if candidate.is_file() and (
                    sys.platform == "win32" or os.access(candidate, os.X_OK)
                ):
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

    # ------------------------------------------------------------------ #
    # Queue management
    # ------------------------------------------------------------------ #

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
        lower_third_config=None,
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
        new_items = []
        for moment in moments:
            start = moment.minute_index * 60
            clip_label = self._build_moment_filename_label(moment)
            title_cache = getattr(self, "video_title_cache", {})
            cached_title = ""
            if isinstance(title_cache, dict):
                cached_title = str(title_cache.get(url, "")).strip()
            new_items.append(
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
        with self.download_queue_lock:
            self.download_queue.extend(new_items)
            queue_len = len(self.download_queue)
            already_active = self.download_active

        if already_active:
            self.download_total = self.download_completed + queue_len + 1
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
        self.download_total = queue_len
        self._start_download_ui(self.download_total)
        with self.download_queue_lock:
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
        lower_third_config=None,
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

        new_item = {
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
        with self.download_queue_lock:
            self.download_queue.append(new_item)
            queue_len = len(self.download_queue)
            already_active = self.download_active

        if already_active:
            self.download_total = self.download_completed + queue_len + 1
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
        self.download_total = queue_len
        self._start_download_ui(self.download_total)
        with self.download_queue_lock:
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
            while not self.download_cancel.is_set():
                with self.download_queue_lock:
                    if not self.download_queue:
                        break
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
            with self.download_queue_lock:
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
            if self.download_process.stderr is None:
                raise RuntimeError("Impossible d'ouvrir le flux stderr du processus.")

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
            if self.download_process.stderr is None:
                raise RuntimeError("Impossible d'ouvrir le flux stderr du processus.")

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
        lower_third_config=None,
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
            self.master.after(0, lambda: self.download_current_progress.configure(value=0))
            self.master.after(0, self._set_download_phase, "rendu ffmpeg…")

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

    # ------------------------------------------------------------------ #
    # cancel() - defined here for download logic; also in utils.py cancel
    # ------------------------------------------------------------------ #

    def cancel(self) -> None:
        if not self.busy:
            return
        if self.download_active:
            self.download_cancel.set()
            if self.download_process and self.download_process.poll() is None:
                self.download_process.terminate()
            with self.download_queue_lock:
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
