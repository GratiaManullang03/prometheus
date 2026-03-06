# OpenRouter — Daftar Model Tersedia (Free Tier)

Model-model di bawah ini tersedia tanpa biaya (`:free`).
Digunakan oleh Prometheus untuk reasoning dan eksperimen.

Model aktif saat ini dikonfigurasi di `config/config.yaml` → `llm.model`.

---

## Model yang Direkomendasikan

| Model ID | Keunggulan | Cocok untuk |
|----------|------------|-------------|
| `mistralai/mistral-small-3.1-24b-instruct:free` | Cepat, instruksi sangat baik, JSON reliable | **Default Prometheus** — reasoning & planning |
| `meta-llama/llama-3.3-70b-instruct:free` | Kapasitas besar, reasoning kuat | Task kompleks, analisis mendalam |
| `qwen/qwen3-coder:free` | Spesialis coding | Code generation & review |
| `nousresearch/hermes-3-llama-3.1-405b:free` | Model terbesar, reasoning sangat kuat | Task riset & analisis berat |
| `google/gemma-3-27b-it:free` | Balanced, dari Google | Alternatif umum |

---

## Daftar Lengkap Free Models

```
# Qwen (Alibaba)
qwen/qwen3-4b:free
qwen/qwen3-coder:free
qwen/qwen3-next-80b-a3b-instruct:free

# OpenAI (via OpenRouter)
openai/gpt-oss-120b:free
openai/gpt-oss-20b:free

# NVIDIA
nvidia/llama-nemotron-embed-vl-1b-v2:free
nvidia/nemotron-3-nano-30b-a3b:free
nvidia/nemotron-nano-12b-v2-vl:free
nvidia/nemotron-nano-9b-v2:free

# Liquid AI
liquid/lfm-2.5-1.2b-thinking:free
liquid/lfm-2.5-1.2b-instruct:free

# Arcee AI
arcee-ai/trinity-mini:free

# Z-AI
z-ai/glm-4.5-air:free

# CognitiveComputations
cognitivecomputations/dolphin-mistral-24b-venice-edition:free

# Google
google/gemma-3n-e2b-it:free
google/gemma-3n-e4b-it:free
google/gemma-3-4b-it:free
google/gemma-3-12b-it:free
google/gemma-3-27b-it:free

# Meta
meta-llama/llama-3.3-70b-instruct:free
meta-llama/llama-3.2-3b-instruct:free

# Mistral AI
mistralai/mistral-small-3.1-24b-instruct:free

# NousResearch
nousresearch/hermes-3-llama-3.1-405b:free
```

---

## Cara Ganti Model

Edit `config/config.yaml`:

```yaml
llm:
  model: "meta-llama/llama-3.3-70b-instruct:free"  # ganti di sini
```

Atau set environment variable untuk override per-session:

```bash
python main.py --goal "analisis sistem"
# model dibaca dari config.yaml
```

---

## Catatan

- Daftar ini akan bertambah seiring waktu — cek https://openrouter.ai/models untuk update terbaru.
- Model `:free` bisa memiliki rate limit berbeda. Jika sering terkena limit, coba model lain atau tambahkan delay di `config.yaml` → `loop_interval_seconds`.
- Model dengan kapasitas besar (70B+) lebih lambat tapi lebih akurat untuk JSON structured output yang dibutuhkan Brain.
