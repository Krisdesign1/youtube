"""Transcript formatting utilities."""

from __future__ import annotations

import json
from typing import Iterable, List


def seconds_to_timestamp(seconds: float) -> str:
    total_seconds = int(round(seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"


def minute_to_timestamp(minute_index: int) -> str:
    return seconds_to_timestamp(minute_index * 60)


def format_transcript(transcript: Iterable[dict], output_format: str) -> List[str]:
    """Format transcript entries into human-readable lines."""
    if output_format == "json":
        payload = []
        for chunk in transcript:
            text = chunk.get("text", "").replace("\n", " ").strip()
            if not text:
                continue
            payload.append(
                {
                    "start": chunk.get("start", 0.0),
                    "duration": chunk.get("duration", 0.0),
                    "text": text,
                }
            )
        json_text = json.dumps(payload, ensure_ascii=False, indent=2)
        return json_text.splitlines()

    include_timestamps = output_format == "text-timestamps"
    lines: List[str] = []
    for chunk in transcript:
        text = chunk.get("text", "").replace("\n", " ").strip()
        if not text:
            continue
        if include_timestamps:
            timestamp = seconds_to_timestamp(chunk.get("start", 0.0))
            lines.append(f"[{timestamp}] {text}")
        else:
            lines.append(text)
    return lines
