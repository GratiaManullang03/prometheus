# Google AI Studio API — Referensi Integrasi

## Apa itu Google AI Studio?

Google AI Studio adalah platform dari Google untuk mengakses model Gemini dan Gemma secara gratis (free tier).
Prometheus menggunakan Google AI Studio sebagai provider LLM utama sejak migrasi dari OpenRouter.

- Base URL : `https://generativelanguage.googleapis.com/v1beta/openai/`
- SDK      : `openai` (Python) — endpoint kompatibel OpenAI, tidak perlu SDK khusus
- API Key  : Dapatkan di https://aistudio.google.com/apikey
- Docs     : https://ai.google.dev/gemini-api/docs

---

## Setup di Prometheus

API key disimpan di `.env`:

```bash
GOOGLE_AI_STUDIO_API_KEY=AIza...
```

Konfigurasi di `config/config.yaml`:

```yaml
llm:
  provider: "google"
  base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
  model: "gemini-2.5-flash"
  api_key: "${GOOGLE_AI_STUDIO_API_KEY}"
```

---

## Chat Completion (OpenAI-compatible)

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key="AIza...",  # dari env: GOOGLE_AI_STUDIO_API_KEY
)

response = client.chat.completions.create(
    model="gemini-2.5-flash",
    max_tokens=8192,
    temperature=0.3,
    messages=[
        {"role": "system", "content": "Kamu adalah reasoning core dari Prometheus."},
        {"role": "user",   "content": "Analisis state sistem ini dan buat rencana perbaikan."},
    ],
)

text = response.choices[0].message.content
```

---

## Response Format

```python
response.choices[0].message.content   # string — isi jawaban
response.choices[0].finish_reason     # "stop" | "length" | "max_tokens"
response.usage.prompt_tokens          # token input
response.usage.completion_tokens      # token output
response.usage.total_tokens           # total
```

---

## Error Handling

```python
from openai import APIStatusError, RateLimitError, AuthenticationError

try:
    response = client.chat.completions.create(...)
except AuthenticationError:
    # API key salah atau tidak valid
    ...
except RateLimitError:
    # RPM atau RPD habis — ModelRegistry otomatis fallback ke model lain
    ...
except APIStatusError as e:
    print(e.status_code, e.message)
    # 429 = rate limit | 400 = bad request | 500 = server error
```

---

## Perbedaan dengan OpenRouter

| Aspek | OpenRouter | Google AI Studio |
|---|---|---|
| Base URL | `openrouter.ai/api/v1` | `generativelanguage.googleapis.com/v1beta/openai/` |
| API Key env | `OPENROUTER_API_KEY` | `GOOGLE_AI_STUDIO_API_KEY` |
| Model IDs | `provider/model:tier` (e.g. `arcee-ai/trinity-large-preview:free`) | nama langsung (e.g. `gemini-2.5-flash`) |
| Rate limit | Per model, bervariasi | Per model, 20-14.4K RPD tergantung model |
| Kualitas | Tergantung model yang dipilih | Gemini 2.5 Flash jauh lebih baik dari free OpenRouter |

---

## Catatan Penting

- Rate limit Google AI Studio adalah **per hari (RPD)**, bukan hanya per menit.
- Gemini 2.5 Flash memiliki limit **20 RPD** — Prometheus menggunakannya hanya untuk REASONING task.
- ModelRegistry otomatis fallback ke Gemma 3 27B (14.4K RPD) ketika Gemini 2.5 habis kuota.
- OpenRouter masih dikonfigurasi sebagai backup (`OPENROUTER_API_KEY` di `.env`) tapi tidak digunakan secara default.
