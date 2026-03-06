"""Kalkulasi statistik dasar dari teks."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class TextStats:
    """Hasil statistik dari satu teks."""

    char_count: int
    word_count: int
    sentence_count: int
    paragraph_count: int
    avg_word_length: float
    avg_sentence_length: float
    unique_words: int
    lexical_diversity: float  # unique_words / word_count


def compute_stats(text: str) -> TextStats:
    """Hitung statistik dari string teks.

    Args:
        text: Teks input (bisa multiline).

    Returns:
        TextStats berisi semua metrik.
    """
    if not text or not text.strip():
        return TextStats(0, 0, 0, 0, 0.0, 0.0, 0, 0.0)

    char_count = len(text)

    words = re.findall(r"\b\w+\b", text.lower())
    word_count = len(words)

    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    sentence_count = len(sentences)

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    paragraph_count = len(paragraphs)

    avg_word_length = sum(len(w) for w in words) / word_count if word_count else 0.0
    avg_sentence_length = word_count / sentence_count if sentence_count else 0.0

    unique = set(words)
    unique_words = len(unique)
    lexical_diversity = unique_words / word_count if word_count else 0.0

    return TextStats(
        char_count=char_count,
        word_count=word_count,
        sentence_count=sentence_count,
        paragraph_count=paragraph_count,
        avg_word_length=round(avg_word_length, 2),
        avg_sentence_length=round(avg_sentence_length, 2),
        unique_words=unique_words,
        lexical_diversity=round(lexical_diversity, 4),
    )
