import csv
import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from youtube_transcript_api import CouldNotRetrieveTranscript

from youtube_script_app.base import (
    TranscriptRetrievalError,
    TranscriptResult,
    analyze_most_viewed_moments,
    extract_video_id,
    fetch_transcript,
    format_most_viewed_moments,
    format_transcript,
    seconds_to_timestamp,
)
from youtube_script_app.core import transcript_fetcher
from youtube_script_app.core.moment_analyzer import export_most_viewed_csv
from youtube_script_app.core.transcript_fetcher import setup_logging


class FakeRequestBlocked(CouldNotRetrieveTranscript):
    def __str__(self) -> str:
        return "YouTube is blocking requests from your IP."


def test_extract_video_id_watch() -> None:
    assert (
        extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )


def test_extract_video_id_short() -> None:
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_invalid() -> None:
    with pytest.raises(ValueError):
        extract_video_id("https://example.com")


def test_extract_video_id_rejects_lookalike_domain() -> None:
    with pytest.raises(ValueError):
        extract_video_id("https://notyoutube.com/watch?v=dQw4w9WgXcQ")


def test_extract_video_id_accepts_port_on_valid_domain() -> None:
    assert (
        extract_video_id("https://www.youtube.com:443/watch?v=dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )


def test_seconds_to_timestamp() -> None:
    assert seconds_to_timestamp(59) == "00:59"
    assert seconds_to_timestamp(61) == "01:01"
    assert seconds_to_timestamp(3661) == "01:01:01"


def test_format_transcript_text() -> None:
    transcript = [
        {"text": "Hello", "start": 0, "duration": 1.5},
        {"text": "World", "start": 1.2, "duration": 2.0},
    ]
    assert format_transcript(transcript, "text") == ["Hello", "World"]


def test_format_transcript_timestamps() -> None:
    transcript = [
        {"text": "Hello", "start": 0, "duration": 1.5},
        {"text": "World", "start": 1.2, "duration": 2.0},
    ]
    assert format_transcript(transcript, "text-timestamps") == [
        "[00:00] Hello",
        "[00:01] World",
    ]


def test_format_transcript_json() -> None:
    transcript = [
        {"text": "Hello", "start": 0, "duration": 1.5},
        {"text": "World", "start": 1.2, "duration": 2.0},
    ]
    output = "\n".join(format_transcript(transcript, "json"))
    data = json.loads(output)
    assert data[0]["text"] == "Hello"
    assert data[1]["text"] == "World"


def test_analyze_most_viewed_moments() -> None:
    transcript = [
        {"text": "Incroyable ! C'est dingue !!!", "start": 5, "duration": 2.0},
        {"text": "Wow secret énorme ?", "start": 20, "duration": 1.0},
        {"text": "Texte neutre", "start": 125, "duration": 1.0},
    ]
    moments = analyze_most_viewed_moments(transcript, limit=1)
    assert len(moments) == 1
    assert moments[0].minute_index == 0


def test_format_most_viewed_moments() -> None:
    transcript = [
        {"text": "Incroyable ! C'est dingue !!!", "start": 5, "duration": 2.0},
        {"text": "Wow secret énorme ?", "start": 20, "duration": 1.0},
    ]
    moments = analyze_most_viewed_moments(transcript, limit=1)
    lines = format_most_viewed_moments(moments, include_header=False)
    assert lines


def test_format_most_viewed_moments_header_is_precise() -> None:
    transcript = [
        {"text": "Incroyable secret révélation !!!", "start": 5, "duration": 2.0},
    ]
    moments = analyze_most_viewed_moments(transcript, limit=1)
    lines = format_most_viewed_moments(moments, include_header=True)
    assert lines[0] == "Moments forts estimés"


def test_setup_logging_falls_back_when_log_dir_is_unusable(tmp_path) -> None:
    logger_name = "youtube-script-test-fallback"
    logger = logging.getLogger(logger_name)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    bad_dir = tmp_path / "not-a-directory"
    bad_dir.write_text("content", encoding="utf-8")

    configured = setup_logging(log_dir=bad_dir, logger_name=logger_name)

    assert any(isinstance(handler, logging.NullHandler) for handler in configured.handlers)

    for handler in list(configured.handlers):
        configured.removeHandler(handler)


def test_fetch_transcript_wraps_retrieval_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeApi:
        @staticmethod
        def list_transcripts(video_id: str):
            raise CouldNotRetrieveTranscript(video_id)

    monkeypatch.setattr(
        "youtube_script_app.core.transcript_fetcher.YouTubeTranscriptApi",
        FakeApi,
    )
    monkeypatch.setattr(
        "youtube_script_app.core.transcript_fetcher._fetch_with_yt_dlp",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(TranscriptRetrievalError) as exc_info:
        fetch_transcript("dQw4w9WgXcQ", None)

    assert isinstance(exc_info.value.__cause__, CouldNotRetrieveTranscript)


def test_fetch_transcript_uses_proxy_config_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if transcript_fetcher.GenericProxyConfig is None:
        pytest.skip("Installed youtube-transcript-api has no proxy config support.")

    instances = []

    class FakeApi:
        def __init__(self, proxy_config=None):
            self.proxy_config = proxy_config
            instances.append(self)

        def fetch(self, video_id: str, languages=("en",), preserve_formatting=False):
            return [{"text": "Hello", "start": 0.0, "duration": 1.0}]

    monkeypatch.setenv(
        transcript_fetcher.TRANSCRIPT_HTTP_PROXY_ENV,
        "http://user:pass@example.test:8080",
    )
    monkeypatch.setattr(
        "youtube_script_app.core.transcript_fetcher.YouTubeTranscriptApi",
        FakeApi,
    )

    data, _, _ = fetch_transcript("dQw4w9WgXcQ", None)

    assert data[0]["text"] == "Hello"
    assert instances[0].proxy_config is not None
    assert instances[0].proxy_config.to_requests_dict()["http"].startswith(
        "http://user:pass@example.test"
    )


def test_fetch_transcript_falls_back_to_ytdlp_on_ip_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caption_url = "https://caption.example.test/en.json3"

    class FakeApi:
        def fetch(self, video_id: str, languages=("en",), preserve_formatting=False):
            raise FakeRequestBlocked(video_id)

    class Completed:
        returncode = 0
        stderr = ""
        stdout = json.dumps(
            {
                "subtitles": {"en": [{"ext": "json3", "url": caption_url}]},
                "automatic_captions": {},
            }
        )

    class Response:
        text = json.dumps(
            {
                "events": [
                    {
                        "tStartMs": 1200,
                        "dDurationMs": 2400,
                        "segs": [{"utf8": "Hello "}, {"utf8": "world"}],
                    }
                ]
            }
        )

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "youtube_script_app.core.transcript_fetcher.YouTubeTranscriptApi",
        FakeApi,
    )
    monkeypatch.setattr(transcript_fetcher, "_resolve_yt_dlp_cmd", lambda: ["yt-dlp"])
    monkeypatch.setattr(
        transcript_fetcher.subprocess, "run", lambda *a, **kw: Completed()
    )
    monkeypatch.setattr(transcript_fetcher.requests, "get", lambda *a, **kw: Response())

    data, used_language, available = fetch_transcript("dQw4w9WgXcQ", None)

    assert data == [{"text": "Hello world", "start": 1.2, "duration": 2.4}]
    assert used_language == "en"
    assert available == ["en"]


def test_fetch_transcript_ip_block_message_mentions_workarounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeApi:
        def fetch(self, video_id: str, languages=("en",), preserve_formatting=False):
            raise FakeRequestBlocked(video_id)

    monkeypatch.setattr(
        "youtube_script_app.core.transcript_fetcher.YouTubeTranscriptApi",
        FakeApi,
    )
    monkeypatch.setattr(transcript_fetcher, "_resolve_yt_dlp_cmd", lambda: None)

    with pytest.raises(TranscriptRetrievalError) as exc_info:
        fetch_transcript("dQw4w9WgXcQ", None)

    message = str(exc_info.value)
    assert "YouTube is blocking transcript requests" in message
    assert transcript_fetcher.TRANSCRIPT_HTTP_PROXY_ENV in message
    assert transcript_fetcher.WEBSHARE_USERNAME_ENV in message


# --- extract_video_id: formats supplémentaires ---

def test_extract_video_id_shorts() -> None:
    assert (
        extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )


def test_extract_video_id_embed() -> None:
    assert (
        extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )


def test_extract_video_id_live() -> None:
    assert (
        extract_video_id("https://www.youtube.com/live/dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )


# --- format_transcript: chunks vides ---

def test_format_transcript_skips_empty_text() -> None:
    transcript = [
        {"text": "", "start": 0, "duration": 1.0},
        {"text": "   ", "start": 1.0, "duration": 1.0},
        {"text": "Hello", "start": 2.0, "duration": 1.0},
    ]
    assert format_transcript(transcript, "text") == ["Hello"]


def test_format_transcript_json_skips_empty_text() -> None:
    transcript = [
        {"text": "", "start": 0, "duration": 1.0},
        {"text": "Hello", "start": 1.0, "duration": 1.0},
    ]
    output = "\n".join(format_transcript(transcript, "json"))
    data = json.loads(output)
    assert len(data) == 1
    assert data[0]["text"] == "Hello"


# --- export_most_viewed_csv ---

def test_export_most_viewed_csv_creates_file() -> None:
    transcript = [
        {"text": "Incroyable secret révélation !!!", "start": 5, "duration": 2.0},
        {"text": "Wow énorme scandale ?", "start": 20, "duration": 1.0},
    ]
    moments = analyze_most_viewed_moments(transcript, limit=2)
    with tempfile.NamedTemporaryFile(
        mode="r", suffix=".csv", delete=False, encoding="utf-8"
    ) as tmp:
        tmp_path = tmp.name

    export_most_viewed_csv(tmp_path, moments)

    with open(tmp_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == len(moments)
    assert set(rows[0].keys()) == {"minute", "score", "excerpt"}
    Path(tmp_path).unlink()


def test_export_most_viewed_csv_empty_moments() -> None:
    with tempfile.NamedTemporaryFile(
        mode="r", suffix=".csv", delete=False, encoding="utf-8"
    ) as tmp:
        tmp_path = tmp.name

    export_most_viewed_csv(tmp_path, [])

    with open(tmp_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert rows == []
    Path(tmp_path).unlink()


# --- main() via argv ---

def test_main_prints_transcript(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from youtube_script_app.cli import main

    fake_result = TranscriptResult(
        lines=["Hello", "World"],
        output_format="text",
        most_viewed_moments=None,
    )
    monkeypatch.setattr(
        "youtube_script_app.cli.generate_transcript_with_format",
        lambda *a, **kw: fake_result,
    )

    exit_code = main(["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Hello" in captured.out
    assert "World" in captured.out
