"""Video mockup canvas: live preview of overlays."""

from __future__ import annotations

import tkinter as tk


class VideoMockupCanvas(tk.Canvas):
    """Compact live preview mockup of the video with enabled overlays."""

    def __init__(self, master, *, palette: dict, **kwargs) -> None:
        super().__init__(
            master, width=160, height=90, highlightthickness=1, bd=0,
            highlightbackground=palette.get("border", "#dde2f0"), **kwargs,
        )
        self._pal = palette
        self._opts: dict = {}
        self.bind("<Configure>", lambda _e: self._draw())

    def refresh(self, options: dict) -> None:
        self._opts = dict(options)
        self._draw()

    def _draw(self) -> None:
        try:
            self.delete("all")
            w = self.winfo_width() or 160
            h = self.winfo_height() or 90
        except tk.TclError:
            return
        if w < 4 or h < 4:
            self.after(40, self._draw)
            return

        aspect = self._opts.get("aspect", "landscape")
        is_shorts = (aspect == "shorts")

        self.create_rectangle(0, 0, w, h, fill="#2a2a3e", outline="")

        if is_shorts:
            vw = int(w * 0.56)
            vx = (w - vw) // 2
            self.create_rectangle(0, 0, vx, h, fill="#1a1a2e", outline="")
            self.create_rectangle(vx + vw, 0, w, h, fill="#1a1a2e", outline="")
            self.create_rectangle(vx, 0, vx + vw, h, fill="#333355", outline="")
        else:
            self.create_rectangle(0, 0, w, h, fill="#333355", outline="")

        if self._opts.get("progress_bar"):
            self.create_rectangle(0, h - 4, w, h, fill=self._pal.get("accent", "#5b5bd6"), outline="")

        if self._opts.get("lower_third"):
            pos = self._opts.get("lower_third_pos", "Bas")
            lt_h = max(8, h // 5)
            ly = 0 if pos == "Haut" else h - lt_h
            self.create_rectangle(0, ly, w, ly + lt_h, fill="#000033", stipple="gray50", outline="")
            self.create_rectangle(0, ly, 3, ly + lt_h, fill=self._pal.get("accent", "#5b5bd6"), outline="")

        if self._opts.get("subtitles"):
            sub_y = h - 16
            style = self._opts.get("subtitle_style", "word")
            sub_color = "#ffff00" if style == "box" else "#ffffff"
            self.create_text(w // 2, sub_y, text="Sous-titres...", fill=sub_color,
                             font=("Arial", 7, "bold"), anchor="center")

        if self._opts.get("logo"):
            pos = self._opts.get("logo_pos", "Haut droit")
            lw, lh = 24, 14
            margin = 4
            lx = margin if "gauche" in pos else (w - lw - margin if "droit" in pos else (w - lw) // 2)
            ly = (h - lh - margin) if "Bas" in pos else (margin if "Haut" in pos else (h - lh) // 2)
            self.create_rectangle(lx, ly, lx + lw, ly + lh,
                                  fill=self._pal.get("accent", "#5b5bd6"),
                                  outline=self._pal.get("accent_dark", "#4444b8"))
            self.create_text(lx + lw // 2, ly + lh // 2, text="L", fill="#fff", font=("Arial", 7, "bold"))

        self.create_rectangle(0, 0, w - 1, h - 1, outline=self._pal.get("border", "#dde2f0"), fill="")
