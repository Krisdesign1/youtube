"""Theme application mixin: fonts, styles, colours."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import List

from ..theme import THEME, SPACING, BUTTON_VARIANTS


class ThemeMixin:
    def _apply_blue_theme(self) -> None:
        self.palette = dict(THEME)
        self.spacing = dict(SPACING)
        self.font_family = self._pick_font_family(
            ["Avenir Next", "SF Pro Text", "SF Pro Display", "Montserrat", "Poppins", "Inter", "Segoe UI"],
            fallback="Helvetica",
        )
        self.mono_family = self._pick_font_family(
            ["Menlo", "SF Mono", "Consolas", "Monaco", "Courier New"],
            fallback="Courier New",
        )
        font_main = (self.font_family, 10)
        font_title = (self.font_family, 23, "bold")
        font_label = (self.font_family, 11, "bold")
        font_section = (self.font_family, 12, "bold")
        font_button = (self.font_family, 12, "bold")
        font_link = (self.font_family, 10, "underline")
        font_subtle = (self.font_family, 9)

        self.master.option_add("*Font", font_main)

        self.master.configure(background=self.palette["bg"])
        self.style.configure("TFrame", background=self.palette["bg"])
        self.style.configure("TLabelframe", background=self.palette["bg"])
        self.style.configure(
            "TLabelframe.Label",
            background=self.palette["bg"],
            foreground=self.palette["accent"],
            font=font_label,
        )
        self.style.configure(
            "TLabel",
            background=self.palette["bg"],
            foreground=self.palette["text"],
            font=font_main,
        )
        self.style.configure(
            "Title.TLabel",
            font=font_title,
            foreground=self.palette["accent"],
            background=self.palette["bg"],
        )
        self.style.configure(
            "Subtitle.TLabel",
            foreground=self.palette["muted"],
            background=self.palette["bg"],
            font=font_main,
        )
        self.style.configure(
            "Status.TLabel",
            foreground=self.palette["accent"],
            background=self.palette["bg"],
            font=(self.font_family, 10, "bold"),
        )
        self.style.configure(
            "Hero.TFrame",
            background=self.palette["hero"],
        )
        self.style.configure(
            "HeroTitle.TLabel",
            font=(self.font_family, 26, "bold"),
            foreground=self.palette["hero_text"],
            background=self.palette["hero"],
        )
        self.style.configure(
            "HeroSubtitle.TLabel",
            font=(self.font_family, 12),
            foreground=self.palette["hero_muted"],
            background=self.palette["hero"],
        )
        self.style.configure(
            "TButton",
            background=self.palette["bg_alt"],
            foreground=self.palette["accent"],
            padding=(self.spacing["md"] - self.spacing["xs"], 7),
            font=font_main,
        )
        self.style.map(
            "TButton",
            background=[
                ("active", self.palette["button_hover"]),
                ("disabled", self.palette["button_disabled"]),
            ],
        )
        self.style.configure(
            "Primary.TButton",
            background=self.palette["accent"],
            foreground=self.palette["white"],
            padding=(22, 13),
            font=font_button,
        )
        self.style.map(
            "Primary.TButton",
            background=[
                ("active", self.palette["accent_dark"]),
                ("disabled", self.palette["primary_disabled"]),
            ],
            foreground=[("disabled", self.palette["primary_disabled_text"])],
        )
        self.style.configure(
            "Secondary.TButton",
            background=self.palette["card"],
            foreground=self.palette["muted"],
            padding=(11, 8),
            font=font_main,
            bordercolor=self.palette["border"],
        )
        self.style.map(
            "Secondary.TButton",
            background=[
                ("active", self.palette["secondary_hover"]),
                ("disabled", self.palette["secondary_disabled"]),
            ],
            foreground=[
                ("active", self.palette["accent"]),
                ("disabled", self.palette["secondary_disabled_text"]),
            ],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=self.palette["card"],
            foreground=self.palette["text"],
            bordercolor=self.palette["border"],
        )
        self.style.configure(
            "Normal.TEntry",
            fieldbackground=self.palette["card"],
            foreground=self.palette["text"],
        )
        self.style.configure(
            "Placeholder.TEntry",
            fieldbackground=self.palette["placeholder_bg"],
            foreground=self.palette["placeholder_text"],
        )
        self.style.configure(
            "TCheckbutton",
            background=self.palette["bg"],
            foreground=self.palette["text"],
            font=font_main,
        )
        self.style.configure(
            "Card.TLabelframe",
            background=self.palette["card"],
            bordercolor=self.palette["border"],
            relief="solid",
        )
        self.style.configure(
            "Card.TLabelframe.Label",
            background=self.palette["card"],
            foreground=self.palette["accent"],
            font=font_label,
        )
        self.style.configure(
            "Card.TLabel",
            background=self.palette["card"],
            foreground=self.palette["text"],
            font=font_main,
        )
        self.style.configure(
            "CardTitle.TLabel",
            background=self.palette["card"],
            foreground=self.palette["text"],
            font=font_section,
        )
        self.style.configure(
            "CardMuted.TLabel",
            background=self.palette["card"],
            foreground=self.palette["muted"],
            font=font_main,
        )
        self.style.configure(
            "Card.TFrame",
            background=self.palette["card"],
        )
        self.style.configure(
            "CardAlt.TFrame",
            background=self.palette["bg_alt"],
        )
        self.style.configure(
            "Card.TCheckbutton",
            background=self.palette["card"],
            foreground=self.palette["text"],
            font=font_main,
        )
        self.style.configure(
            "Link.TButton",
            background=self.palette["card"],
            foreground=self.palette["accent"],
            padding=(0, 0),
            font=font_link,
            borderwidth=0,
        )
        self.style.configure(
            "SoftPrimary.TButton",
            background=self.palette["soft_primary"],
            foreground=self.palette["accent"],
            padding=(13, 9),
            font=font_main,
            bordercolor=self.palette["border"],
        )
        self.style.map(
            "SoftPrimary.TButton",
            background=[
                ("active", self.palette["soft_primary_hover"]),
                ("disabled", self.palette["soft_primary_disabled"]),
            ],
            foreground=[
                ("active", self.palette["accent_dark"]),
                ("disabled", self.palette["secondary_disabled_text"]),
            ],
        )
        self.style.configure(
            "Subtle.TButton",
            background=self.palette["subtle"],
            foreground=self.palette["muted"],
            padding=(9, 6),
            font=font_subtle,
            bordercolor=self.palette["border"],
        )
        self.style.map(
            "Subtle.TButton",
            background=[
                ("active", self.palette["subtle_hover"]),
                ("disabled", self.palette["secondary_disabled"]),
            ],
            foreground=[
                ("active", self.palette["accent"]),
                ("disabled", self.palette["secondary_disabled_text"]),
            ],
        )
        self.style.map(
            "Link.TButton",
            foreground=[("active", self.palette["accent_dark"])],
            background=[("active", self.palette["card"])],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=self.palette["card"],
            foreground=self.palette["text"],
        )
        self.style.configure(
            "Options.TNotebook",
            background=self.palette["card"],
            tabmargins=[0, 4, 0, 0],
        )
        self.style.configure(
            "Options.TNotebook.Tab",
            background=self.palette["bg_alt"],
            foreground=self.palette["muted"],
            padding=[14, 6],
            font=(self.font_family, 10),
        )
        self.style.map(
            "Options.TNotebook.Tab",
            background=[("selected", self.palette["soft_primary"])],
            foreground=[("selected", self.palette["accent"])],
        )
        self.style.configure(
            "Blue.Horizontal.TProgressbar",
            troughcolor=self.palette["bg_alt"],
            background=self.palette["accent"],
            bordercolor=self.palette["border"],
            lightcolor=self.palette["accent"],
            darkcolor=self.palette["accent_dark"],
        )
        self.style.configure(
            "Success.Horizontal.TProgressbar",
            troughcolor=self.palette["bg_alt"],
            background=self.palette["success"],
            bordercolor=self.palette["border"],
            lightcolor=self.palette["success"],
            darkcolor=self.palette["success"],
        )

    def _pick_font_family(self, candidates: List[str], *, fallback: str) -> str:
        available = set(tkfont.families(self.master))
        for name in candidates:
            if name in available:
                return name
        return fallback

    def _button(
        self,
        parent: tk.Misc,
        *,
        text: str,
        command,
        variant: str = "secondary",
        **kwargs,
    ) -> ttk.Button:
        style = BUTTON_VARIANTS.get(variant, BUTTON_VARIANTS["secondary"])
        return ttk.Button(parent, text=text, command=command, style=style, **kwargs)
