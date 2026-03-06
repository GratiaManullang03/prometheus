"""Format hasil analisis menjadi laporan yang mudah dibaca."""

from __future__ import annotations

from text_analyzer.stats import TextStats


def format_report(stats: TextStats, top_words: list[tuple[str, int]] | None = None) -> str:
    """Format TextStats menjadi laporan teks.

    Args:
        stats: Hasil kalkulasi statistik.
        top_words: Opsional — daftar kata sering untuk disertakan.

    Returns:
        String laporan yang siap ditampilkan.
    """
    lines = [
        "=" * 40,
        "TEXT ANALYSIS REPORT",
        "=" * 40,
        f"Characters   : {stats.char_count:,}",
        f"Words        : {stats.word_count:,}",
        f"Sentences    : {stats.sentence_count:,}",
        f"Paragraphs   : {stats.paragraph_count:,}",
        f"Unique words : {stats.unique_words:,}",
        "-" * 40,
        f"Avg word length    : {stats.avg_word_length:.2f} chars",
        f"Avg sentence length: {stats.avg_sentence_length:.1f} words",
        f"Lexical diversity  : {stats.lexical_diversity:.2%}",
    ]

    if top_words:
        lines.append("-" * 40)
        lines.append("Top Words:")
        for word, count in top_words:
            lines.append(f"  {word:<20} {count}")

    lines.append("=" * 40)
    return "\n".join(lines)
