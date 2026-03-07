"""Analyzer utama — mengkoordinasikan analisis teks."""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from text_analyzer.stats import TextStats, compute_stats


class TextAnalyzer:
    """Analisis teks: statistik, kata sering, dan deteksi bahasa sederhana.

    Ini adalah versi awal (v0.1) dengan fitur dasar.
    Prometheus akan meningkatkan akurasi dan menambah fitur secara bertahap.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._stats: Optional[TextStats] = None

    @property
    def stats(self) -> TextStats:
        """Lazy-compute dan cache statistik."""
        if self._stats is None:
            self._stats = compute_stats(self._text)
        return self._stats

    def top_words(self, n: int = 10, exclude_stopwords: bool = True) -> list[tuple[str, int]]:
        """Return n kata paling sering muncul.

        Args:
            n: Jumlah kata yang direturn.
            exclude_stopwords: Jika True, hapus kata umum bahasa Inggris.

        Returns:
            List tuple (kata, frekuensi) diurutkan dari terbanyak.
        """
        words = re.findall(r"\b\w+\b", self._text.lower())
        if exclude_stopwords:
            words = [w for w in words if w not in _STOPWORDS]
        counter = Counter(words)
        return counter.most_common(n)

    def sentences(self) -> list[str]:
        """Pecah teks menjadi daftar kalimat."""
        raw = re.split(r"(?<=[.!?])\s+", self._text.strip())
        return [s.strip() for s in raw if s.strip()]

    def keyword_density(self, keyword: str) -> float:
        """Hitung densitas keyword dalam teks (0.0 - 1.0).

        Args:
            keyword: Kata kunci yang dicari (case-insensitive).

        Returns:
            Rasio kemunculan keyword terhadap total kata.
        """
        if self.stats.word_count == 0:
            return 0.0
        count = len(re.findall(rf"\b{re.escape(keyword.lower())}\b", self._text.lower()))
        return round(count / self.stats.word_count, 4)

    def summary(self, max_sentences: int = 3) -> str:
        """Ekstrak ringkasan sederhana dari kalimat pertama.

        Catatan: Ini adalah implementasi naive (v0.1).
        Prometheus akan meningkatkan ini dengan extractive summarization.

        Args:
            max_sentences: Jumlah kalimat untuk ringkasan.

        Returns:
            String ringkasan.
        """
        sents = self.sentences()
        return " ".join(sents[:max_sentences])


# Stopwords dasar bahasa Inggris — akan diperluas oleh Prometheus
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "this", "that", "these", "those", "it", "its",
    "i", "you", "he", "she", "we", "they", "my", "your", "our", "their",
}
