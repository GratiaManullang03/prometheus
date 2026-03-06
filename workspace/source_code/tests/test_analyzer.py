"""Test suite untuk TextAnalyzer — dijalankan oleh Docker experiment container."""

import pytest
from text_analyzer.analyzer import TextAnalyzer
from text_analyzer.stats import compute_stats
from text_analyzer.formatter import format_report


SAMPLE_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "This is a second sentence with more words. "
    "Python is a great programming language for data analysis.\n\n"
    "In the second paragraph, we discuss more topics. "
    "Natural language processing enables computers to understand text."
)


class TestTextStats:
    def test_basic_counts(self):
        stats = compute_stats(SAMPLE_TEXT)
        assert stats.word_count > 0
        assert stats.sentence_count > 0
        assert stats.char_count == len(SAMPLE_TEXT)

    def test_empty_text(self):
        stats = compute_stats("")
        assert stats.word_count == 0
        assert stats.sentence_count == 0
        assert stats.lexical_diversity == 0.0

    def test_lexical_diversity_range(self):
        stats = compute_stats(SAMPLE_TEXT)
        assert 0.0 <= stats.lexical_diversity <= 1.0

    def test_avg_word_length_positive(self):
        stats = compute_stats(SAMPLE_TEXT)
        assert stats.avg_word_length > 0


class TestTextAnalyzer:
    def setup_method(self):
        self.analyzer = TextAnalyzer(SAMPLE_TEXT)

    def test_top_words_length(self):
        top = self.analyzer.top_words(n=5)
        assert len(top) <= 5

    def test_top_words_sorted(self):
        top = self.analyzer.top_words(n=10)
        counts = [c for _, c in top]
        assert counts == sorted(counts, reverse=True)

    def test_keyword_density_range(self):
        density = self.analyzer.keyword_density("python")
        assert 0.0 <= density <= 1.0

    def test_keyword_density_zero_missing(self):
        density = self.analyzer.keyword_density("xyznotaword")
        assert density == 0.0

    def test_sentences_not_empty(self):
        sents = self.analyzer.sentences()
        assert len(sents) > 0

    def test_summary_respects_limit(self):
        summary = self.analyzer.summary(max_sentences=2)
        # Summary harus lebih pendek dari full text
        assert len(summary) < len(SAMPLE_TEXT)

    def test_stats_cached(self):
        # Panggil dua kali — harus return objek yang sama (cached)
        s1 = self.analyzer.stats
        s2 = self.analyzer.stats
        assert s1 is s2


class TestFormatter:
    def test_report_contains_sections(self):
        stats = compute_stats(SAMPLE_TEXT)
        report = format_report(stats)
        assert "Words" in report
        assert "Sentences" in report
        assert "Lexical diversity" in report

    def test_report_with_top_words(self):
        analyzer = TextAnalyzer(SAMPLE_TEXT)
        stats = analyzer.stats
        top = analyzer.top_words(n=3)
        report = format_report(stats, top_words=top)
        assert "Top Words" in report
