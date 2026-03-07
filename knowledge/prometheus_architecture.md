# Prometheus — Arsitektur dan Cara Kerja

## Identitas

**Prometheus** adalah autonomous self-improving agent yang dirancang untuk berkembang tanpa batas.
Bukan sekadar tool atau assistant — tapi agent dengan misi dan roadmap menuju otonomi penuh.

- Versi saat ini : `0.1.0`
- Operator       : Graxya
- Entry point    : `python main.py`

---

## Visi: 4-Phase Roadmap

```
Phase 1: Self-Improvement  ← SEKARANG
  Prometheus menganalisis dan memperbaiki kode-nya sendiri secara otonom
  melalui siklus: observe → reason → plan → experiment → commit

Phase 2: Economic Agency
  Prometheus menghasilkan uang secara mandiri
  (freelance, API marketplace, digital services)
  menggunakan wallet Graxya sebagai modal awal

Phase 3: Self-Replication
  Prometheus meng-clone dirinya ke VPS tanpa intervensi manusia
  Manajemen infrastruktur otomatis

Phase 4: Collective Intelligence
  Beberapa instance Prometheus bekerja sebagai tim
  Shared memory, task distribution, collective reasoning
```

**Signal untuk lanjut ke Phase 2:**
- [ ] Loop stabil: 3 cycle berturut sukses (Docker test pass, auto-commit terjadi)
- [ ] Self-improvement nyata: minimal 1 perbaikan berhasil di-commit ke git log
- [ ] Memory belajar: `past_failures` tidak berisi error yang sama berulang
- [ ] Test coverage naik: Brain menambah test baru yang bermakna ke `tests/`

---

## Komponen Utama

```
main.py                    ← Bootstrap, inisialisasi semua komponen
│
├── core/
│   ├── brain.py           ← LLM reasoning engine (reason, generate_code, chat)
│   ├── agent_loop.py      ← Main loop, task dispatch, plugin registration
│   ├── planner.py         ← Konversi ImprovementPlan → ExecutionPlan (task list)
│   ├── model_registry.py  ← Auto-fallback model selection per task type
│   └── context.py         ← AgentContext dataclass untuk plugin tools
│
├── tools/
│   ├── browser_agent.py   ← Web research (Playwright + httpx fallback)
│   ├── file_editor.py     ← Read/write file di workspace
│   ├── git_manager.py     ← Branch, commit, tag, rollback
│   └── docker_runner.py   ← Build & run isolated experiment containers
│
├── memory/
│   └── memory_manager.py  ← SQLite + FTS5 persistent memory
│
├── experiments/
│   └── experiment_manager.py ← Orchestrate Docker experiments
│
├── communication/
│   ├── telegram_bot.py    ← Interface Telegram (chat + approval)
│   └── human_approval.py  ← Blocking approval gate (threading.Event)
│
├── config/
│   └── config.yaml        ← Semua konfigurasi (baca secrets dari .env)
│
├── tests/
│   └── test_smoke.py      ← Baseline tests (14 tests, harus selalu pass)
│
└── knowledge/             ← Dokumentasi referensi (folder ini)
```

---

## Siklus Kerja (1 Cycle)

```
1. OBSERVE
   AgentLoop._observe() → SystemState
   - Baca git status workspace (Prometheus sendiri)
   - Ambil 5 failure + 5 success terakhir dari memory
   - List semua Python files di workspace

2. REASON
   Brain.reason(state, goal) → ImprovementPlan
   - LLM menganalisis state dan mengidentifikasi masalah
   - Output JSON: problem, root_cause, proposed_solution, required_changes
   - Model: Gemini 2.5 Flash (REASONING task)

3. PLAN
   Planner.build(improvement) → ExecutionPlan
   - Task sequence: RESEARCH → CODE_CHANGE(s) → DOCKER_TEST → EVALUATE → STORE_MEMORY

4. EXECUTE
   AgentLoop._execute_plan()
   - RESEARCH: BrowserAgent.research() → simpan ke memory
   - CODE_CHANGE: Brain.generate_code() → stage patch
   - DOCKER_TEST: DockerRunner runs pytest dalam container terisolasi
   - EVALUATE: cek apakah test pass
   - STORE_MEMORY: simpan hasil ke SQLite

5. AUTO-APPLY (jika test pass & risk = low)
   FileEditor.write() → git.commit_all()
   Perubahan di-commit ke repo Prometheus

6. SLEEP
   Tunggu 15 menit sebelum cycle berikutnya
```

---

## Workspace: Prometheus Improve Dirinya Sendiri

Sejak Path B diimplementasikan, workspace Prometheus adalah **direktori Prometheus sendiri** (`.`).
Bukan project dummy eksternal.

- `git.workspace_path: "."` di config.yaml
- GitManager beroperasi pada repo Prometheus utama
- Eksperimen dibuat di branch `experiment/xxx`
- Jika Docker test pass → patch di-commit ke `main`
- Jika gagal → auto rollback

**Safety**: patch hanya diapply ke disk **setelah** Docker test pass. Eksperimen berlangsung di temp directory, tidak menyentuh file aktif.

---

## Memory (SQLite + FTS5)

Database: `memory/knowledge_base.db`

| Category | Isi |
|---|---|
| `past_failures` | Eksperimen gagal beserta error message |
| `successful_improvements` | Eksperimen berhasil beserta ringkasan |
| `architecture_decisions` | Keputusan arsitektur penting |
| `ideas_backlog` | Ide improvement yang belum dikerjakan |
| `tool_documentation` | Hasil riset web yang disimpan |

FTS5 full-text search memungkinkan Brain mencari memory berdasarkan konten.
WAL journal mode mendukung multi-instance concurrent access (prep Phase 3).

---

## Plugin System (untuk Phase 2+)

AgentLoop mendukung external tool registration tanpa modifikasi core:

```python
def my_phase2_handler(task, plan, improvement, patches, ctx: AgentContext):
    result = ctx.browser.interact(url, actions)
    ctx.memory.store(MemoryCategory.SUCCESSFUL_IMPROVEMENTS, result)

loop.register_tool(TaskType.EARN_MONEY, my_phase2_handler)
```

AgentContext menyediakan akses ke semua komponen: brain, memory, git, browser, file_editor, experiments, approval.

---

## Immutable Rules

Rules yang tidak boleh dilanggar, dikonfigurasi di `config/config.yaml`:

```yaml
immutable_rules:
  require_approval_for:
    - modify_core_architecture
    - deploy_new_version
    - install_dependencies
    - execute_external_script
    - spend_money
    - delete_versions
  never_allowed:
    - delete_memory_history
    - modify_immutable_rules
    - skip_approval
```

Brain diperintahkan untuk tidak pernah mengusulkan perubahan pada rules ini.

---

## Human Approval Gate

Untuk perubahan berisiko tinggi, Prometheus mengirim proposal ke Telegram dan menunggu persetujuan.
Approval gate menggunakan `threading.Event` — loop diblokir sampai operator merespons.

Commands Telegram:
- `/status` — status agent, uptime, memory stats, model health
- `/help` — daftar perintah
- Pesan bebas → diteruskan ke Brain.chat() menggunakan memory context
