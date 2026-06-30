"""Command-line interface for the YouTube transcript tool."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Sequence

from .core.moment_analyzer import MOST_VIEWED_DEFAULT_LIMIT, format_most_viewed_moments
from .core.transcript_fetcher import (
    TranscriptRetrievalError,
    VideoIdExtractionError,
    generate_transcript_with_format,
    normalize_output_format,
)

OUTPUT_FORMATS = {
    "text": "Texte brut",
    "text-timestamps": "Texte avec horodatages",
    "json": "JSON simple",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the script (transcript) of a YouTube video."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="YouTube URL (e.g. https://youtu.be/dQw4w9WgXcQ). Prompted if omitted.",
    )
    parser.add_argument(
        "-l",
        "--language",
        action="append",
        dest="languages",
        default=None,
        help=(
            "Preferred language code for the transcript. "
            "Can be provided multiple times (e.g. -l fr -l en). "
            "If omitted the default language returned by YouTube is used."
        ),
    )
    parser.add_argument(
        "-t",
        "--timestamps",
        action="store_true",
        help="Include timestamps with each transcript line.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=OUTPUT_FORMATS.keys(),
        help="Output format: text, text-timestamps, or json.",
    )
    parser.add_argument(
        "--most-viewed",
        nargs="?",
        type=int,
        const=MOST_VIEWED_DEFAULT_LIMIT,
        default=0,
        help=(
            "Include estimated highlight moments (by minute). "
            "Optionally provide a limit (default: 5)."
        ),
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        help="Export estimated highlight moments to a CSV file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Optional path to save the generated script. Prints to stdout otherwise.",
    )
    return parser


def save_or_print(lines: Sequence[str], output_path: str | None) -> None:
    content = "\n".join(lines)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as file:
            file.write(content)
    else:
        print(content)


def main(argv: Sequence[str] | None = None) -> int:
    from .core.moment_analyzer import export_most_viewed_csv

    parser = build_parser()
    args = parser.parse_args(argv)

    url = args.url or input("Enter the YouTube video URL: ").strip()
    if not url:
        parser.error("A YouTube video URL is required.")

    try:
        output_format = normalize_output_format(args.format, args.timestamps)
        result = generate_transcript_with_format(
            url,
            languages=args.languages,
            output_format=output_format,
            include_most_viewed_moments=bool(args.most_viewed) or bool(args.csv),
            most_viewed_limit=args.most_viewed or MOST_VIEWED_DEFAULT_LIMIT,
        )
    except (VideoIdExtractionError, TranscriptRetrievalError) as error:
        parser.error(str(error))

    lines = result.lines
    include_most_viewed = (
        bool(args.most_viewed) and result.most_viewed_moments is not None
    )

    if output_format == "json" and include_most_viewed:
        transcript_payload = json.loads("\n".join(result.lines))
        payload = {
            "transcript": transcript_payload,
            "most_viewed": [
                moment.to_dict() for moment in result.most_viewed_moments or []
            ],
        }
        lines = json.dumps(payload, ensure_ascii=False, indent=2).splitlines()
    elif include_most_viewed:
        blocks: List[str] = []
        blocks.extend(
            format_most_viewed_moments(
                result.most_viewed_moments or [], include_header=True
            )
        )
        blocks.append("")
        blocks.extend(["Transcription", "-" * 30])
        blocks.extend(result.lines)
        lines = blocks

    save_or_print(lines, args.output)
    if args.csv:
        export_most_viewed_csv(args.csv, result.most_viewed_moments or [])
    if args.languages and result.used_language:
        print(f"Langue utilisée: {result.used_language}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
