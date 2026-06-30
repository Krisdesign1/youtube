"""YouTube transcript retrieval logic."""

from __future__ import annotations

import html
import importlib.util
import inspect
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Sequence
from urllib.parse import parse_qs, urlparse

import requests
from requests.exceptions import RequestException
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)

try:  # youtube-transcript-api >= 1.0
    from youtube_transcript_api import IpBlocked, RequestBlocked
except ImportError:  # pragma: no cover - exercised only with older dependency versions
    IpBlocked = RequestBlocked = None  # type: ignore[assignment]

try:  # youtube-transcript-api >= 1.0
    from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig
except ImportError:  # pragma: no cover - exercised only with older dependency versions
    GenericProxyConfig = WebshareProxyConfig = None  # type: ignore[assignment]

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

TRANSCRIPT_HTTP_PROXY_ENV = "YOUTUBE_SCRIPT_TRANSCRIPT_HTTP_PROXY"
TRANSCRIPT_HTTPS_PROXY_ENV = "YOUTUBE_SCRIPT_TRANSCRIPT_HTTPS_PROXY"
WEBSHARE_USERNAME_ENV = "YOUTUBE_SCRIPT_TRANSCRIPT_WEBSHARE_USERNAME"
WEBSHARE_PASSWORD_ENV = "YOUTUBE_SCRIPT_TRANSCRIPT_WEBSHARE_PASSWORD"
WEBSHARE_LOCATIONS_ENV = "YOUTUBE_SCRIPT_TRANSCRIPT_WEBSHARE_LOCATIONS"
WEBSHARE_RETRIES_ENV = "YOUTUBE_SCRIPT_TRANSCRIPT_WEBSHARE_RETRIES"

YTDLP_TIMEOUT_SECONDS = 45
CAPTION_DOWNLOAD_TIMEOUT_SECONDS = 30
CAPTION_WHITESPACE_RE = re.compile(r"\s+")
BLOCKED_TRANSCRIPT_ERRORS = tuple(
    error_type
    for error_type in (RequestBlocked, IpBlocked)
    if isinstance(error_type, type)
)


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


def _env_value(name: str) -> str:
    return os.environ.get(name, "").strip()


def _parse_env_list(value: str) -> List[str]:
    return [item for item in re.split(r"[\s,;]+", value.strip()) if item]


def _parse_positive_int(value: str, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _generic_proxy_dict_from_env() -> dict[str, str] | None:
    proxies: dict[str, str] = {}
    http_url = _env_value(TRANSCRIPT_HTTP_PROXY_ENV)
    https_url = _env_value(TRANSCRIPT_HTTPS_PROXY_ENV)
    if http_url:
        proxies["http"] = http_url
    if https_url:
        proxies["https"] = https_url
    return proxies or None


def _transcript_proxy_config_from_env() -> Any | None:
    webshare_username = _env_value(WEBSHARE_USERNAME_ENV)
    webshare_password = _env_value(WEBSHARE_PASSWORD_ENV)
    if webshare_username and webshare_password and WebshareProxyConfig is not None:
        locations = _parse_env_list(_env_value(WEBSHARE_LOCATIONS_ENV))
        retries = _parse_positive_int(_env_value(WEBSHARE_RETRIES_ENV), 10)
        return WebshareProxyConfig(
            proxy_username=webshare_username,
            proxy_password=webshare_password,
            filter_ip_locations=locations or None,
            retries_when_blocked=retries,
        )

    proxies = _generic_proxy_dict_from_env()
    if proxies and GenericProxyConfig is not None:
        return GenericProxyConfig(
            http_url=proxies.get("http"),
            https_url=proxies.get("https"),
        )
    return None


def _requests_proxy_dict_from_env() -> dict[str, str] | None:
    proxy_config = _transcript_proxy_config_from_env()
    if proxy_config is not None and hasattr(proxy_config, "to_requests_dict"):
        return proxy_config.to_requests_dict()
    return _generic_proxy_dict_from_env()


def _yt_dlp_proxy_url_from_env() -> str | None:
    proxies = _requests_proxy_dict_from_env() or {}
    return proxies.get("https") or proxies.get("http")


def _supports_keyword(callable_obj: Any, keyword: str) -> bool:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return False
    return keyword in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _call_with_optional_proxies(callable_obj: Any, *args: Any, **kwargs: Any) -> Any:
    proxies = _generic_proxy_dict_from_env()
    if proxies and _supports_keyword(callable_obj, "proxies"):
        kwargs = {**kwargs, "proxies": proxies}
    return callable_obj(*args, **kwargs)


def _create_youtube_transcript_api() -> Any:
    proxy_config = _transcript_proxy_config_from_env()
    if proxy_config is None:
        return YouTubeTranscriptApi()
    try:
        return YouTubeTranscriptApi(proxy_config=proxy_config)
    except TypeError:
        LOGGER.debug("Installed youtube-transcript-api does not accept proxy_config")
        return YouTubeTranscriptApi()


def _fetch_with_list_api(
    video_id: str, preferred_languages: List[str] | None
) -> tuple[List[dict], str | None, List[str] | None]:
    transcript_list = _call_with_optional_proxies(
        YouTubeTranscriptApi.list_transcripts, video_id
    )
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
    api = _create_youtube_transcript_api()
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
            transcript_list = _call_with_optional_proxies(
                YouTubeTranscriptApi.list_transcripts, video_id
            )
            return _available_languages_from_list(transcript_list)
        api = _create_youtube_transcript_api()
        transcript_list = api.list(video_id)
        return _available_languages_from_list(transcript_list)
    except Exception:
        LOGGER.debug("Could not list available languages for video %s", video_id)
        return None


def _resolve_yt_dlp_cmd() -> List[str] | None:
    path = shutil.which("yt-dlp")
    if path:
        return [path]
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    return None


def _load_ytdlp_video_info(video_id: str) -> dict[str, Any] | None:
    yt_dlp_cmd = _resolve_yt_dlp_cmd()
    if yt_dlp_cmd is None:
        return None

    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        *yt_dlp_cmd,
        "--no-playlist",
        "--skip-download",
        "--dump-json",
        "--no-warnings",
    ]
    proxy_url = _yt_dlp_proxy_url_from_env()
    if proxy_url:
        cmd.extend(["--proxy", proxy_url])
    cmd.append(url)
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=YTDLP_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        LOGGER.warning("yt-dlp subtitle fallback failed for %s: %s", video_id, error)
        return None

    if completed.returncode != 0:
        stderr = completed.stderr.strip().splitlines()
        detail = stderr[-1] if stderr else "yt-dlp exited with an error"
        LOGGER.warning("yt-dlp subtitle fallback failed for %s: %s", video_id, detail)
        return None

    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                LOGGER.debug("yt-dlp returned invalid JSON for %s", video_id)
                return None
            return data if isinstance(data, dict) else None
    return None


def _unique_languages(languages: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    unique: List[str] = []
    for language in languages:
        normalized = str(language or "").strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def _caption_language_matches(candidate: str, preferred: str) -> bool:
    candidate = candidate.lower()
    preferred = preferred.lower()
    return candidate == preferred or candidate.split("-")[0] == preferred.split("-")[0]


def _caption_sources(info: dict[str, Any]) -> List[tuple[str, dict]]:
    sources: List[tuple[str, dict]] = []
    for source_name in ("subtitles", "automatic_captions"):
        source = info.get(source_name)
        if isinstance(source, dict):
            sources.append((source_name, source))
    return sources


def _available_ytdlp_languages(info: dict[str, Any]) -> List[str]:
    languages: List[str] = []
    for _, source in _caption_sources(info):
        languages.extend(str(language) for language in source.keys())
    return _unique_languages(languages)


def _choose_ytdlp_caption_entry(entries: object) -> dict[str, Any] | None:
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        if str(entry.get("ext", "")).lower() == "json3":
            return entry
    return None


def _pick_ytdlp_caption(
    info: dict[str, Any], preferred_languages: List[str] | None
) -> tuple[str, dict[str, Any]] | None:
    sources = _caption_sources(info)
    if not sources:
        return None

    if preferred_languages:
        for preferred in preferred_languages:
            for _, source in sources:
                for language, entries in source.items():
                    if not _caption_language_matches(str(language), preferred):
                        continue
                    entry = _choose_ytdlp_caption_entry(entries)
                    if entry is not None:
                        return str(language), entry
        return None

    for preferred in ("en", "en-US", "en-orig"):
        for _, source in sources:
            for language, entries in source.items():
                if not _caption_language_matches(str(language), preferred):
                    continue
                entry = _choose_ytdlp_caption_entry(entries)
                if entry is not None:
                    return str(language), entry

    for _, source in sources:
        for language, entries in source.items():
            entry = _choose_ytdlp_caption_entry(entries)
            if entry is not None:
                return str(language), entry
    return None


def _clean_caption_text(text: str) -> str:
    text = html.unescape(str(text or ""))
    text = text.replace("\ufeff", "").replace("\u200b", "")
    return CAPTION_WHITESPACE_RE.sub(" ", text).strip()


def _milliseconds_to_seconds(value: object) -> float:
    try:
        return float(value or 0) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def _parse_json3_caption(payload: str) -> List[dict]:
    data = json.loads(payload)
    events = data.get("events", []) if isinstance(data, dict) else []
    chunks: List[dict] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        segments = event.get("segs") or []
        text = "".join(
            str(segment.get("utf8", ""))
            for segment in segments
            if isinstance(segment, dict)
        )
        cleaned = _clean_caption_text(text)
        if not cleaned:
            continue
        start = _milliseconds_to_seconds(event.get("tStartMs", 0))
        duration = _milliseconds_to_seconds(event.get("dDurationMs", 0))
        chunks.append({"text": cleaned, "start": start, "duration": duration})
    return chunks


def _download_ytdlp_caption(entry: dict[str, Any]) -> List[dict]:
    url = str(entry.get("url", "")).strip()
    if not url:
        return []
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            proxies=_requests_proxy_dict_from_env(),
            timeout=CAPTION_DOWNLOAD_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except RequestException as error:
        LOGGER.warning("Could not download yt-dlp caption file: %s", error)
        return []

    try:
        return _parse_json3_caption(response.text)
    except (json.JSONDecodeError, ValueError) as error:
        LOGGER.debug("Could not parse yt-dlp json3 caption payload: %s", error)
        return []


def _fetch_with_yt_dlp(
    video_id: str, preferred_languages: List[str] | None
) -> tuple[List[dict], str | None, List[str] | None] | None:
    info = _load_ytdlp_video_info(video_id)
    if info is None:
        return None

    selected = _pick_ytdlp_caption(info, preferred_languages)
    if selected is None:
        return None

    language, entry = selected
    transcript = _download_ytdlp_caption(entry)
    if not transcript:
        return None

    available_languages = _available_ytdlp_languages(info)
    LOGGER.info("Fetched transcript for %s via yt-dlp subtitle fallback", video_id)
    return transcript, language, available_languages


def _is_ip_blocked_error(exc: BaseException) -> bool:
    if BLOCKED_TRANSCRIPT_ERRORS and isinstance(exc, BLOCKED_TRANSCRIPT_ERRORS):
        return True
    return "YouTube is blocking requests from your IP" in str(exc)


def _ip_block_message() -> str:
    return (
        "YouTube is blocking transcript requests from this network. "
        "Try again later, switch networks/VPN, install yt-dlp for the subtitle "
        "fallback, or configure a rotating residential proxy. "
        f"Generic proxy env vars: {TRANSCRIPT_HTTP_PROXY_ENV}, "
        f"{TRANSCRIPT_HTTPS_PROXY_ENV}. Webshare env vars: "
        f"{WEBSHARE_USERNAME_ENV}, {WEBSHARE_PASSWORD_ENV}. "
        "Upstream guidance: "
        "https://github.com/jdepoix/youtube-transcript-api?tab=readme-ov-file"
        "#working-around-ip-bans-requestblocked-or-ipblocked-exception"
    )


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
                data = _call_with_optional_proxies(
                    YouTubeTranscriptApi.get_transcript,
                    video_id,
                    languages=preferred_languages,
                )
            else:
                data = _call_with_optional_proxies(
                    YouTubeTranscriptApi.get_transcript, video_id
                )
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
        fallback = _fetch_with_yt_dlp(video_id, preferred_languages)
        if fallback is not None:
            return fallback
        LOGGER.exception("Transcript retrieval failed for video %s", video_id)
        if _is_ip_blocked_error(exc):
            raise TranscriptRetrievalError(_ip_block_message()) from exc
        message = str(exc).strip() or "Unable to retrieve transcript for this video."
        raise TranscriptRetrievalError(message) from exc
    except YouTubeTranscriptApiException as exc:
        fallback = _fetch_with_yt_dlp(video_id, preferred_languages)
        if fallback is not None:
            return fallback
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
