"""Persistent GUI settings helpers."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .core import subtitle_renderer
from .video import presets

DOWNLOAD_LOGO_PLACEHOLDER = "/chemin/vers/logo.png"


def default_gui_settings() -> dict:
    return {
        "version": 1,
        "download_aspect_mode": "landscape",
        "video_format": "mp4",
        "clip_duration": 60,
        "download_logo_enabled": True,
        "download_logo_path": "",
        "download_logo_position": "center",
        "download_logo_size_mode": "relative",
        "download_logo_scale_percent": 58,
        "download_logo_opacity_percent": 100,
        "download_subtitles_enabled": True,
        "download_subtitle_style": "impact",
        "download_video_effect": "none",
        "download_preset": "custom",
    }


def coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def normalize_gui_settings(raw: object) -> dict:
    settings = default_gui_settings()
    if not isinstance(raw, dict):
        return settings

    mode = str(raw.get("download_aspect_mode", "")).strip().lower()
    if mode not in {"landscape", "shorts"}:
        mode = settings["download_aspect_mode"]
    settings["download_aspect_mode"] = mode

    video_format = str(raw.get("video_format", "")).strip().lower()
    if video_format not in {"mp4", "webm"}:
        video_format = settings["video_format"]
    settings["video_format"] = video_format

    try:
        clip_duration = int(raw.get("clip_duration", settings["clip_duration"]))
    except (TypeError, ValueError):
        clip_duration = settings["clip_duration"]
    settings["clip_duration"] = max(10, min(300, clip_duration))

    settings["download_logo_enabled"] = coerce_bool(
        raw.get("download_logo_enabled", settings["download_logo_enabled"]),
        settings["download_logo_enabled"],
    )

    logo_path = str(raw.get("download_logo_path", "")).strip()
    if logo_path == DOWNLOAD_LOGO_PLACEHOLDER:
        logo_path = ""
    settings["download_logo_path"] = logo_path

    logo_position = str(raw.get("download_logo_position", "")).strip().lower()
    if logo_position not in {"top", "center", "bottom"}:
        logo_position = settings["download_logo_position"]
    settings["download_logo_position"] = logo_position

    logo_size_mode = str(raw.get("download_logo_size_mode", "")).strip().lower()
    if logo_size_mode not in {"original", "relative"}:
        logo_size_mode = settings["download_logo_size_mode"]
    settings["download_logo_size_mode"] = logo_size_mode

    try:
        logo_scale_percent = int(
            raw.get(
                "download_logo_scale_percent",
                settings["download_logo_scale_percent"],
            )
        )
    except (TypeError, ValueError):
        logo_scale_percent = settings["download_logo_scale_percent"]
    settings["download_logo_scale_percent"] = max(20, min(80, logo_scale_percent))

    try:
        logo_opacity_percent = int(
            raw.get(
                "download_logo_opacity_percent",
                settings["download_logo_opacity_percent"],
            )
        )
    except (TypeError, ValueError):
        logo_opacity_percent = settings["download_logo_opacity_percent"]
    settings["download_logo_opacity_percent"] = max(10, min(100, logo_opacity_percent))

    settings["download_subtitles_enabled"] = coerce_bool(
        raw.get(
            "download_subtitles_enabled",
            settings["download_subtitles_enabled"],
        ),
        settings["download_subtitles_enabled"],
    )
    settings["download_subtitle_style"] = subtitle_renderer.normalize_subtitle_style(
        raw.get("download_subtitle_style", settings["download_subtitle_style"])
    )
    settings["download_video_effect"] = subtitle_renderer.normalize_video_effect(
        raw.get("download_video_effect", settings["download_video_effect"])
    )
    settings["download_preset"] = presets.normalize_preset_key(
        raw.get("download_preset", settings["download_preset"])
    )
    return settings


def load_gui_settings(path: Path | None, logger: logging.Logger) -> dict:
    if not isinstance(path, Path):
        return default_gui_settings()
    if not path.exists():
        return default_gui_settings()
    try:
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Impossible de lire les preferences GUI: %s", error)
        return default_gui_settings()
    return normalize_gui_settings(raw)


def save_gui_settings(
    path: Path | None, snapshot: dict, logger: logging.Logger
) -> dict:
    normalized = normalize_gui_settings(snapshot)
    if not isinstance(path, Path):
        return normalized
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(normalized, file, ensure_ascii=False, indent=2)
        temp_path.replace(path)
    except OSError as error:
        logger.warning("Impossible d'enregistrer les preferences GUI: %s", error)
    return normalized
