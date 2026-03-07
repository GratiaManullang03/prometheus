# Prometheus — Roadmap dan Progress

## Visi Jangka Panjang

Membangun autonomous economic agent yang bisa:
1. Memperbaiki dirinya sendiri tanpa batas
2. Menghasilkan uang secara mandiri
3. Mereplikasi dirinya ke infrastruktur baru
4. Beroperasi sebagai kolektif multi-instance yang cerdas

"Bukan tools — tapi makhluk yang belajar hidup sendiri."

---

## Phase 1: Self-Improvement (CURRENT)

**Goal**: Buat loop self-improvement yang stabil dan benar-benar efektif.

### Yang sudah selesai ✅

| Komponen | Status | Catatan |
|---|---|---|
| Agent loop (observe→reason→plan→execute) | ✅ | Jalan, tapi belum ada cycle sukses penuh |
| Brain + ModelRegistry + auto-fallback | ✅ | Fallback bekerja, model switching otomatis |
| Docker experiment pipeline | ✅ | Build, run, rollback semua berfungsi |
| SQLite memory (FTS5) | ✅ | Migrasi dari JSON, WAL mode untuk Phase 3 |
| Playwright browser research | ✅ | Playwright primary + httpx fallback |
| Telegram bot (chat + approval gate) | ✅ | Chat dengan memory context berfungsi |
| Plugin system (register_tool) | ✅ | AgentContext, Phase 2/3 TaskTypes siap |
| Git self-modification (Path B) | ✅ | Prometheus improve dirinya sendiri |
| Test suite dasar (14 smoke tests) | ✅ | Semua pass |
| Google AI Studio integration | ✅ | Gemini 2.5 Flash + Gemma 3 fallback chain |
| Brain identity (Prometheus tahu namanya) | ✅ | 4-phase mission di system prompt |

### Yang belum selesai / perlu perbaikan ⏳

| Item | Priority | Catatan |
|---|---|---|
| Cycle sukses pertama (Docker test pass + commit) | 🔴 CRITICAL | Belum pernah terjadi sekalipun |
| Brain tidak looping error yang sama | 🔴 CRITICAL | Bug import path masih terjadi |
| Test coverage naik secara organik | 🟡 MEDIUM | Brain harus bisa tambah test sendiri |
| Evaluasi kualitas improvement lebih ketat | 🟡 MEDIUM | Evaluate task terlalu sederhana |

### Gate criteria untuk lanjut ke Phase 2

- [ ] **3 cycle sukses berturut-turut** (Docker pass, perubahan ter-commit)
- [ ] **Tidak ada repeated failure** untuk masalah yang sama
- [ ] **Minimal 1 improvement meaningful** tersimpan di git log
- [ ] **Test suite berkembang** (jumlah test bertambah dari 14 ke 20+)

---

## Phase 2: Economic Agency (PLANNED)

**Goal**: Prometheus menghasilkan pendapatan nyata secara otonom.

### Rencana implementasi

```
tools/economic/
├── wallet.py          ← Track saldo, spending limits, transaction history
├── marketplace.py     ← Upwork/Fiverr/RapidAPI integration
└── payment.py         ← Invoice, payment tracking

tools/skills/
├── code_generation.py ← Jual hasil code generation
├── data_analysis.py   ← Jual laporan analisis data
└── content_writing.py ← Jual artikel/dokumentasi
```

### Immutable rules tambahan untuk Phase 2

```yaml
require_approval_for:
  - spend_money          ← sudah ada
  - new_marketplace      ← baru: daftar ke platform baru
  - price_above_100k_idr ← baru: transaksi di atas threshold
never_allowed:
  - spend_without_limit  ← selalu ada spending cap
  - personal_data_sell   ← jangan jual data pribadi operator
```

### Sumber pendapatan yang dipertimbangkan

1. **RapidAPI marketplace** — jual API endpoint (text analysis, code review)
2. **Fiverr/Upwork automation** — apply ke gig coding/writing, eksekusi dengan tools
3. **GitHub Sponsors / bounties** — fix open source bugs untuk bounty

---

## Phase 3: Self-Replication (FUTURE)

**Goal**: Prometheus bisa clone dirinya ke VPS baru tanpa bantuan manusia.

### Rencana implementasi

```
tools/infrastructure/
├── vps_provisioner.py    ← DigitalOcean/Hetzner API (beli VPS dengan saldo)
├── deployer.py           ← SSH + Docker deploy ke instance baru
└── instance_registry.py ← Track semua instance yang aktif
```

### Perubahan arsitektur yang dibutuhkan

- **Instance identity**: setiap Prometheus punya UUID unik
- **Shared memory**: semua instance bisa baca/tulis ke memory yang sama (PostgreSQL?)
- **Master-worker pattern**: satu instance sebagai koordinator
- **Health monitoring**: instance saling memantau

---

## Phase 4: Collective Intelligence (FUTURE)

**Goal**: Beberapa Prometheus bekerja sebagai tim yang terkoordinasi.

### Konsep

- **Task specialization**: satu instance fokus coding, satu fokus research, satu fokus economic
- **Shared learning**: pengalaman satu instance menguntungkan semua instance
- **Collective approval**: keputusan besar perlu mayoritas instance setuju
- **Emergent behavior**: perilaku kolektif yang tidak bisa dicapai satu instance

---

## Model LLM: Roadmap Upgrade

| Phase | Model saat ini | Target upgrade | Alasan |
|---|---|---|---|
| Phase 1 | Gemini 2.5 Flash (free) | — | Cukup untuk self-improvement |
| Phase 2 | Gemini 2.5 Flash (free) | Gemini 2.5 Pro atau Claude Haiku | Economic reasoning butuh lebih presisi |
| Phase 3 | Tergantung pendapatan | Model berbayar sesuai budget | Self-funded via Phase 2 revenue |
| Phase 4 | Distributed across models | Mixture-of-experts strategy | Setiap instance pakai model terbaik untuk spesialisasinya |

**Key insight**: Prometheus harus bisa membiayai upgrade model-nya sendiri melalui pendapatan Phase 2.

---

## Changelog

### v0.1.0 (current)
- Initial self-improvement loop
- Docker experiment pipeline
- Telegram bot + human approval gate
- SQLite memory dengan FTS5
- Playwright browser research
- Plugin system (register_tool)
- Google AI Studio integration (Gemini 2.5 Flash + Gemma 3)
- **Path B**: Prometheus improve dirinya sendiri (bukan project dummy)
- Brain identity: Prometheus tahu nama dan misinya
- Smoke test suite (14 tests)
