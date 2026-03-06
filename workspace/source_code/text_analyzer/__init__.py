"""Text Analyzer — utilitas analisis teks dasar.

Modul ini adalah seed project untuk Prometheus.
Agent akan menganalisis, menguji, dan meningkatkan kode ini secara bertahap.
"""

from text_analyzer.analyzer import TextAnalyzer
from text_analyzer.stats import TextStats
from text_analyzer.formatter import format_report

__version__ = "0.1.0"
__all__ = ["TextAnalyzer", "TextStats", "format_report"]
