"""YouTube transcript retrieval logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence
from urllib.parse import parse_qs, urlparse

from requests.exceptions import RequestException
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)

from .moment_analyzer import (
    MOST_VIEWED_DEFAULT_LIMIT,
    MomentScore,
    analyze_most_viewed_moments,
)
from .transcript_formatter import format_transcript


class VideoIdExtractionError(ValueError):
    """Raised when a YouTube video ID cannot be extracted from the URL."""


class TranscriptRetrievalError(RuntimeError):
    """Raised when fetching the transcript fails for recoverable reasons."""


@dataclass
class TranscriptResult:
    lines: List[str]
    raw_transcript: List[dict] | None = None
    used_language: str | None = None
    available_languages: List[str] | None = None
    output_format: str = "text"
    most_viewed_moments: List[MomentScore] | None = None


def setup_logging(
    log_dir: Path | None = None,
    logger_name: str = "youtube-script",
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    target_dir = log_dir or Path.home() / ".youtube-script"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        log_file = target_dir / "app.log"
        handler: logging.Handler = logging.FileHandler(log_file, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
    except OSError:
        handler = logging.NullHandler()

    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


LOGGER = setup_logging()


def extract_video_id(url: str) -> str:
    """Return the YouTube video ID contained in the provided URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if host == "youtu.be" or host.endswith(".youtu.be"):
        video_id = path.lstrip("/").split("/")[0]
        if not video_id:
            raise VideoIdExtractionError("Missing video identifier in shortened URL.")
        return video_id

    if host == "youtube.com" or host.endswith(".youtube.com"):
        if path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            if not video_id:
                raise VideoIdExtractionError("Parameter 'v' not found in watch URL.")
            return video_id
        if path.startswith(("/shorts/", "/embed/", "/live/")):
            parts = path.split("/")
            video_id = parts[2] if len(parts) >= 3 else ""
            if not video_id:
                raise VideoIdExtractionError(
                    "Unable to parse video identifier from the provided URL."
                )
            return video_id

    raise VideoIdExtractionError(
        "The provided URL does not appear to be a valid YouTube video link."
    )


def _normalize_languages(languages: Sequence[str] | None) -> List[str] | None:
    return list(dict.fromkeys(languages)) if languages else None


def _available_languages_from_list(transcript_list: Iterable) -> List[str]:
    return [item.language_code for item in transcript_list]


def _fetch_with_list_api(
    video_id: str, preferred_languages: List[str] | None
) -> tuple[List[dict], str | None, List[str] | None]:
    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    available_languages = _available_languages_from_list(transcript_list)

    if preferred_languages:
        transcript = transcript_list.find_transcript(preferred_languages)
    else:
        transcript = transcript_list.find_transcript(available_languages)

    fetched = transcript.fetch()
    data = fetched if isinstance(fetched, list) else fetched.to_raw_data()
    return data, getattr(transcript, "language_code", None), available_languages


def _fetch_with_instance_api(
    video_id: str, preferred_languages: List[str] | None
) -> tuple[List[dict], str | None, List[str] | None]:
    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(
            video_id,
            languages=preferred_languages or ("en",),
        )
    except NoTranscriptFound:
        if preferred_languages:
            raise
        transcript_list = api.list(video_id)
        available_languages = _available_languages_from_list(transcript_list)
        if not available_languages:
            raise
        transcript = transcript_list.find_transcript(available_languages)
        fetched = transcript.fetch()
        data = fetched if isinstance(fetched, list) else fetched.to_raw_data()
        return data, getattr(transcript, "language_code", None), available_languages

    data = fetched if isinstance(fetched, list) else fetched.to_raw_data()
    return data, None, None


def _try_list_languages(video_id: str) -> List[str] | None:
    try:
        if hasattr(YouTubeTranscriptApi, "list_transcripts"):
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            return _available_languages_from_list(transcript_list)
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        return _available_languages_from_list(transcript_list)
    except Exception:
        LOGGER.debug("Could not list available languages for video %s", video_id)
        return None


def fetch_transcript(
    video_id: str, languages: Sequence[str] | None
) -> tuple[List[dict], str | None, List[str] | None]:
    """Fetch the YouTube transcript data for the given video identifier."""
    preferred_languages = _normalize_languages(languages)

    try:
        if hasattr(YouTubeTranscriptApi, "list_transcripts"):
            return _fetch_with_list_api(video_id, preferred_languages)

        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            if preferred_languages:
                data = YouTubeTranscriptApi.get_transcript(
                    video_id, languages=preferred_languages
                )
            else:
                data = YouTubeTranscriptApi.get_transcript(video_id)
            return data, None, None

        return _fetch_with_instance_api(video_id, preferred_languages)
    except TranscriptsDisabled as exc:
        LOGGER.exception("Transcripts disabled for video %s", video_id)
        raise TranscriptRetrievalError(
            "Transcripts are disabled for this video."
        ) from exc
    except NoTranscriptFound as exc:
        available = _try_list_languages(video_id)
        if languages:
            message = "No transcript found for the specified languages."
            if available:
                message = f"{message} Available languages: {', '.join(available)}."
        else:
            message = "No transcript is available for this video."
            if available:
                message = f"{message} Available languages: {', '.join(available)}."
        LOGGER.warning("No transcript found for %s (languages=%s)", video_id, languages)
        raise TranscriptRetrievalError(message) from exc
    except RequestException as exc:
        LOGGER.exception("Network error while fetching transcript for %s", video_id)
        raise TranscriptRetrievalError(
            "Unable to reach YouTube. Check your network connection."
        ) from exc
    except CouldNotRetrieveTranscript as exc:
        LOGGER.exception("Transcript retrieval failed for video %s", video_id)
        message = str(exc).strip() or "Unable to retrieve transcript for this video."
        raise TranscriptRetrievalError(message) from exc
    except YouTubeTranscriptApiException as exc:
        LOGGER.exception("Unexpected transcript API error for video %s", video_id)
        message = str(exc).strip() or "Unexpected transcript API error."
        raise TranscriptRetrievalError(message) from exc


def normalize_output_format(
    output_format: str | None, include_timestamps: bool
) -> str:
    if output_format:
        return output_format
    return "text-timestamps" if include_timestamps else "text"


def generate_transcript(
    url: str,
    *,
    languages: Sequence[str] | None = None,
    include_timestamps: bool = False,
) -> List[str]:
    """High-level helper to generate formatted transcript lines."""
    output_format = normalize_output_format(None, include_timestamps)
    result = generate_transcript_with_format(
        url, languages=languages, output_format=output_format
    )
    return result.lines


def generate_transcript_with_format(
    url: str,
    *,
    languages: Sequence[str] | None = None,
    output_format: str = "text",
    include_most_viewed_moments: bool = False,
    most_viewed_limit: int = MOST_VIEWED_DEFAULT_LIMIT,
) -> TranscriptResult:
    """Generate a transcript with output format metadata."""
    video_id = extract_video_id(url)
    transcript, used_language, available_languages = fetch_transcript(
        video_id, languages
    )
    most_viewed = (
        analyze_most_viewed_moments(transcript, limit=most_viewed_limit)
        if include_most_viewed_moments
        else None
    )
    lines = format_transcript(transcript, output_format)
    return TranscriptResult(
        lines=lines,
        raw_transcript=transcript,
        used_language=used_language,
        available_languages=available_languages,
        output_format=output_format,
        most_viewed_moments=most_viewed,
    )
