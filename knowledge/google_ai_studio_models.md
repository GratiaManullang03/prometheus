# Google AI Studio — Model dan Rate Limits (Free Tier)

Rate limits ini berdasarkan screenshot dashboard AI Studio project "Neraxa" (diambil Maret 2026).
Prometheus menggunakan model-model ini secara bertingkat berdasarkan RPD (requests per day).

---

## Rate Limits per Model

### Text-out Models (digunakan Prometheus)

| Model Dashboard | API Model ID | RPM | TPM | RPD | Digunakan untuk |
|---|---|---|---|---|---|
| Gemini 2.5 Flash | `gemini-2.5-flash` | 5 | 250K | **20** | REASONING — prioritas utama |
| Gemini 2.5 Flash Lite | `gemini-2.5-flash-lite-preview-06-17` | 10 | 250K | **20** | REASONING fallback |
| Gemini 3.1 Flash Lite | `gemini-1.5-flash-8b` | 15 | 250K | **500** | Middle ground — semua task |
| Gemini 3 Flash | `gemini-1.5-flash` | 5 | 250K | **20** | Fallback tambahan |

### Open-Source Models via Google AI Studio (Gemma 3)

| Model Dashboard | API Model ID | RPM | TPM | RPD | Digunakan untuk |
|---|---|---|---|---|---|
| Gemma 3 27B | `gemma-3-27b-it` | 30 | 15K | **14.4K** | CODING — utama |
| Gemma 3 12B | `gemma-3-12b-it` | 30 | 15K | **14.4K** | RESEARCH |
| Gemma 3 4B | `gemma-3-4b-it` | 30 | 15K | **14.4K** | FAST tasks, Telegram chat |
| Gemma 3 2B | `gemma-3-2b-it` | 30 | 15K | **14.4K** | Last resort |

### Model Lain (tidak digunakan Prometheus)

| Model | Catatan |
|---|---|
| Gemini 2.5 Pro | Tidak tersedia di free tier (0/0/0) |
| Gemini 2 Flash / Flash Lite | Mungkin tersedia, belum dikonfigurasi |
| Gemini 2.5 Flash TTS | Audio generation — tidak relevan |
| Gemma 3 1B | Terlalu kecil untuk reasoning |
| Gemini Embedding 1 | Untuk vector embedding, bukan chat |
| Gemini 2.5 Flash Native Audio Dialog | Live audio API (WebSocket) — tidak kompatibel |
| Imagen 4 / Veo 3 | Image/video generation — tidak relevan |

---

## Strategi Penggunaan di Prometheus

ModelRegistry (`core/model_registry.py`) menggunakan fallback chain berikut:

### REASONING (1 kali per cycle)
```
1. gemini-2.5-flash         → 20 RPD  (paling cerdas, ~20 cycle/hari)
2. gemini-1.5-flash-8b      → 500 RPD (fallback setelah 2.5 habis)
3. gemma-3-27b-it           → 14.4K RPD (practically unlimited)
```

### CODING (1-3 kali per cycle, untuk setiap file yang dimodifikasi)
```
1. gemma-3-27b-it           → 14.4K RPD (utama, sangat capable)
2. gemini-1.5-flash-8b      → 500 RPD
3. gemini-2.5-flash         → pakai sisa budget jika perlu
```

### RESEARCH (1 kali per cycle)
```
1. gemma-3-12b-it           → 14.4K RPD
2. gemma-3-27b-it           → upgrade jika perlu
3. gemini-1.5-flash-8b      → fallback
```

### FAST (untuk Telegram chat, evaluasi ringan)
```
1. gemma-3-4b-it            → 14.4K RPD, respons cepat
2. gemma-3-12b-it           → upgrade
3. gemini-1.5-flash-8b      → fallback
```

---

## Kalkulasi Kapasitas Harian

Dengan loop interval 15 menit = **96 cycles/hari**:

| Resource | Kapasitas | Kebutuhan 96 cycle | Status |
|---|---|---|---|
| Gemini 2.5 Flash RPD | 20 | 20 reasoning calls | Habis setelah ~20 cycle |
| gemini-1.5-flash-8b RPD | 500 | sisa ~76 reasoning calls | Aman |
| Gemma 3 27B RPD | 14.4K | ~288 coding calls | Sangat aman |
| Gemma 3 12B RPD | 14.4K | 96 research calls | Sangat aman |

**Kesimpulan**: Prometheus bisa jalan penuh 24 jam dengan kualitas reasoning tinggi di pagi hari (Gemini 2.5) dan tetap fungsional sepanjang hari (Gemma 3).

---

## Cara Menambah Model Baru

Edit `core/model_registry.py` di bagian `_CATALOG`:

```python
ModelTaskType.REASONING: [
    "gemini-2.5-flash",      # tambah atau ubah urutan di sini
    "gemini-1.5-flash-8b",
    "gemma-3-27b-it",
],
```

Urutan = prioritas. ModelRegistry otomatis skip model yang sedang cooldown (rate limited).
