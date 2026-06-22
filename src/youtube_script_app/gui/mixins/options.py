"""Options panel mixin: toggle, badge, config summary, and preference change handlers."""

from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from tkinter import colorchooser, messagebox

from PIL import Image, ImageTk

from ..constants import LOGGER
from ...core import lower_third


class OptionsMixin:
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

    def _fetch_lower_third_from_url(self) -> None:
        url = self.last_url or self._get_entry_value(self.url_entry)
        if not url:
            messagebox.showwarning("Aucune URL", "Ajoute d'abord une URL vidéo.")
            return
        yt_dlp_cmd = self._resolve_yt_dlp_cmd()
        if not yt_dlp_cmd:
            messagebox.showerror(
                "yt-dlp manquant",
                "yt-dlp est requis pour récupérer les métadonnées.",
            )
            return
        btn = getattr(self, "download_lower_third_fetch_button", None)
        if btn:
            btn.configure(state="disabled", text="…")

        def _do_fetch() -> None:
            cmd = [
                *yt_dlp_cmd,
                "--no-playlist",
                "--skip-download",
                "--print",
                "%(channel)s",
                "--print",
                "%(title)s",
                url,
            ]
            try:
                result = subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=25,
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
            hold_var = getattr(self, "download_intro_outro_hold_var", None)
            hold = max(0.5, float(hold_var.get() if hold_var is not None else 1.5))
        except (TypeError, ValueError, tk.TclError):
            hold = 1.5
        bg_var = getattr(self, "download_intro_outro_bg_color_var", None)
        text_var = getattr(self, "download_intro_outro_text_color_var", None)
        bg_hex = str(bg_var.get() if bg_var is not None else "#000000")
        text_hex = str(text_var.get() if text_var is not None else "#FFFFFF")
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

        sub_text_entry = getattr(self, "download_lower_third_subscribe_text_entry", None)
        if sub_text_entry is not None and visible and not getattr(self, "busy", False):
            sub_on = bool(
                self.download_lower_third_subscribe_var.get()
                if hasattr(self, "download_lower_third_subscribe_var")
                else True
            )
            sub_text_entry.configure(state="normal" if sub_on else "disabled")

        valign_row = getattr(self, "_lt_valign_row", None)
        if valign_row is not None:
            pos_label = (
                self.download_lower_third_position_var.get()
                if hasattr(self, "download_lower_third_position_var")
                else ""
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
        bg_opacity = (
            self.download_lower_third_bg_opacity_var.get()
            if hasattr(self, "download_lower_third_bg_opacity_var")
            else 86
        )
        title_scale = (
            self.download_lower_third_title_scale_var.get()
            if hasattr(self, "download_lower_third_title_scale_var")
            else 100
        ) / 100.0
        tagline_scale = (
            self.download_lower_third_tagline_scale_var.get()
            if hasattr(self, "download_lower_third_tagline_scale_var")
            else 100
        ) / 100.0
        subscribe_text = (
            self.download_lower_third_subscribe_text_var.get().strip()
            if hasattr(self, "download_lower_third_subscribe_text_var")
            else ""
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
            bg_alpha=int(bg_opacity * 2.55),
            title_scale=title_scale,
            tagline_scale=tagline_scale,
            subscribe_text=subscribe_text,
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
            cw = canvas.winfo_width()
            ch = canvas.winfo_height()
            if cw < 2 or ch < 2:
                cw = int(canvas.cget("width"))
                ch = int(canvas.cget("height"))
            cw = max(1, cw)
            ch = max(1, ch)
            canvas.delete("all")
        except tk.TclError:
            return

        canvas.create_rectangle(
            1,
            1,
            cw - 2,
            ch - 2,
            fill=self.palette["bg_alt"],
            outline=self.palette["shadow"],
        )

        position = self._selected_lower_third_position()
        is_portrait = position == "top-center"
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
                cw // 2,
                ch // 2,
                text="Erreur aperçu",
                fill=self.palette["danger"],
                font=(self.font_family, 8),
            )
            return

        if is_portrait:
            scale = ch / vh
            fg_h_virt = int(vw * 9 / 16)
            pb_h_virt = (vh - fg_h_virt) // 2
            pb_canvas = int(pb_h_virt * scale)
            fg_canvas = int(fg_h_virt * scale)

            canvas.create_rectangle(1, 1, cw - 2, ch - 2, fill="#555555")
            canvas.create_rectangle(
                1,
                pb_canvas,
                cw - 2,
                pb_canvas + fg_canvas,
                fill="#6a5040",
            )
            canvas.create_line(cw // 3, 1, cw // 3, pb_canvas - 1, fill="#666666")
            canvas.create_line(2 * cw // 3, 1, 2 * cw // 3, pb_canvas - 1, fill="#666666")

            valign = self._selected_lower_third_valign()
            band_h_virt = lower_third.lower_third_band_height(cfg, vh)
            if valign == "bottom":
                y_off_virt = max(0, pb_h_virt - band_h_virt)
            elif valign == "center":
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
                LOGGER.debug("Lower third preview render failed", exc_info=True)
        else:
            try:
                resized = lt_img.resize((cw, ch), Image.LANCZOS)
                self._lt_preview_tk = ImageTk.PhotoImage(resized)
                canvas.create_image(0, 0, anchor="nw", image=self._lt_preview_tk)
            except Exception:
                LOGGER.debug("Lower third preview render failed", exc_info=True)

    def _on_download_aspect_change(self, *_: object) -> None:
        self._redraw_logo_preview()
        self._refresh_video_mockup()
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
        from ...downloads import utils as download_utils
        width_ratio = self._get_download_logo_width_ratio()
        x_ratio, y_ratio = download_utils.logo_position_to_ratios(
            self._selected_download_logo_position(),
            width_ratio,
        )
        self.download_logo_x_ratio_var.set(x_ratio)
        self.download_logo_y_ratio_var.set(y_ratio)
        self._redraw_logo_preview()
        self._refresh_video_mockup()
        self._save_gui_settings()

    def _on_download_preset_change(self, *_: object) -> None:
        from ...video import presets as video_presets
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

    def _refresh_video_mockup(self, *_: object) -> None:
        mockup = (
            getattr(self, "download_video_mockup", None)
            or getattr(self, "download_video_mockup_canvas", None)
            or getattr(self, "video_mockup_canvas", None)
        )
        if mockup is None or not hasattr(mockup, "refresh"):
            return
        options = {
            "aspect": (
                self._selected_download_aspect_mode()
                if hasattr(self, "download_aspect_ratio_var")
                else "landscape"
            ),
            "progress_bar": self._progress_bar_enabled(),
            "lower_third": self._download_lower_third_enabled(),
            "lower_third_pos": (
                self.download_lower_third_position_var.get()
                if hasattr(self, "download_lower_third_position_var")
                else "Bas"
            ),
            "subtitles": bool(
                self.download_subtitles_enabled_var.get()
                if hasattr(self, "download_subtitles_enabled_var")
                else False
            ),
            "subtitle_style": (
                self._selected_download_subtitle_style()
                if hasattr(self, "download_subtitle_style_var")
                else "word"
            ),
            "logo": bool(
                self.download_logo_enabled_var.get()
                if hasattr(self, "download_logo_enabled_var")
                else False
            ),
            "logo_pos": (
                self.download_logo_position_var.get()
                if hasattr(self, "download_logo_position_var")
                else "Haut droit"
            ),
        }
        mockup.refresh(options)

    def _on_download_logo_focus_out(self, _event) -> None:
        self._save_gui_settings()
