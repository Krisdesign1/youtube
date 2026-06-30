"""Scrollable card-based history panel."""

from __future__ import annotations

import re as _re
import tkinter as tk
from tkinter import ttk


class HistoryPanel(tk.Frame):
    """Scrollable card-based history panel replacing the ScrolledText history widget."""

    _ICONS = {"video": "🎬", "clip": "✂", "audio": "🎵", "other": "🔗"}
    _CARD_HEIGHT = 52
    _MAX_VISIBLE = 8

    def __init__(self, master, *, palette: dict, font_family: str = "Arial", **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._pal = palette
        self._ff = font_family
        self.configure(bg=palette.get("card", "#ffffff"))

        self._canvas = tk.Canvas(self, bg=palette.get("card", "#ffffff"),
                                 highlightthickness=0, bd=0)
        self._scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")

        self._inner = tk.Frame(self._canvas, bg=palette.get("card", "#ffffff"))
        self._window = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

    def _on_inner_configure(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfigure(self._window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        current = getattr(event, "widget", None)
        while current is not None:
            if current is self._canvas or current is self._inner:
                delta = getattr(event, "delta", 0)
                if delta:
                    self._canvas.yview_scroll(-1 if delta > 0 else 1, "units")
                return
            current = getattr(current, "master", None)

    def populate(self, lines: list) -> None:
        for child in self._inner.winfo_children():
            child.destroy()

        if not lines:
            tk.Label(
                self._inner, text="Aucun téléchargement dans l'historique.",
                bg=self._pal.get("card", "#ffffff"), fg=self._pal.get("muted", "#5a6482"),
                font=(self._ff, 9), padx=8, pady=10,
            ).pack(fill="x")
            self._update_height(1)
            return

        for i, line in enumerate(lines):
            self._make_card(self._inner, str(line).strip(), i)

        self._update_height(min(len(lines), self._MAX_VISIBLE))

    def _update_height(self, visible_count: int) -> None:
        h = max(self._CARD_HEIGHT, visible_count * self._CARD_HEIGHT)
        self._canvas.configure(height=h)

    def _make_card(self, parent, line: str, index: int) -> None:
        card_bg = self._pal.get("card", "#ffffff")
        border_color = self._pal.get("border", "#dde2f0")
        card = tk.Frame(parent, bg=card_bg, highlightthickness=1,
                        highlightbackground=border_color, height=self._CARD_HEIGHT)
        card.pack(fill="x", padx=4, pady=2)
        card.pack_propagate(False)

        line_lower = line.lower()
        if "mp3" in line_lower or "audio" in line_lower or "🎵" in line:
            icon, badge_text, badge_bg = self._ICONS["audio"], "AUDIO", "#059669"
        elif "clip" in line_lower or "extrait" in line_lower or "✂" in line:
            icon, badge_text, badge_bg = self._ICONS["clip"], "CLIP", self._pal.get("accent", "#5b5bd6")
        elif any(x in line_lower for x in ["mp4", "webm", "vidéo", "video"]):
            icon, badge_text, badge_bg = self._ICONS["video"], "VIDEO", self._pal.get("secondary", "#7c3aed")
        else:
            icon, badge_text, badge_bg = self._ICONS["other"], "LIEN", self._pal.get("muted", "#5a6482")

        date_match = _re.search(r'\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}', line)
        date_str = date_match.group(0) if date_match else ""
        display = line[:45] + "…" if len(line) > 45 else line

        inner = tk.Frame(card, bg=card_bg)
        inner.pack(fill="both", expand=True, padx=8, pady=4)

        left = tk.Frame(inner, bg=card_bg)
        left.pack(side="left", fill="both", expand=True)
        top_row = tk.Frame(left, bg=card_bg)
        top_row.pack(fill="x")
        tk.Label(top_row, text=icon, bg=card_bg, fg=self._pal.get("accent", "#5b5bd6"),
                 font=(self._ff, 11)).pack(side="left", padx=(0, 4))
        tk.Label(top_row, text=display, bg=card_bg, fg=self._pal.get("text", "#0d0d1a"),
                 font=(self._ff, 9), anchor="w").pack(side="left", fill="x", expand=True)

        right = tk.Frame(inner, bg=card_bg)
        right.pack(side="right")
        tk.Label(right, text=f" {badge_text} ", bg=badge_bg, fg="#ffffff",
                 font=(self._ff, 7, "bold"), padx=3, pady=1).pack(side="top", anchor="e")
        if date_str:
            tk.Label(right, text=date_str, bg=card_bg, fg=self._pal.get("muted", "#5a6482"),
                     font=(self._ff, 7)).pack(side="top", anchor="e", pady=(2, 0))

    def configure(self, **kwargs) -> None:
        kwargs.pop("state", None)
        super().configure(**kwargs)

    config = configure

    def delete(self, *_args) -> None:
        pass

    def insert(self, *_args) -> None:
        pass

    def see(self, *_args) -> None:
        pass

    def get(self, *_args) -> str:
        return ""
