"""Backward-compatible re-exports from the package modules.

The logic has been split into focused modules:
- core.transcript_formatter: seconds_to_timestamp, minute_to_timestamp, format_transcript
- core.moment_analyzer:      keyword sets, MomentScore, scoring and export functions
- core.transcript_fetcher:   extract_video_id, fetch_transcript, generate_transcript_*
- cli:                       OUTPUT_FORMATS, build_parser, save_or_print, main
"""

from .cli import OUTPUT_FORMATS, build_parser, main, save_or_print
from .core.moment_analyzer import (
    MOMENT_CURIOSITY,
    MOMENT_KEYWORDS_LIGHT,
    MOMENT_KEYWORDS_MEDIUM,
    MOMENT_KEYWORDS_STRONG,
    MOMENT_LAUGHTER,
    MOMENT_MIN_WORDS,
    MOMENT_PHRASES_MEDIUM,
    MOMENT_PHRASES_STRONG,
    MOMENT_TRANSITIONS,
    MOST_VIEWED_DEFAULT_LIMIT,
    MOST_VIEWED_MIN_SCORE,
    NUMBER_PATTERN,
    WORD_RE,
    MomentScore,
    analyze_minute_scores,
    analyze_most_viewed_moments,
    export_most_viewed_csv,
    format_most_viewed_moments,
)
from .core.transcript_fetcher import (
    LOGGER,
    TranscriptRetrievalError,
    TranscriptResult,
    VideoIdExtractionError,
    extract_video_id,
    fetch_transcript,
    generate_transcript,
    generate_transcript_with_format,
    normalize_output_format,
    setup_logging,
)
from .core.transcript_formatter import (
    format_transcript,
    minute_to_timestamp,
    seconds_to_timestamp,
)

__all__ = [
    # cli
    "OUTPUT_FORMATS",
    "build_parser",
    "main",
    "save_or_print",
    # moment_analyzer
    "MOMENT_CURIOSITY",
    "MOMENT_KEYWORDS_LIGHT",
    "MOMENT_KEYWORDS_MEDIUM",
    "MOMENT_KEYWORDS_STRONG",
    "MOMENT_LAUGHTER",
    "MOMENT_MIN_WORDS",
    "MOMENT_PHRASES_MEDIUM",
    "MOMENT_PHRASES_STRONG",
    "MOMENT_TRANSITIONS",
    "MOST_VIEWED_DEFAULT_LIMIT",
    "MOST_VIEWED_MIN_SCORE",
    "NUMBER_PATTERN",
    "WORD_RE",
    "MomentScore",
    "analyze_minute_scores",
    "analyze_most_viewed_moments",
    "export_most_viewed_csv",
    "format_most_viewed_moments",
    # transcript_fetcher
    "LOGGER",
    "TranscriptRetrievalError",
    "TranscriptResult",
    "VideoIdExtractionError",
    "extract_video_id",
    "fetch_transcript",
    "generate_transcript",
    "generate_transcript_with_format",
    "normalize_output_format",
    "setup_logging",
    # transcript_formatter
    "format_transcript",
    "minute_to_timestamp",
    "seconds_to_timestamp",
]

if __name__ == "__main__":
    import sys

    sys.exit(main())
