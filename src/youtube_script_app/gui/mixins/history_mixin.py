"""History mixin: load, save, record and display download history."""

from __future__ import annotations

import json
import subprocess
import tkinter as tk
from pathlib import Path
from typing import List

from ...downloads import history as history_store
from ..constants import LOGGER


class HistoryMixin:
    @staticmethod
    def _empty_download_history() -> dict:
        return history_store.empty_download_history()

    def _normalize_download_history(self, raw: object) -> dict:
        return history_store.normalize_download_history(raw)

    def _load_download_history(self) -> dict:
        path = getattr(self, "download_history_path", None)
        return history_store.load_download_history(path, LOGGER)

    def _save_download_history(self, snapshot: dict | None = None) -> None:
        path = getattr(self, "download_history_path", None)
        if not isinstance(path, Path):
            return
        if snapshot is None:
            lock = getattr(self, "download_history_lock", None)
            if lock is not None:
                with lock:
                    snapshot = json.loads(json.dumps(self.download_history, ensure_ascii=False))
            else:
                snapshot = json.loads(json.dumps(self.download_history, ensure_ascii=False))
        history_store.save_download_history(path, snapshot, LOGGER)

    def _history_key_for_url(self, url: str) -> tuple[str, str]:
        return history_store.history_key_for_url(url)

    @staticmethod
    def _format_history_timestamp(value: str) -> str:
        return history_store.format_history_timestamp(value)

    def _resolve_video_title(self, url: str, yt_dlp_cmd: List[str]) -> str:
        url = (url or "").strip()
        if not url:
            return "Titre inconnu"
        cached = self.video_title_cache.get(url)
        if cached:
            return cached

        title = ""
        if yt_dlp_cmd:
            title_cmd = [
                *yt_dlp_cmd,
                "--no-playlist",
                "--skip-download",
                "--print",
                "%(title)s",
                url,
            ]
            try:
                completed = subprocess.run(
                    title_cmd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=25,
                )
                for line in completed.stdout.splitlines():
                    cleaned = line.strip()
                    if cleaned:
                        title = cleaned
                        break
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                LOGGER.warning("Impossible de récupérer le titre vidéo pour %s: %s", url, error)

        if not title:
            try:
                from ...base import extract_video_id, VideoIdExtractionError
                title = f"YouTube ({extract_video_id(url)})"
            except Exception:
                title = "Titre inconnu"
        self.video_title_cache[url] = title
        return title

    def _record_download_history(self, item: dict, final_path: Path) -> None:
        url = str(item.get("url", "")).strip()
        if not url:
            return
        with self.download_history_lock:
            snapshot = history_store.add_download_record(
                self.download_history,
                item,
                final_path,
                video_title_cache=self.video_title_cache,
            )
        self._save_download_history(snapshot)
        self.master.after(0, self._refresh_download_history_view)

    def _format_download_history_lines(self) -> List[str]:
        with self.download_history_lock:
            snapshot = json.loads(json.dumps(self.download_history, ensure_ascii=False))
        return history_store.format_download_history_lines(snapshot)

    def _refresh_download_history_view(self) -> None:
        panel = getattr(self, "download_history_panel", None)
        if panel is not None:
            lines = self._format_download_history_lines()
            panel.populate(lines)
            return
        widget = getattr(self, "download_history_text", None)
        if widget is None:
            return
        lines = self._format_download_history_lines()
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, "\n".join(lines))
        widget.configure(state="disabled")
        widget.see("1.0")

    def clear_download_history(self) -> None:
        from tkinter import messagebox
        should_clear = messagebox.askyesno(
            "Effacer l'historique",
            "Supprimer l'historique des liens et téléchargements enregistrés ?",
        )
        if not should_clear:
            return
        with self.download_history_lock:
            self.download_history = self._empty_download_history()
            snapshot = json.loads(json.dumps(self.download_history, ensure_ascii=False))
        self._save_download_history(snapshot)
        self._refresh_download_history_view()
        self._append_download_log("Historique des téléchargements effacé.")
