"""Heuristic scoring of transcript moments by minute."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from typing import Iterable, List

from .transcript_formatter import minute_to_timestamp

MOMENT_KEYWORDS_STRONG = {
    "incroyable",
    "dingue",
    "ouf",
    "impossible",
    "révélation",
    "secret",
    "scandale",
    "choc",
    "énorme",
    "bombe",
    "catastrophe",
    "record",
    "inédit",
    "exclusif",
    "jamais",
    "amazing",
    "insane",
    "crazy",
    "shocking",
    "unbelievable",
}
MOMENT_KEYWORDS_MEDIUM = {
    "astuce",
    "hack",
    "top",
    "meilleur",
    "meilleure",
    "pire",
    "résultat",
    "preuve",
    "avant",
    "après",
    "erreur",
    "attention",
    "alerte",
    "dangereux",
    "important",
    "test",
    "comparaison",
    "surprise",
}
MOMENT_KEYWORDS_LIGHT = {
    "simple",
    "facile",
    "rapide",
    "nouveau",
    "gratuit",
    "guide",
    "démo",
    "tips",
    "astuces",
    "pro",
}
MOMENT_PHRASES_STRONG = {
    "tu ne vas pas croire",
    "vous n'allez pas croire",
    "tu vas voir",
    "vous allez voir",
    "plot twist",
    "attends",
    "regarde bien",
    "écoute bien",
    "no way",
}
MOMENT_PHRASES_MEDIUM = {
    "le meilleur",
    "le pire",
    "c'est parti",
    "en bref",
    "voici",
    "regarde",
    "écoute",
}
MOMENT_CURIOSITY = {
    "pourquoi",
    "comment",
    "quoi",
    "what",
    "why",
    "how",
}
MOMENT_TRANSITIONS = {"mais", "sauf", "pourtant", "or", "par contre"}
MOMENT_LAUGHTER = {"lol", "haha", "mdr", "lmao"}
MOMENT_MIN_WORDS = 8
MOST_VIEWED_DEFAULT_LIMIT = 5
MOST_VIEWED_MIN_SCORE = 5
WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)
NUMBER_PATTERN = re.compile(r"\b(top\s*)?\d+\b", re.IGNORECASE)


@dataclass
class MomentScore:
    minute_index: int
    score: int
    excerpt: str

    def to_dict(self) -> dict:
        return {
            "minute": minute_to_timestamp(self.minute_index),
            "score": self.score,
            "excerpt": self.excerpt,
        }


def _tokenize(text: str) -> List[str]:
    return WORD_RE.findall(text)


def _count_phrases(text: str, phrases: set[str]) -> int:
    return sum(text.count(phrase) for phrase in phrases)


def analyze_minute_scores(transcript: Iterable[dict]) -> List[MomentScore]:
    buckets: dict[int, List[str]] = {}
    for chunk in transcript:
        text = chunk.get("text", "").replace("\n", " ").strip()
        if not text:
            continue
        minute_index = int(chunk.get("start", 0.0) // 60)
        buckets.setdefault(minute_index, []).append(text)

    moments: List[MomentScore] = []
    for minute_index, texts in sorted(buckets.items()):
        combined = " ".join(texts)
        lower_text = combined.lower()
        tokens = _tokenize(lower_text)
        word_count = len(tokens)

        punctuation_hits = combined.count("!") + combined.count("?")
        keyword_score = 0
        keyword_score += sum(4 for token in tokens if token in MOMENT_KEYWORDS_STRONG)
        keyword_score += sum(2 for token in tokens if token in MOMENT_KEYWORDS_MEDIUM)
        keyword_score += sum(1 for token in tokens if token in MOMENT_KEYWORDS_LIGHT)
        laughter_hits = sum(1 for token in tokens if token in MOMENT_LAUGHTER)
        uppercase_hits = sum(
            1 for token in _tokenize(combined) if token.isupper() and len(token) >= 3
        )
        phrase_score = _count_phrases(lower_text, MOMENT_PHRASES_STRONG) * 4
        phrase_score += _count_phrases(lower_text, MOMENT_PHRASES_MEDIUM) * 2
        curiosity_hits = sum(1 for token in tokens if token in MOMENT_CURIOSITY)
        transition_hits = sum(1 for token in tokens if token in MOMENT_TRANSITIONS)
        number_hits = len(NUMBER_PATTERN.findall(lower_text))

        # Density normalization: keyword scores scale linearly with word count,
        # which unfairly boosts long minutes. Normalize to a 60-word reference.
        density_factor = 60.0 / max(word_count, 1)
        normalized_keyword_score = min(
            int(keyword_score * density_factor), keyword_score * 2
        )

        score = 0
        score += min(punctuation_hits, 6) * 2
        score += normalized_keyword_score
        score += phrase_score
        score += laughter_hits * 3
        score += min(uppercase_hits, 5)
        score += curiosity_hits * 2
        score += transition_hits
        score += number_hits * 2
        if word_count < MOMENT_MIN_WORDS:
            score -= 2
        score = max(score, 0)

        excerpt = combined.replace("  ", " ").strip()
        excerpt = excerpt[:160] + ("…" if len(excerpt) > 160 else "")
        moments.append(
            MomentScore(minute_index=minute_index, score=score, excerpt=excerpt)
        )

    return moments


def analyze_most_viewed_moments(
    transcript: Iterable[dict], limit: int = MOST_VIEWED_DEFAULT_LIMIT
) -> List[MomentScore]:
    if limit <= 0:
        return []
    moments = analyze_minute_scores(transcript)
    if not moments:
        return []
    filtered = [moment for moment in moments if moment.score >= MOST_VIEWED_MIN_SCORE]
    if not filtered:
        filtered = moments
    ranked = sorted(filtered, key=lambda moment: (-moment.score, moment.minute_index))
    return ranked[:limit]


def format_most_viewed_moments(
    moments: List[MomentScore], include_header: bool = True
) -> List[str]:
    if not moments:
        return ["Aucun moment notable détecté."]

    lines: List[str] = []
    if include_header:
        lines.append("Moments forts estimés")
        lines.append("-" * 38)
    for index, moment in enumerate(moments, start=1):
        timestamp = minute_to_timestamp(moment.minute_index)
        lines.append(f"{index}. {timestamp} (score {moment.score}) — {moment.excerpt}")
    return lines


def export_most_viewed_csv(
    path: str,
    most_viewed_moments: List[MomentScore] | None,
) -> None:
    rows: List[dict] = []
    for moment in most_viewed_moments or []:
        rows.append(
            {
                "minute": minute_to_timestamp(moment.minute_index),
                "score": moment.score,
                "excerpt": moment.excerpt,
            }
        )

    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["minute", "score", "excerpt"])
        writer.writeheader()
        writer.writerows(rows)
