"""Download history persistence and formatting."""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List

from ..core.transcript_fetcher import VideoIdExtractionError, extract_video_id
from ..core.transcript_formatter import seconds_to_timestamp


def empty_download_history() -> dict:
    return {"version": 1, "links": {}}


def normalize_download_history(raw: object) -> dict:
    if not isinstance(raw, dict):
        return empty_download_history()

    raw_links = raw.get("links")
    if not isinstance(raw_links, dict):
        return empty_download_history()

    normalized_links: dict[str, dict] = {}
    for key, payload in raw_links.items():
        if not isinstance(payload, dict):
            continue
        url = str(payload.get("url", "")).strip()
        if not url:
            continue

        title = str(payload.get("title", "")).strip() or "Titre inconnu"
        video_id = str(payload.get("video_id", "")).strip()
        downloads_raw = payload.get("downloads", [])
        downloads: List[dict] = []
        if isinstance(downloads_raw, list):
            for event in downloads_raw:
                if not isinstance(event, dict):
                    continue
                downloaded_at = str(event.get("downloaded_at", "")).strip()
                if not downloaded_at:
                    continue
                try:
                    start_seconds = int(event.get("start_seconds", 0) or 0)
                except (TypeError, ValueError):
                    start_seconds = 0
                try:
                    end_seconds = int(event.get("end_seconds", 0) or 0)
                except (TypeError, ValueError):
                    end_seconds = 0
                kind = str(event.get("kind", "clip")).strip().lower()
                if kind not in {"clip", "full_video", "audio"}:
                    kind = "clip"
                downloads.append(
                    {
                        "downloaded_at": downloaded_at,
                        "output_file": str(event.get("output_file", "")).strip(),
                        "output_name": str(event.get("output_name", "")).strip(),
                        "start_seconds": start_seconds,
                        "end_seconds": end_seconds,
                        "format": str(event.get("format", "")).strip(),
                        "kind": kind,
                        "shorts": bool(event.get("shorts", False)),
                        "logo": bool(event.get("logo", False)),
                    }
                )
        downloads.sort(key=lambda row: row["downloaded_at"], reverse=True)
        normalized_links[str(key)] = {
            "url": url,
            "video_id": video_id,
            "title": title,
            "downloads": downloads,
            "first_downloaded_at": str(
                payload.get("first_downloaded_at", "")
            ).strip(),
            "last_downloaded_at": str(payload.get("last_downloaded_at", "")).strip(),
        }
    return {"version": 1, "links": normalized_links}


def load_download_history(path: Path | None, logger: logging.Logger) -> dict:
    if not isinstance(path, Path):
        return empty_download_history()
    if not path.exists():
        return empty_download_history()
    try:
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Impossible de lire l'historique des telechargements: %s", error)
        return empty_download_history()
    return normalize_download_history(raw)


def save_download_history(
    path: Path | None, snapshot: dict, logger: logging.Logger
) -> None:
    if not isinstance(path, Path):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(snapshot, file, ensure_ascii=False, indent=2)
        temp_path.replace(path)
    except OSError as error:
        logger.warning(
            "Impossible d'enregistrer l'historique des telechargements: %s", error
        )


def history_key_for_url(url: str) -> tuple[str, str]:
    try:
        video_id = extract_video_id(url)
        return f"video:{video_id}", video_id
    except VideoIdExtractionError:
        return f"url:{url}", ""


def format_history_timestamp(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def add_download_record(
    history: dict,
    item: dict,
    final_path: Path,
    *,
    video_title_cache: dict[str, str] | None = None,
    now: str | None = None,
) -> dict:
    url = str(item.get("url", "")).strip()
    if not url:
        return copy.deepcopy(history)

    key, video_id = history_key_for_url(url)
    timestamp = now or datetime.now().astimezone().isoformat(timespec="seconds")
    start = int(item.get("start", 0) or 0)
    duration = int(item.get("duration", 0) or 0)
    end = start + max(duration, 0)
    title = str(item.get("video_title", "")).strip()
    if not title:
        cache = video_title_cache or {}
        title = str(cache.get(url, "")).strip() or "Titre inconnu"
    kind = str(item.get("kind", "clip")).strip().lower()
    if kind not in {"clip", "full_video", "audio"}:
        kind = "clip"

    entry = {
        "downloaded_at": timestamp,
        "output_file": str(final_path),
        "output_name": final_path.name,
        "start_seconds": start,
        "end_seconds": end,
        "format": str(item.get("format", "")).strip(),
        "kind": kind,
        "shorts": bool(item.get("shorts", False)),
        "logo": bool(item.get("logo_enabled") and item.get("logo_path")),
    }

    links = history.setdefault("links", {})
    history_row = links.get(key)
    if not isinstance(history_row, dict):
        history_row = {
            "url": url,
            "video_id": video_id,
            "title": title,
            "downloads": [],
            "first_downloaded_at": timestamp,
            "last_downloaded_at": timestamp,
        }
        links[key] = history_row
    else:
        history_row["url"] = url
        if video_id:
            history_row["video_id"] = video_id
        if title and title != "Titre inconnu":
            history_row["title"] = title
        if not history_row.get("first_downloaded_at"):
            history_row["first_downloaded_at"] = timestamp
        history_row["last_downloaded_at"] = timestamp

    downloads = history_row.setdefault("downloads", [])
    downloads.insert(0, entry)
    del downloads[200:]

    if len(links) > 300:
        ordered = sorted(
            links.items(),
            key=lambda row: str(row[1].get("last_downloaded_at", "")),
            reverse=True,
        )[:300]
        history["links"] = dict(ordered)
    return copy.deepcopy(history)


def format_download_history_lines(history: dict) -> List[str]:
    links = dict(history.get("links", {}))
    if not links:
        return ["Aucun téléchargement enregistré pour le moment."]

    ordered_links = sorted(
        links.values(),
        key=lambda row: str(row.get("last_downloaded_at", "")),
        reverse=True,
    )
    lines: List[str] = []
    for index, row in enumerate(ordered_links, start=1):
        title = str(row.get("title", "")).strip() or "Titre inconnu"
        url = str(row.get("url", "")).strip()
        downloads = row.get("downloads", [])
        if not isinstance(downloads, list):
            downloads = []
        last = downloads[0] if downloads else {}
        last_when = format_history_timestamp(str(last.get("downloaded_at", "")))

        lines.append(f"{index}. {title}")
        if url:
            lines.append(f"   URL: {url}")
        if last_when:
            lines.append(
                f"   Dernier téléchargement: {last_when} • Total: {len(downloads)}"
            )
        else:
            lines.append(f"   Total téléchargements: {len(downloads)}")

        for event in downloads[:6]:
            try:
                start = int(event.get("start_seconds", 0) or 0)
            except (TypeError, ValueError):
                start = 0
            try:
                end = int(event.get("end_seconds", 0) or 0)
            except (TypeError, ValueError):
                end = 0
            ts = format_history_timestamp(str(event.get("downloaded_at", "")))
            file_name = str(event.get("output_name", "")).strip() or "fichier inconnu"
            video_format = str(event.get("format", "")).strip() or "format inconnu"
            kind = str(event.get("kind", "clip")).strip().lower()
            variants: List[str] = []
            if kind == "audio":
                segment = "audio seul"
            elif kind == "full_video":
                segment = "vidéo entière"
            else:
                segment = f"{seconds_to_timestamp(start)} → {seconds_to_timestamp(end)}"
                if event.get("shorts"):
                    variants.append("Short 9:16")
                if event.get("logo"):
                    variants.append("logo")
            variant_label = f" • {', '.join(variants)}" if variants else ""
            lines.append(
                f"   - {ts} • {segment} • {file_name} • {video_format}{variant_label}"
            )
        remaining = len(downloads) - 6
        if remaining > 0:
            lines.append(f"   ... {remaining} téléchargement(s) plus ancien(s)")
        lines.append("")

    while lines and not lines[-1].strip():
        lines.pop()
    return lines
