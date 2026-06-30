"""Transcript mixin: moments cards, tags, generate, save, export."""

from __future__ import annotations

import json
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import ttk
from typing import List, Optional


def _parse_timestamp_to_seconds(ts: str) -> float:
    """Parse MM:SS or HH:MM:SS into a float number of seconds."""
    parts = ts.strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except (ValueError, IndexError):
        pass
    raise ValueError(f"Format invalide : {ts!r}  (attendu MM:SS ou HH:MM:SS)")

from ..constants import (
    LOGGER,
    TIMESTAMP_RE,
    BRACKET_RE,
    INVALID_FILENAME_CHARS_RE,
    FILENAME_SPACES_RE,
)
from ..widgets.progress import _CanvasProgress
from ...base import (
    VideoIdExtractionError,
    TranscriptRetrievalError,
    export_most_viewed_csv,
    format_most_viewed_moments,
    generate_transcript_with_format,
    seconds_to_timestamp,
    extract_video_id,
)


class TranscriptMixin:
    def _on_moments_configure(self, event: tk.Event) -> None:
        self.moments_canvas.configure(scrollregion=self.moments_canvas.bbox("all"))

    def _on_moments_canvas_configure(self, event: tk.Event) -> None:
        self.moments_canvas.itemconfigure(self.moments_window, width=event.width)
        wrap = max(event.width - 220, 220)
        for label in self._moment_excerpt_labels:
            label.configure(wraplength=wrap)

    def _score_color(self, ratio: float) -> str:
        """Return a color from indigo (low) → violet (mid) → emerald (high)."""
        ratio = max(0.0, min(1.0, ratio))
        if ratio < 0.5:
            # indigo → violet
            t = ratio * 2
            start = (91, 91, 214)   # #5b5bd6 accent
            end = (124, 58, 237)    # #7c3aed secondary
        else:
            # violet → emerald
            t = (ratio - 0.5) * 2
            start = (124, 58, 237)  # #7c3aed secondary
            end = (5, 150, 105)     # #059669 success
        r = int(start[0] + (end[0] - start[0]) * t)
        g = int(start[1] + (end[1] - start[1]) * t)
        b = int(start[2] + (end[2] - start[2]) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _render_most_viewed_cards(self, moments: List) -> None:
        for child in self.moments_list.winfo_children():
            child.destroy()
        self._moment_excerpt_labels = []
        self._moment_action_buttons = []
        self._moment_mini_bars = {}

        if not moments:
            self.moments_count_label.configure(text="0 moment")
            empty = ttk.Label(
                self.moments_list,
                text="Aucun moment détecté pour le moment.",
                style="CardMuted.TLabel",
            )
            empty.grid(row=0, column=0, sticky="w", padx=4, pady=6)
            return

        self.moments_count_label.configure(text=f"{len(moments)} moments")
        max_score = max((moment.score for moment in moments), default=1) or 1
        for index, moment in enumerate(moments):
            is_top = index == 0
            card_border = self.palette["hero_stripe"] if is_top else self.palette["border"]
            card = tk.Frame(
                self.moments_list,
                bg=self.palette["card"],
                highlightthickness=2 if is_top else 1,
                highlightbackground=card_border,
            )
            card.grid(row=index, column=0, sticky="ew", padx=4, pady=(10 if is_top else 5, 5))
            card.grid_columnconfigure(1, weight=1)

            # Left accent bar (vertical stripe)
            accent_bar = tk.Frame(
                card,
                bg=self._score_color(moment.score / max_score),
                width=4,
            )
            accent_bar.grid(row=0, column=0, rowspan=3, sticky="ns")

            timestamp = seconds_to_timestamp(moment.minute_index * 60)
            top_row = tk.Frame(card, bg=self.palette["card"])
            top_row.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(12, 12), pady=(12, 4))
            top_row.grid_columnconfigure(0, weight=1)

            badge_row = tk.Frame(top_row, bg=self.palette["card"])
            badge_row.grid(row=0, column=0, sticky="w")

            badge = tk.Label(
                badge_row,
                text=f"  {timestamp}  ",
                bg=self.palette["accent"],
                fg=self.palette["white"],
                font=(self.font_family, 10, "bold"),
                pady=3,
            )
            badge.grid(row=0, column=0, sticky="w")

            if is_top:
                tk.Label(
                    badge_row,
                    text="  ★ Recommandé  ",
                    bg=self.palette["success"],
                    fg=self.palette["white"],
                    font=(self.font_family, 9, "bold"),
                    pady=3,
                ).grid(row=0, column=1, sticky="w", padx=(8, 0))

            # Score bar + label (top-right)
            score_frame = tk.Frame(top_row, bg=self.palette["card"])
            score_frame.grid(row=0, column=1, sticky="e")
            score_label = tk.Label(
                score_frame,
                text=f"Score {moment.score}",
                bg=self.palette["card"],
                fg=self.palette["accent"],
                font=(self.font_family, 9, "bold"),
            )
            score_label.grid(row=0, column=0, sticky="e")

            bar_width = 100
            bar = tk.Canvas(
                score_frame,
                width=bar_width,
                height=8,
                background=self.palette["bg_alt"],
                highlightthickness=0,
            )
            fill_width = max(4, int(bar_width * moment.score / max_score))
            bar_color = self._score_color(moment.score / max_score)
            bar.create_rectangle(0, 0, bar_width, 8, fill=self.palette["bg_alt"], outline="")
            bar.create_rectangle(0, 0, fill_width, 8, fill=bar_color, outline="")
            bar.grid(row=1, column=0, sticky="e", pady=(4, 0))

            excerpt_label = tk.Label(
                card,
                text=moment.excerpt,
                bg=self.palette["card"],
                fg=self.palette["text"],
                justify="left",
                anchor="w",
                font=(self.font_family, 10),
                wraplength=520,
            )
            excerpt_label.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(12, 12))
            self._moment_excerpt_labels.append(excerpt_label)

            button_stack = tk.Frame(card, bg=self.palette["card"])
            button_stack.grid(row=2, column=1, columnspan=2, sticky="w", padx=12, pady=(10, 12))

            play_button = ttk.Button(
                button_stack,
                text="▶ Lire",
                command=lambda m=moment: self._open_at_minute(m.minute_index),
                style="SoftPrimary.TButton",
            )
            play_button.grid(row=0, column=0, sticky="ew")
            self._moment_action_buttons.append(play_button)

            download_button = ttk.Button(
                button_stack,
                text="⬇ Extraire",
                command=lambda m=moment: self.download_single_clip(m),
                style="Secondary.TButton",
            )
            download_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
            self._moment_action_buttons.append(download_button)

            preview_button = ttk.Button(
                button_stack,
                text="👁 Aperçu",
                command=lambda m=moment: self.preview_single_clip(m),
                style="Secondary.TButton",
            )
            preview_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))
            self._moment_action_buttons.append(preview_button)

            copy_button = ttk.Button(
                button_stack,
                text="📋 Copier",
                command=lambda m=moment: self.copy_moment_text(m),
                style="Secondary.TButton",
            )
            copy_button.grid(row=0, column=3, sticky="ew", padx=(8, 0))
            self._moment_action_buttons.append(copy_button)

            mini_bar = _CanvasProgress(
                card,
                height=4,
                palette=self.palette,
                font_family=self.font_family,
                show_text=False,
                bg=self.palette["card"],
            )
            mini_bar.grid(row=3, column=0, columnspan=3, sticky="ew")
            self._moment_mini_bars[index] = mini_bar

    def _open_at_minute(self, minute_index: int) -> None:
        url = self.last_url or self._get_entry_value(self.url_entry)
        if not url:
            messagebox.showinfo("Aucune URL", "Ajoute une URL pour ouvrir ce moment.")
            return
        seconds = minute_index * 60
        separator = "&" if "?" in url else "?"
        webbrowser.open(f"{url}{separator}t={seconds}s")

    def _build_moment_clip_text(self, moment) -> str:
        start = float(moment.minute_index * 60)
        duration = float(self._get_clip_duration())
        end = start + duration
        lines: List[str] = []
        for chunk in self.last_transcript_chunks:
            text = str(chunk.get("text", "")).replace("\n", " ").strip()
            if not text:
                continue
            try:
                chunk_start = float(chunk.get("start", 0.0) or 0.0)
                chunk_duration = float(chunk.get("duration", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            chunk_end = chunk_start + max(chunk_duration, 0.0)
            if chunk_start < end and chunk_end > start:
                lines.append(text)
        if lines:
            return "\n".join(lines)
        return str(getattr(moment, "excerpt", "")).strip()

    @staticmethod
    def _filename_timestamp(seconds: float) -> str:
        return seconds_to_timestamp(seconds).replace(":", "-")

    @staticmethod
    def _sanitize_filename_text(text: str, max_length: int = 96) -> str:
        cleaned = INVALID_FILENAME_CHARS_RE.sub(" ", text.replace("\n", " ").strip())
        cleaned = FILENAME_SPACES_RE.sub(" ", cleaned).strip(" ._-")
        if not cleaned:
            return "extrait"
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length].rstrip(" ._-")
        return cleaned or "extrait"

    def _build_moment_filename_label(self, moment) -> str:
        raw_text = self._build_moment_clip_text(moment)
        if not raw_text:
            raw_text = str(getattr(moment, "excerpt", "")).strip()
        return self._sanitize_filename_text(raw_text)

    def copy_moment_text(self, moment) -> None:
        content = self._build_moment_clip_text(moment)
        if not content:
            messagebox.showinfo(
                "Aucun texte",
                "Aucun texte trouvé pour cet extrait.",
            )
            return
        self.master.clipboard_clear()
        self.master.clipboard_append(content)
        timestamp = seconds_to_timestamp(moment.minute_index * 60)
        self._set_status(
            f"Texte de l'extrait {timestamp} copié ✓", busy=False, success=True
        )

    def _configure_transcript_tags(self) -> None:
        self.output_text.tag_configure(
            "timestamp",
            foreground=self.palette["muted"],
            font=(self.mono_family, 10, "bold"),
        )
        self.output_text.tag_configure(
            "bracket",
            foreground=self.palette["timestamp"],
            font=(self.mono_family, 10, "italic"),
        )

    def _apply_transcript_tags(self, lines: List[str]) -> None:
        for idx, line in enumerate(lines, start=1):
            match = TIMESTAMP_RE.match(line)
            if match:
                end = match.end()
                self.output_text.tag_add("timestamp", f"{idx}.0", f"{idx}.{end}")
            for bracket in BRACKET_RE.finditer(line):
                self.output_text.tag_add(
                    "bracket",
                    f"{idx}.{bracket.start()}",
                    f"{idx}.{bracket.end()}",
                )

    def copy_to_clipboard(self) -> None:
        content = self.output_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Aucune donnée", "Rien à copier pour le moment.")
            return
        self.master.clipboard_clear()
        self.master.clipboard_append(content)
        self._set_status("Transcription copiée ✓", busy=False, success=True)

    def _set_status(
        self, message: str, *, busy: bool, error: bool = False, success: bool = False
    ) -> None:
        self.status_var.set(message)
        if busy:
            self._set_busy_state(True)
            if not self.download_active:
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
        else:
            self._set_busy_state(False)
            self.progress.stop()
        if error:
            self.style.configure("Status.TLabel", foreground=self.palette["status_error"])
        elif success:
            self.style.configure("Status.TLabel", foreground=self.palette["success"])
        else:
            self.style.configure("Status.TLabel", foreground=self.palette["accent"])

    def generate(self) -> None:
        """Launch background transcript generation."""
        import threading
        self._recover_stale_busy_state()
        if self.busy:
            self._set_status("Un traitement est déjà en cours…", busy=True)
            return

        if self.download_active:
            messagebox.showinfo(
                "Téléchargement en cours",
                "Merci d'attendre la fin du téléchargement avant de générer.",
            )
            return

        url = self._get_entry_value(self.url_entry)
        if not url:
            messagebox.showwarning("Champ manquant", "Colle un lien YouTube à transcrire.")
            return
        try:
            extract_video_id(url)
        except VideoIdExtractionError:
            message = (
                "La transcription fonctionne uniquement avec une vidéo YouTube.\n\n"
                "Pour ce lien, utilise « Télécharger vidéo » ou « Télécharger audio »."
            )
            messagebox.showerror("Transcription YouTube uniquement", message)
            self._append_output("Erreur: lien non compatible avec la transcription YouTube.")
            self._set_status("Choisis un lien YouTube pour transcrire, ou télécharge le média.", busy=False, error=True)
            return

        languages = self._parse_languages(self._get_entry_value(self.languages_entry))
        output_format = self._selected_output_format()
        include_most_viewed = self.most_viewed_var.get()
        most_viewed_limit = self._get_most_viewed_limit()

        self.last_url = url
        self._set_status("Analyse de la vidéo en cours…", busy=True)
        self.output_text.delete("1.0", tk.END)
        self._render_most_viewed_cards([])
        self.last_most_viewed_moments = []
        self.last_transcript_chunks = []
        self._update_stats("")
        self.meta_var.set("")
        self.cancel_event.clear()
        self.current_job_id += 1
        job_id = self.current_job_id

        thread = threading.Thread(
            target=self._run_generation,
            args=(
                job_id,
                url,
                languages,
                output_format,
                include_most_viewed,
                most_viewed_limit,
            ),
            daemon=True,
        )
        self.generation_thread = thread
        thread.start()

    def _run_generation(
        self,
        job_id: int,
        url: str,
        languages: Optional[List[str]],
        output_format: str,
        include_most_viewed: bool,
        most_viewed_limit: int,
    ) -> None:
        try:
            result = generate_transcript_with_format(
                url,
                languages=languages,
                output_format=output_format,
                include_most_viewed_moments=include_most_viewed,
                most_viewed_limit=most_viewed_limit,
            )
        except (VideoIdExtractionError, TranscriptRetrievalError) as error:
            if self._should_ignore_result(job_id):
                return
            self.master.after(0, self._handle_error, str(error))
            return
        except Exception as error:
            if self._should_ignore_result(job_id):
                return
            LOGGER.exception("Unhandled generation error in GUI thread")
            self.master.after(0, self._handle_error, f"Erreur inattendue: {error}")
            return
        finally:
            self.generation_thread = None

        if self._should_ignore_result(job_id):
            return
        self.master.after(
            0,
            self._display_result,
            result.lines,
            result.raw_transcript,
            result.used_language,
            output_format,
            result.most_viewed_moments,
        )

    def _handle_error(self, message: str) -> None:
        LOGGER.warning("GUI error: %s", message)
        self._set_status("Erreur lors de la récupération.", busy=False, error=True)
        self._append_output(f"Erreur: {message}")
        messagebox.showerror("Impossible de récupérer le script", message)

    def _display_result(
        self,
        lines: List[str],
        transcript_chunks: List[dict] | None,
        used_language: str | None,
        output_format: str,
        most_viewed_moments,
    ) -> None:
        self.last_transcript_chunks = list(transcript_chunks or [])
        self.output_text.insert(tk.END, "\n".join(lines))
        if output_format != "json":
            self._apply_transcript_tags(lines)
        self.output_text.tag_add("sel", "1.0", tk.END)
        self.output_text.focus_set()
        format_label = self.output_format_lookup.get(output_format, output_format)
        meta_parts = [f"Format: {format_label}"]
        if used_language:
            meta_parts.append(f"Langue utilisée: {used_language}")
        self.meta_var.set(" | ".join(meta_parts))
        self._set_status("Transcription récupérée.", busy=False)
        self._update_stats("\n".join(lines))
        if most_viewed_moments is not None:
            self.last_most_viewed_moments = most_viewed_moments
            self._render_most_viewed_cards(most_viewed_moments)

    def save_transcript(self) -> None:
        """Save current transcript to a file."""
        content = self.output_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("Aucune donnée", "Génère d'abord un script.")
            return

        output_format = self._selected_output_format()
        if output_format == "json":
            defext = ".json"
            types = [("Fichier JSON", "*.json"), ("Tous les fichiers", "*.*")]
        else:
            defext = ".txt"
            types = [("Fichier texte", "*.txt"), ("Tous les fichiers", "*.*")]

        file_path = filedialog.asksaveasfilename(
            defaultextension=defext,
            filetypes=types,
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(content)
        except OSError as error:
            messagebox.showerror("Enregistrement impossible", str(error))
        else:
            self._set_status(f"Script enregistré dans {file_path}.", busy=False)

    def _copy_youtube_chapters(self) -> None:
        if not self.last_most_viewed_moments:
            messagebox.showinfo(
                "Aucun moment détecté",
                "Transcris une vidéo d'abord pour détecter les moments forts.",
            )
            return
        lines = ["0:00 Introduction"]
        for moment in self.last_most_viewed_moments:
            ts = seconds_to_timestamp(moment.minute_index * 60)
            excerpt = moment.excerpt[:60].strip().rstrip("…").rstrip(".")
            lines.append(f"{ts} {excerpt}")
        self.master.clipboard_clear()
        self.master.clipboard_append("\n".join(lines))
        self._set_status("Chapitres YouTube copiés ✓", busy=False, success=True)

    def _open_manual_cut_dialog(self) -> None:
        """Open a dialog to manually select a transcript range and extract a clip."""
        chunks = getattr(self, "last_transcript_chunks", [])
        if not chunks:
            messagebox.showinfo(
                "Aucune transcription",
                "Génère d'abord une transcription pour sélectionner un extrait.",
            )
            return

        dialog = tk.Toplevel(self.master)
        dialog.title("Sélection manuelle d'un extrait")
        dialog.geometry("700x540")
        dialog.minsize(520, 420)
        dialog.transient(self.master)
        dialog.configure(bg=self.palette["bg"])
        dialog.grab_set()

        # Header
        header = tk.Frame(dialog, bg=self.palette["card"], pady=12)
        header.pack(fill="x")
        tk.Label(
            header,
            text="✂  Sélectionner un extrait de la transcription",
            bg=self.palette["card"],
            fg=self.palette["text"],
            font=(self.font_family, 13, "bold"),
            padx=16,
        ).pack(side="left")

        # Separator
        tk.Frame(dialog, bg=self.palette["border"], height=1).pack(fill="x")

        # Time pickers row
        time_frame = tk.Frame(dialog, bg=self.palette["bg"], pady=10)
        time_frame.pack(fill="x", padx=16)

        for col, label, var_name, default in [
            (0, "Début :", "start_var", "00:00:00"),
            (2, "Fin :", "end_var", "00:00:30"),
        ]:
            tk.Label(
                time_frame,
                text=label,
                bg=self.palette["bg"],
                fg=self.palette["muted"],
                font=(self.font_family, 11),
            ).grid(row=0, column=col, sticky="w", padx=(0 if col == 0 else 24, 4))

        start_var = tk.StringVar(value="00:00:00")
        end_var = tk.StringVar(value="00:00:30")

        entry_kw = dict(
            width=10,
            bg=self.palette["bg_alt"],
            fg=self.palette["text"],
            insertbackground=self.palette["text"],
            font=(self.mono_family, 11),
            relief="flat",
            highlightthickness=1,
            highlightcolor=self.palette["accent"],
            highlightbackground=self.palette["border"],
        )
        start_entry = tk.Entry(time_frame, textvariable=start_var, **entry_kw)
        start_entry.grid(row=0, column=1, sticky="w")
        tk.Label(
            time_frame, text="Fin :", bg=self.palette["bg"],
            fg=self.palette["muted"], font=(self.font_family, 11),
        ).grid(row=0, column=2, sticky="w", padx=(24, 4))
        end_entry = tk.Entry(time_frame, textvariable=end_var, **entry_kw)
        end_entry.grid(row=0, column=3, sticky="w")

        dur_label = tk.Label(
            time_frame, text="", bg=self.palette["bg"],
            fg=self.palette["muted"], font=(self.font_family, 10),
        )
        dur_label.grid(row=0, column=4, sticky="w", padx=(16, 0))

        def _update_duration(*_):
            try:
                s = _parse_timestamp_to_seconds(start_var.get())
                e = _parse_timestamp_to_seconds(end_var.get())
                dur = e - s
                dur_label.config(
                    text=f"Durée : {seconds_to_timestamp(dur)}" if dur > 0 else ""
                )
            except ValueError:
                dur_label.config(text="")

        start_var.trace_add("write", _update_duration)
        end_var.trace_add("write", _update_duration)

        # Mode selector
        mode_frame = tk.Frame(dialog, bg=self.palette["bg"], pady=2)
        mode_frame.pack(fill="x", padx=16)
        tk.Label(
            mode_frame, text="Clic sur une ligne → définir :",
            bg=self.palette["bg"], fg=self.palette["muted"],
            font=(self.font_family, 10),
        ).pack(side="left")
        mode_var = tk.StringVar(value="start")
        for val, lbl in [("start", "le Début"), ("end", "la Fin")]:
            tk.Radiobutton(
                mode_frame, text=lbl, variable=mode_var, value=val,
                bg=self.palette["bg"], fg=self.palette["text"],
                selectcolor=self.palette["card"],
                activebackground=self.palette["bg"],
                activeforeground=self.palette["text"],
                font=(self.font_family, 10),
            ).pack(side="left", padx=(8, 0))

        # Search bar
        search_frame = tk.Frame(dialog, bg=self.palette["bg"])
        search_frame.pack(fill="x", padx=16, pady=(6, 2))
        tk.Label(
            search_frame, text="Rechercher :",
            bg=self.palette["bg"], fg=self.palette["muted"],
            font=(self.font_family, 10),
        ).pack(side="left")
        search_var = tk.StringVar()
        search_entry = tk.Entry(
            search_frame, textvariable=search_var,
            bg=self.palette["bg_alt"], fg=self.palette["text"],
            insertbackground=self.palette["text"],
            font=(self.mono_family, 10), relief="flat",
            highlightthickness=1,
            highlightcolor=self.palette["accent"],
            highlightbackground=self.palette["border"],
            width=28,
        )
        search_entry.pack(side="left", padx=(6, 6))
        match_label = tk.Label(
            search_frame, text="",
            bg=self.palette["bg"], fg=self.palette["muted"],
            font=(self.font_family, 9),
        )
        match_label.pack(side="left")

        # Transcript listbox
        list_outer = tk.Frame(dialog, bg=self.palette["bg"])
        list_outer.pack(fill="both", expand=True, padx=16, pady=(2, 0))

        scrollbar = ttk.Scrollbar(list_outer, orient="vertical")
        listbox = tk.Listbox(
            list_outer,
            yscrollcommand=scrollbar.set,
            bg=self.palette["bg_alt"],
            fg=self.palette["text"],
            selectbackground=self.palette["accent"],
            selectforeground=self.palette["white"],
            font=(self.mono_family, 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.palette["border"],
            activestyle="none",
            cursor="hand2",
        )
        scrollbar.config(command=listbox.yview)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        chunk_starts: List[float] = []
        chunk_texts: List[str] = []
        for chunk in chunks:
            try:
                cs = float(chunk.get("start", 0) or 0)
            except (TypeError, ValueError):
                cs = 0.0
            text = str(chunk.get("text", "")).replace("\n", " ").strip()
            ts = seconds_to_timestamp(cs)
            listbox.insert(tk.END, f"  {ts}    {text}")
            chunk_starts.append(cs)
            chunk_texts.append(text.lower())

        # Search state
        _search_matches: List[int] = []
        _search_cursor: List[int] = [0]

        def _jump_to(idx: int) -> None:
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(idx)
            listbox.see(idx)
            listbox.activate(idx)

        def _do_search(*_) -> None:
            query = search_var.get().strip().lower()
            _search_matches.clear()
            _search_cursor[0] = 0
            if not query:
                match_label.config(text="")
                listbox.selection_clear(0, tk.END)
                return
            for i, txt in enumerate(chunk_texts):
                if query in txt:
                    _search_matches.append(i)
            if _search_matches:
                match_label.config(text=f"{len(_search_matches)} résultat(s)")
                _jump_to(_search_matches[0])
            else:
                match_label.config(text="Aucun résultat")

        def _next_match(direction: int = 1) -> None:
            if not _search_matches:
                return
            _search_cursor[0] = (_search_cursor[0] + direction) % len(_search_matches)
            _jump_to(_search_matches[_search_cursor[0]])

        search_var.trace_add("write", _do_search)
        search_entry.bind("<Return>", lambda e: _next_match(1))
        search_entry.bind("<Shift-Return>", lambda e: _next_match(-1))

        next_btn = self._button(
            search_frame, text="↓", command=lambda: _next_match(1), variant="tertiary"
        )
        next_btn.pack(side="left", padx=(2, 0))
        prev_btn = self._button(
            search_frame, text="↑", command=lambda: _next_match(-1), variant="tertiary"
        )
        prev_btn.pack(side="left", padx=(2, 0))

        def _on_listbox_click(event):
            sel = listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            cs = chunk_starts[idx]
            ts = seconds_to_timestamp(cs)
            if ts.count(":") == 1:
                ts = "00:" + ts
            if mode_var.get() == "start":
                start_var.set(ts)
                mode_var.set("end")
            else:
                end_var.set(ts)
                mode_var.set("start")

        listbox.bind("<<ListboxSelect>>", _on_listbox_click)

        # Bottom buttons
        tk.Frame(dialog, bg=self.palette["border"], height=1).pack(fill="x", pady=(8, 0))
        btn_frame = tk.Frame(dialog, bg=self.palette["bg"], pady=10)
        btn_frame.pack(fill="x", padx=16)

        def _do_extract():
            try:
                start_s = _parse_timestamp_to_seconds(start_var.get())
                end_s = _parse_timestamp_to_seconds(end_var.get())
            except ValueError as exc:
                messagebox.showerror("Timestamp invalide", str(exc), parent=dialog)
                return
            if end_s <= start_s:
                messagebox.showerror(
                    "Plage invalide",
                    "La fin doit être après le début.",
                    parent=dialog,
                )
                return
            dialog.destroy()
            self.download_custom_clip(start_s, end_s)

        extract_btn = self._button(
            btn_frame, text="⬇ Extraire ce clip", command=_do_extract, variant="primary"
        )
        extract_btn.pack(side="right", padx=(8, 0))
        close_btn = self._button(
            btn_frame, text="Fermer", command=dialog.destroy, variant="tertiary"
        )
        close_btn.pack(side="right")

        _update_duration()

    def export_moments(self) -> None:
        if not self.last_most_viewed_moments:
            messagebox.showinfo(
                "Aucune donnée",
                "Génère d'abord les moments forts estimés pour exporter.",
            )
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[
                ("Fichier CSV", "*.csv"),
                ("Fichier texte", "*.txt"),
                ("Fichier JSON", "*.json"),
                ("Tous les fichiers", "*.*"),
            ],
            initialfile="moments_forts_estimes",
        )
        if not file_path:
            return
        try:
            extension = Path(file_path).suffix.lower()
            if extension == ".json":
                payload = {
                    "moments": [moment.to_dict() for moment in self.last_most_viewed_moments],
                    "source_url": self.last_url,
                }
                with open(file_path, "w", encoding="utf-8") as file:
                    json.dump(payload, file, ensure_ascii=False, indent=2)
            elif extension == ".txt":
                lines = format_most_viewed_moments(
                    self.last_most_viewed_moments, include_header=True
                )
                with open(file_path, "w", encoding="utf-8") as file:
                    file.write("\n".join(lines))
            else:
                export_most_viewed_csv(file_path, self.last_most_viewed_moments)
        except OSError as error:
            messagebox.showerror("Export impossible", str(error))
        else:
            self._set_status("Moments exportés.", busy=False)
