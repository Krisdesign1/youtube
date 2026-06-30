"""Logo mixin: logo selection, configuration, preview and drag interactions."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image, ImageTk

from ...downloads import utils as download_utils
from ...video import renderer as video_renderer
from ...video.logo_config import LogoConfig


class LogoMixin:
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
            messagebox.showerror("Logo introuvable", f"Le fichier logo est introuvable:\n{logo_path}")
            return None
        return str(logo_path)

    def _build_logo_config(self) -> LogoConfig | None:
        enabled_var = getattr(self, "download_logo_enabled_var", None)
        enabled = bool(enabled_var.get()) if enabled_var is not None and hasattr(enabled_var, "get") else False
        if not enabled:
            return None

        logo_path = self._current_download_logo_path()
        if not logo_path:
            messagebox.showwarning("Logo manquant", "Sélectionne un logo ou décoche « Intégrer le logo ».")
            return None

        try:
            return LogoConfig.from_gui_state({
                "logo_path": logo_path,
                "logo_position": self._selected_download_logo_position(),
                "logo_size_mode": self._selected_download_logo_size_mode(),
                "logo_size": self._get_download_logo_scale_percent(),
                "logo_opacity": self._get_download_logo_opacity_percent(),
                "download_logo_x_ratio": self._get_download_logo_x_ratio(),
                "download_logo_y_ratio": self._get_download_logo_y_ratio(),
            })
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
            "shorts_blur_bg": bool(
                getattr(self, "download_shorts_blur_var", None)
                and self.download_shorts_blur_var.get()
            ),
            "logo_width_ratio": self._get_download_logo_width_ratio(),
            "logo_x_ratio": self._get_download_logo_x_ratio(),
            "logo_y_ratio": self._get_download_logo_y_ratio(),
            "logo_original_width": config.original_width,
            "logo_original_height": config.original_height,
        }

    def _selected_download_logo_options(self) -> dict | None:
        enabled_var = getattr(self, "download_logo_enabled_var", None)
        logo_enabled = bool(enabled_var.get()) if enabled_var is not None and hasattr(enabled_var, "get") else False
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
            "shorts_blur_bg": bool(
                getattr(self, "download_shorts_blur_var", None)
                and self.download_shorts_blur_var.get()
            ),
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
        fixed_logo_combo_state = "readonly" if fixed_logo_state != "disabled" else "disabled"
        if fixed_logo_state != "disabled" and self._selected_download_logo_size_mode() == "original":
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
            if hasattr(self, "download_logo_position_var") and hasattr(self, "download_logo_position_lookup")
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
                    selected_position, previous_width_ratio, previous_x_ratio, previous_y_ratio,
                )
            ):
                logo_x_ratio, logo_y_ratio = download_utils.logo_position_to_ratios(
                    selected_position, new_width_ratio,
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
            else download_utils.logo_scale_percent_to_width_ratio(self._get_download_logo_scale_percent())
        )
        return download_utils.normalize_logo_width_ratio(value)

    def _get_download_logo_x_ratio(self) -> float:
        value = (
            self.download_logo_x_ratio_var.get()
            if hasattr(self, "download_logo_x_ratio_var")
            else download_utils.DEFAULT_LOGO_X_RATIO
        )
        return download_utils.normalize_logo_x_ratio(value, self._get_download_logo_width_ratio())

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

    def _selected_download_logo_position(self) -> str:
        label = self.download_logo_position_var.get()
        return download_utils.normalize_logo_position(
            self.download_logo_position_lookup.get(label, download_utils.DEFAULT_LOGO_POSITION)
        )

    def _logo_preview_canvas_size(self) -> tuple[int, int]:
        aspect_mode = (
            self._selected_download_aspect_mode()
            if hasattr(self, "download_aspect_ratio_var") and hasattr(self, "download_aspect_ratio_lookup")
            else "landscape"
        )
        return (158, 280) if aspect_mode == "shorts" else (280, 158)

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
                mode, self._get_download_logo_scale_percent(),
                target_width, video_format, original_logo_width=source_size[0],
            )
            return max(0.01, min(0.30, logo_width_px / target_width))
        base_width_ratio = self._get_download_logo_width_ratio()
        return download_utils.effective_logo_width_ratio(base_width_ratio, portrait=portrait_preview)

    def _logo_preview_bounds(self, width: int, height: int) -> tuple[int, int, int, int]:
        portrait_preview = height > width
        width_ratio = self._logo_preview_width_ratio(portrait_preview)
        base_width_ratio = self._get_download_logo_width_ratio()
        x_ratio = self._get_download_logo_x_ratio()
        y_ratio = self._get_download_logo_y_ratio()
        selected_position = (
            self._selected_download_logo_position()
            if hasattr(self, "download_logo_position_var") and hasattr(self, "download_logo_position_lookup")
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
        if download_utils.logo_ratios_match_position(selected_position, base_width_ratio, x_ratio, y_ratio):
            x, y = video_renderer.resolve_logo_position(
                selected_position, 0.0, 0.0, width, height, logo_width, logo_height,
            )
        else:
            x_ratio = download_utils.normalize_logo_x_ratio(x_ratio, width_ratio)
            y_ratio = download_utils.normalize_logo_y_ratio(y_ratio)
            x, y = video_renderer.resolve_logo_position(
                "custom", x_ratio, y_ratio, width, height, logo_width, logo_height,
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
        enabled = bool(enabled_var.get()) if enabled_var is not None and hasattr(enabled_var, "get") else True
        frame_fill = self.palette["bg_alt"]
        border = self.palette["shadow"]
        canvas.create_rectangle(1, 1, width - 2, height - 2, fill=frame_fill, outline=border)
        for fraction in (1 / 3, 2 / 3):
            x = int(width * fraction)
            y = int(height * fraction)
            canvas.create_line(x, 2, x, height - 2, fill=self.palette["canvas_grid"])
            canvas.create_line(2, y, width - 2, y, fill=self.palette["canvas_grid"])

        logo_path = self._current_download_logo_path()
        logo_x, logo_y, logo_width, logo_height = self._logo_preview_bounds(width, height)
        if not logo_path or not Path(logo_path).expanduser().exists():
            canvas.create_text(
                width // 2, height // 2, text="Aucun logo chargé",
                fill=self.palette["muted"], font=(self.font_family, 9),
            )
            return

        try:
            image = Image.open(Path(logo_path).expanduser()).convert("RGBA")
            resized = image.resize((max(1, logo_width), max(1, logo_height)), Image.Resampling.LANCZOS)
            opacity = self._get_download_logo_opacity_percent() / 100.0
            if not enabled:
                opacity *= 0.35
            red, green, blue, alpha = resized.split()
            alpha = alpha.point(lambda value: int(value * opacity))
            resized.putalpha(alpha)
            self._logo_preview_tk = ImageTk.PhotoImage(resized)
            canvas.create_image(logo_x, logo_y, anchor="nw", image=self._logo_preview_tk, tags=("logo",))
        except Image.DecompressionBombError:
            canvas.create_text(
                width // 2, height // 2, text="Logo trop grand pour l'aperçu",
                fill=self.palette["danger"], font=(self.font_family, 8),
            )
        except Exception as error:
            canvas.create_text(
                width // 2, height // 2, text=f"Erreur chargement logo : {error}",
                fill=self.palette["danger"], font=(self.font_family, 8),
            )

    def _draw_logo_preview(self) -> None:
        self._redraw_logo_preview()

    def _on_logo_preview_press(self, event: tk.Event) -> None:
        if not bool(self.download_logo_enabled_var.get()) or getattr(self, "busy", False):
            return
        width, height = self._logo_preview_canvas_size()
        logo_x, logo_y, logo_width, logo_height = self._logo_preview_bounds(width, height)
        if logo_x <= event.x <= logo_x + logo_width and logo_y <= event.y <= logo_y + logo_height:
            self._logo_preview_drag_offset = (event.x - logo_x, event.y - logo_y)
        else:
            self._logo_preview_drag_offset = (logo_width // 2, logo_height // 2)
            self._on_logo_preview_drag(event)

    def _on_logo_preview_drag(self, event: tk.Event) -> None:
        if not bool(self.download_logo_enabled_var.get()) or getattr(self, "busy", False):
            return
        width, height = self._logo_preview_canvas_size()
        _logo_x, _logo_y, logo_width, logo_height = self._logo_preview_bounds(width, height)
        offset_x, offset_y = getattr(self, "_logo_preview_drag_offset", (logo_width // 2, logo_height // 2))
        x = max(0, min(width - logo_width, int(event.x - offset_x)))
        y = max(0, min(height - logo_height, int(event.y - offset_y)))
        self.download_logo_x_ratio_var.set(x / width)
        self.download_logo_y_ratio_var.set(y / height)
        self._redraw_logo_preview()

    @staticmethod
    def _logo_ratio_options_from_item(item: dict) -> dict:
        scale_percent = item.get("logo_scale_percent", download_utils.DEFAULT_LOGO_SCALE_PERCENT)
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
                item.get("logo_position", download_utils.DEFAULT_LOGO_POSITION), logo_width_ratio,
            )
        else:
            logo_x_ratio = download_utils.normalize_logo_x_ratio(x_source, logo_width_ratio)
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
