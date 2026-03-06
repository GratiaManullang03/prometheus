# OpenRouter API — Referensi Integrasi

## Apa itu OpenRouter?

OpenRouter adalah unified API gateway yang menyediakan akses ke ratusan LLM dari berbagai provider
(OpenAI, Anthropic, Google, Meta, Mistral, dll.) melalui satu endpoint kompatibel OpenAI.

- Base URL : `https://openrouter.ai/api/v1`
- SDK      : `openai` (Python) — tidak perlu SDK khusus
- Docs     : https://openrouter.ai/docs

---

## Setup Dasar

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="<OPENROUTER_API_KEY>",  # dari env: OPENROUTER_API_KEY
)
```

---

## Chat Completion (standard)

```python
response = client.chat.completions.create(
    model="mistralai/mistral-small-3.1-24b-instruct:free",
    max_tokens=4096,
    temperature=0.3,
    messages=[
        {"role": "system", "content": "Kamu adalah asisten engineering."},
        {"role": "user",   "content": "Jelaskan perbedaan TCP dan UDP."},
    ],
)

text = response.choices[0].message.content
```

---

## Reasoning Mode (model tertentu)

Beberapa model mendukung extended reasoning (chain-of-thought internal).
Aktifkan via `extra_body`:

```python
response = client.chat.completions.create(
    model="arcee-ai/trinity-large-preview:free",
    messages=[{"role": "user", "content": "Berapa banyak huruf 'r' di 'strawberry'?"}],
    extra_body={"reasoning": {"enabled": True}},
)

message = response.choices[0].message

# Untuk multi-turn dengan reasoning, sertakan reasoning_details kembali:
messages = [
    {"role": "user", "content": "Berapa banyak huruf 'r' di 'strawberry'?"},
    {
        "role": "assistant",
        "content": message.content,
        "reasoning_details": message.reasoning_details,  # wajib dikembalikan utuh
    },
    {"role": "user", "content": "Yakin? Coba cek ulang."},
]

response2 = client.chat.completions.create(
    model="arcee-ai/trinity-large-preview:free",
    messages=messages,
    extra_body={"reasoning": {"enabled": True}},
)
```

---

## Cara Pakai di Prometheus

Brain (`core/brain.py`) sudah dikonfigurasi menggunakan OpenRouter.
Konfigurasi ada di `config/config.yaml` dan dibaca dari environment variable:

```yaml
llm:
  provider: "openrouter"
  base_url: "https://openrouter.ai/api/v1"
  model: "mistralai/mistral-small-3.1-24b-instruct:free"
  api_key: "${OPENROUTER_API_KEY}"
```

Untuk mengganti model, cukup ubah nilai `model` di `config.yaml`.
Lihat daftar model tersedia di `knowledge/openrouter_models.md`.

---

## Response Format

```python
response.choices[0].message.content   # string — isi jawaban
response.choices[0].finish_reason     # "stop" | "length" | "tool_calls"
response.usage.prompt_tokens          # token input
response.usage.completion_tokens      # token output
response.usage.total_tokens           # total
```

---

## Error Handling

```python
from openai import APIError, RateLimitError, AuthenticationError

try:
    response = client.chat.completions.create(...)
except AuthenticationError:
    # API key salah atau tidak ada
    ...
except RateLimitError:
    # Rate limit — tunggu sebentar lalu retry
    ...
except APIError as e:
    # Error lain dari server
    print(e.status_code, e.message)
```

---

## Catatan Penting

- Model dengan suffix `:free` tidak dikenakan biaya tetapi mungkin memiliki rate limit lebih ketat.
- Request header `HTTP-Referer` dan `X-Title` bisa ditambahkan untuk identifikasi di dashboard OpenRouter:
  ```python
  client = OpenAI(
      base_url="https://openrouter.ai/api/v1",
      api_key="...",
      default_headers={
          "HTTP-Referer": "https://github.com/yourname/prometheus",
          "X-Title": "Prometheus Agent",
      },
  )
  ```
