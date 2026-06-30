"""Creative preset definitions for clip rendering."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_PRESET = "custom"


@dataclass(frozen=True)
class CreativePreset:
    key: str
    label: str
    aspect_mode: str
    subtitles_enabled: bool
    subtitle_style: str
    video_effect: str
    clip_duration: int | None = None


PRESETS = {
    "custom": CreativePreset(
        key="custom",
        label="Personnalisé",
        aspect_mode="landscape",
        subtitles_enabled=True,
        subtitle_style="impact",
        video_effect="none",
    ),
    "tiktok_viral": CreativePreset(
        key="tiktok_viral",
        label="TikTok Viral",
        aspect_mode="shorts",
        subtitles_enabled=True,
        subtitle_style="impact",
        video_effect="contrast",
        clip_duration=45,
    ),
    "podcast_clip": CreativePreset(
        key="podcast_clip",
        label="Podcast Clip",
        aspect_mode="shorts",
        subtitles_enabled=True,
        subtitle_style="box",
        video_effect="none",
        clip_duration=60,
    ),
    "cinematic_bw": CreativePreset(
        key="cinematic_bw",
        label="Cinéma N&B",
        aspect_mode="landscape",
        subtitles_enabled=True,
        subtitle_style="cinema",
        video_effect="black_white",
        clip_duration=60,
    ),
    "documentary": CreativePreset(
        key="documentary",
        label="Documentaire",
        aspect_mode="landscape",
        subtitles_enabled=True,
        subtitle_style="minimal",
        video_effect="cinematic",
        clip_duration=90,
    ),
    "gaming": CreativePreset(
        key="gaming",
        label="Gaming Punch",
        aspect_mode="shorts",
        subtitles_enabled=True,
        subtitle_style="modern",
        video_effect="vintage",
        clip_duration=35,
    ),
}


def normalize_preset_key(value: object) -> str:
    key = str(value or "").strip().lower()
    return key if key in PRESETS else DEFAULT_PRESET


def preset_labels() -> list[str]:
    return [preset.label for preset in PRESETS.values()]


def preset_label_lookup() -> dict[str, str]:
    return {preset.label: key for key, preset in PRESETS.items()}


def preset_by_key(value: object) -> CreativePreset:
    return PRESETS[normalize_preset_key(value)]
