"""Model registry — katalog OpenRouter models dengan auto-fallback.

Setiap jenis task memiliki daftar model preferensi berbeda.
Ketika sebuah model terkena rate limit atau error, registry otomatis
menandainya sebagai cooldown dan memilih model berikutnya.

Task types:
  REASONING  — analisis kompleks, planning, JSON structured output
  CODING     — code generation dan review
  RESEARCH   — summarization, retrieval, ringkasan web
  FAST       — task ringan, quick questions
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

_COOLDOWN_SECONDS = 300  # 5 menit sebelum retry model yang gagal
_MAX_FAILURES_BEFORE_SKIP = 3  # skip permanen dalam sesi jika gagal berkali-kali


class ModelTaskType(str, Enum):
    REASONING = "reasoning"
    CODING = "coding"
    RESEARCH = "research"
    FAST = "fast"


# Katalog model per task type — urutan = prioritas
# Semua model menggunakan tier :free dari OpenRouter
# Catatan provider:
# - Venice (mistral-small) → bisa 402 jika spending limit provider tercapai
# - Arcee AI (trinity-large-preview, trinity-mini) → confirmed free, tidak via Venice
# - Google (gemma) → reliable free tier
# - Meta (llama) → free tapi rate limit ketat
# Urutan = prioritas: model paling reliable & capable di atas

_CATALOG: dict[ModelTaskType, list[str]] = {
    # CATATAN: Google AI Studio OpenAI-compatible endpoint hanya support model Gemini.
    # Gemma models TIDAK bisa diakses via endpoint ini — hanya via native Google AI SDK.
    #
    # Rate limits free tier:
    # gemini-2.5-flash              : 5 RPM,  250K TPM,  20 RPD
    # gemini-2.5-flash-lite-*       : 10 RPM, 250K TPM,  20 RPD
    # gemini-1.5-flash           : 15 RPM, 250K TPM, 500 RPD  ← workhorse utama
    # gemini-2.0-flash              : RPD tinggi (tidak terlihat di dashboard = belum dipakai)
    # gemini-2.0-flash-lite         : RPD tinggi, paling ringan

    ModelTaskType.REASONING: [
        "gemini-2.5-flash",                    # terbaik untuk JSON reasoning — 20 RPD
        "gemini-2.5-flash-lite-preview-06-17", # fallback reasoning — 20 RPD
        "gemini-2.0-flash",                    # fallback dengan RPD lebih besar
        "gemini-1.5-flash",                 # 500 RPD — sustain sepanjang hari
    ],
    ModelTaskType.CODING: [
        "gemini-2.0-flash",                    # RPD besar, bagus untuk code generation
        "gemini-1.5-flash",                 # 500 RPD — utama jika 2.0 limit
        "gemini-2.5-flash",                    # paling presisi tapi hemat RPD
        "gemini-2.0-flash-lite",               # last resort
    ],
    ModelTaskType.RESEARCH: [
        "gemini-2.0-flash-lite",               # ringan, cukup untuk summarize
        "gemini-1.5-flash",                 # 500 RPD
        "gemini-2.0-flash",                    # upgrade jika perlu
    ],
    ModelTaskType.FAST: [
        "gemini-2.0-flash-lite",               # paling cepat & ringan untuk Telegram chat
        "gemini-1.5-flash",                 # 500 RPD fallback
        "gemini-2.0-flash",                    # fallback
    ],
}


@dataclass
class ModelHealth:
    """Status kesehatan satu model dalam sesi ini."""

    model_id: str
    failures: int = 0
    last_failure_at: float = 0.0
    cooling_down: bool = False

    def mark_failure(self) -> None:
        self.failures += 1
        self.last_failure_at = time.time()
        self.cooling_down = True

    def mark_success(self) -> None:
        self.failures = 0
        self.cooling_down = False

    def is_available(self, cooldown: float) -> bool:
        if self.failures >= _MAX_FAILURES_BEFORE_SKIP:
            return False
        if not self.cooling_down:
            return True
        if time.time() - self.last_failure_at >= cooldown:
            self.cooling_down = False
            logger.info("ModelRegistry: %s cooldown selesai, tersedia kembali", self.model_id)
            return True
        remaining = cooldown - (time.time() - self.last_failure_at)
        logger.debug("ModelRegistry: %s masih cooldown %.0fs", self.model_id, remaining)
        return False


class ModelRegistry:
    """Thread-safe registry model dengan health tracking dan auto-fallback.

    Args:
        default_model: Model utama sesuai config.
        cooldown_seconds: Lama cooldown setelah failure.
    """

    def __init__(self, default_model: str, cooldown_seconds: int = _COOLDOWN_SECONDS) -> None:
        self._default = default_model
        self._cooldown = cooldown_seconds
        self._health: dict[str, ModelHealth] = {}
        self._lock = threading.Lock()

    def get_model(self, task_type: ModelTaskType = ModelTaskType.REASONING) -> str:
        """Pilih model terbaik yang tersedia untuk task type tertentu.

        Args:
            task_type: Jenis task yang akan dijalankan.

        Returns:
            Model ID yang paling sesuai dan tersedia.
        """
        candidates = list(_CATALOG.get(task_type, []))

        # Pastikan default selalu ada sebagai fallback terakhir
        if self._default not in candidates:
            candidates.append(self._default)

        with self._lock:
            for model in candidates:
                health = self._health.setdefault(model, ModelHealth(model_id=model))
                if health.is_available(self._cooldown):
                    if model != candidates[0]:
                        logger.info(
                            "ModelRegistry: menggunakan fallback %s (task=%s)",
                            model, task_type.value,
                        )
                    return model

        logger.warning(
            "ModelRegistry: semua model cooldown untuk task=%s — paksa default %s",
            task_type.value, self._default,
        )
        return self._default

    def report_success(self, model_id: str) -> None:
        """Tandai model sebagai berhasil; reset cooldown-nya."""
        with self._lock:
            h = self._health.setdefault(model_id, ModelHealth(model_id=model_id))
            was_failing = h.failures > 0
            h.mark_success()
        if was_failing:
            logger.info("ModelRegistry: %s pulih setelah sukses", model_id)

    def report_failure(self, model_id: str, reason: str = "") -> None:
        """Tandai model sebagai gagal dan masukkan ke cooldown.

        Args:
            model_id: Model yang gagal.
            reason: Deskripsi singkat penyebab kegagalan.
        """
        with self._lock:
            h = self._health.setdefault(model_id, ModelHealth(model_id=model_id))
            h.mark_failure()
            failures = h.failures
        logger.warning(
            "ModelRegistry: %s gagal (ke-%d) — %s. Cooldown %ds.",
            model_id, failures, reason[:80], self._cooldown,
        )

    def status(self) -> dict[str, dict]:
        """Return snapshot status semua model yang pernah digunakan."""
        with self._lock:
            return {
                mid: {
                    "available": h.is_available(self._cooldown),
                    "failures": h.failures,
                    "cooling_down": h.cooling_down,
                }
                for mid, h in self._health.items()
            }

    def all_candidates(self, task_type: ModelTaskType) -> list[str]:
        """Daftar semua kandidat untuk task type ini (untuk logging/debug)."""
        return list(_CATALOG.get(task_type, [self._default]))
