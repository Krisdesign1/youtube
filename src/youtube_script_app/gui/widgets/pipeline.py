"""Pipeline steps widget: visual indicator for download/render stages."""

from __future__ import annotations

import tkinter as tk


class PipelineSteps(tk.Canvas):
    """Horizontal pipeline showing download/render steps with state indicators."""

    _STEPS = ["Téléchargement", "Traitement", "Rendu", "Export"]
    _PULSE_MS = 600

    def __init__(self, master, *, palette: dict, **kwargs) -> None:
        super().__init__(master, height=48, highlightthickness=0, bd=0, **kwargs)
        self._pal = palette
        self._states: list[str] = ["pending"] * len(self._STEPS)
        self._pulse_on = False
        self._pulse_job: str | None = None
        self.bind("<Configure>", lambda _e: self._draw())

    def set_step(self, idx: int, state: str) -> None:
        if 0 <= idx < len(self._states):
            self._states[idx] = state
        self._manage_pulse()
        self._draw()

    def reset(self) -> None:
        self._states = ["pending"] * len(self._STEPS)
        self._stop_pulse()
        self._draw()

    def _manage_pulse(self) -> None:
        if "active" in self._states:
            if self._pulse_job is None:
                self._start_pulse()
        else:
            self._stop_pulse()

    def _start_pulse(self) -> None:
        self._pulse_on = True
        self._pulse_job = self.after(self._PULSE_MS, self._tick_pulse)

    def _stop_pulse(self) -> None:
        if self._pulse_job:
            try:
                self.after_cancel(self._pulse_job)
            except Exception:
                pass
            self._pulse_job = None

    def _tick_pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        self._draw()
        if "active" in self._states:
            self._pulse_job = self.after(self._PULSE_MS, self._tick_pulse)

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
        n = len(self._STEPS)
        step_w = w / n
        circle_r = 10
        cy = h // 2 - 8
        label_y = cy + circle_r + 6

        for i, (step, state) in enumerate(zip(self._STEPS, self._states)):
            cx = int(step_w * i + step_w / 2)
            if i < n - 1:
                next_cx = int(step_w * (i + 1) + step_w / 2)
                line_color = self._pal["success"] if state == "done" else self._pal["border"]
                self.create_line(cx + circle_r, cy, next_cx - circle_r, cy, fill=line_color, width=2)

            if state == "active":
                fill = self._pal["accent"] if self._pulse_on else self._pal["accent_dark"]
                text_char = "●"
                text_fill = self._pal.get("white", "#ffffff")
            elif state == "done":
                fill = self._pal["success"]
                text_char = "✓"
                text_fill = self._pal.get("white", "#ffffff")
            elif state == "error":
                fill = self._pal["danger"]
                text_char = "✗"
                text_fill = self._pal.get("white", "#ffffff")
            else:
                fill = self._pal["bg_alt"]
                text_char = "○"
                text_fill = self._pal["muted"]

            self.create_oval(
                cx - circle_r, cy - circle_r,
                cx + circle_r, cy + circle_r,
                fill=fill, outline=self._pal["border"],
            )
            self.create_text(cx, cy, text=text_char, fill=text_fill, font=("Arial", 9, "bold"))
            self.create_text(cx, label_y, text=step, fill=self._pal["muted"], font=("Arial", 8))
