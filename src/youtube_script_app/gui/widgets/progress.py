"""Canvas-based progress bar widget."""

from __future__ import annotations

import tkinter as tk

from ..constants import LOGGER


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
        try:
            self.delete("all")
            w = self.winfo_width()
            h = self.winfo_height()
        except tk.TclError:
            return
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
                LOGGER.debug("after_cancel failed — widget may be destroyed")
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
