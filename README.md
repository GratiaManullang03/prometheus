# Prometheus

> **An autonomous economic agent that improves itself, earns money, replicates, and never sleeps.**

Prometheus is not a task runner or chatbot framework. It is a self-directed agent with a long-term mission across four phases currently executing Phase 1 (self-improvement). Every hour, it analyzes its own weaknesses, generates code to fix them, tests the fix inside an isolated Docker container, and commits the result. The operator is notified via Telegram and approves high-risk changes with a button click.

---

## Four-Phase Mission

| Phase | Goal | Status |
|-------|------|--------|
| **1 Self-Improvement** | Continuously improve own codebase through safe, tested cycles | **Active** |
| **2 Economic Agency** | Earn money autonomously via freelance markets, APIs, digital services | Planned |
| **3 Self-Replication** | Clone itself to new VPS instances without human intervention | Planned |
| **4 Collective Intelligence** | Multiple Prometheus instances sharing knowledge and specializing | Planned |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                        main.py                          │
│   build_components() → AgentLoop.run_forever()          │
└────────────────────────┬────────────────────────────────┘
                         │ every 3600s
                         ▼
┌─────────────────────────────────────────────────────────┐
│                   AgentLoop._run_cycle()                 │
│                                                          │
│  _observe()  →  Brain.reason()  →  Planner.build()      │
│       │               │                  │               │
│  SystemState    ImprovementPlan    ExecutionPlan          │
│  (git, memory,  (problem, solution,  (ordered Tasks)     │
│   workspace     risk, changes)                           │
│   files)                                                 │
│                                                          │
│  _execute_plan() ──► _dispatch_task() per Task           │
│      │                                                   │
│      ├── RESEARCH      → BrowserAgent.research()         │
│      ├── CODE_CHANGE   → Brain.generate_code() → stage   │
│      ├── DOCKER_TEST   → ExperimentManager.run()         │
│      ├── EVALUATE      → check Docker result             │
│      ├── REQUEST_APPROVAL → HumanApprovalGate (Telegram) │
│      └── STORE_MEMORY  → MemoryManager.store()           │
│                                                          │
│  _maybe_auto_apply()  → commit low-risk patches          │
│  approval gate        → commit + tag stable version      │
└─────────────────────────────────────────────────────────┘
```

---

## Module Map

| Module | File | Responsibility |
|--------|------|----------------|
| `Brain` | `core/brain.py` | LLM via Google AI Studio / OpenRouter; `reason()` → ImprovementPlan; `generate_code()` → code; `chat()` → operator Telegram replies |
| `ModelRegistry` | `core/model_registry.py` | Per-task model selection (REASONING / CODING / RESEARCH / FAST) with health tracking, cooldown, and auto-fallback |
| `Planner` | `core/planner.py` | Converts ImprovementPlan to ordered ExecutionPlan with typed Tasks |
| `AgentLoop` | `core/agent_loop.py` | Main cycle orchestrator; task dispatch; plugin registration; auto-apply low-risk patches |
| `AgentContext` | `core/context.py` | Dataclass passed to external tool plugins contains all agent resources |
| `ExperimentManager` | `experiments/experiment_manager.py` | Git branch → Docker test → evaluate → rollback on fail → persist to memory |
| `DockerRunner` | `tools/docker_runner.py` | Isolated experiment containers (`--network none`, `--read-only`, `--cap-drop ALL`) |
| `GitManager` | `tools/git_manager.py` | Workspace git ops; experiment branches; rollback; stable version tagging |
| `MemoryManager` | `memory/memory_manager.py` | SQLite + FTS5 persistent store; WAL mode for multi-instance; never deletes archives at threshold |
| `HumanApprovalGate` | `communication/human_approval.py` | Blocking Telegram approval gate (`threading.Event`, 24h timeout) |
| `TelegramBot` | `communication/telegram_bot.py` | Long-polling bot; `/status`, `/help`, free-form chat, inline approval buttons |
| `BrowserAgent` | `tools/browser_agent.py` | DDG search via Playwright (headless Chromium) + httpx fallback; SSRF-safe |
| `FileEditor` | `tools/file_editor.py` | Sandboxed read/write in workspace; blocks path traversal |

---

## Execution Cycle (every 3600s)

```
1. _observe()
   └── snapshot: memory stats, git status, recent failures/successes, workspace files

2. Brain.reason(state, goal)
   └── LLM → ImprovementPlan JSON (problem, root_cause, solution, risk, required_changes)

3. Telegram notification
   └── plan summary sent to operator (non-blocking)

4. Planner.build(plan)
   └── ImprovementPlan → ExecutionPlan (ordered Tasks):
       [RESEARCH] → [CODE_CHANGE ...] → [DOCKER_TEST] → [EVALUATE]
       → [REQUEST_APPROVAL?] → [STORE_MEMORY]

5. _execute_plan()
   └── dispatch each Task to handler

6. _maybe_auto_apply()
   └── low-risk + Docker pass → auto-commit to workspace
   └── high-risk / requires_approval → block on Telegram gate → commit + git tag vX.Y

7. Telegram notification
   └── cycle result: N tasks done, M failed
```

---

## Approval vs Auto-Apply

| Condition | Action |
|-----------|--------|
| `requires_human_approval: true` | Block on Telegram → operator clicks ✅/❌ → apply → tag stable version `vX.Y` |
| `requires_human_approval: false` + Docker pass | Auto-commit immediately, no blocking |
| New files only (no existing code modified) | Auto-commit immediately, no Docker test required |

---

## Plugin System (Phase 2/3 Ready)

External tools can be registered at runtime without modifying `AgentLoop`:

```python
def my_earn_money_handler(task, plan, improvement, patches, ctx: AgentContext):
    result = ctx.browser.interact(url, actions)
    ctx.memory.store(MemoryCategory.EXPERIMENT_RESULTS, {"revenue": result})

loop.register_tool(TaskType.EARN_MONEY, my_earn_money_handler)
```

Pre-registered Phase 2/3 TaskTypes: `WEB_INTERACT`, `EARN_MONEY`, `PROVISION_INFRA`.

---

## LLM Configuration

**Primary**: Google AI Studio `gemini-2.5-flash` (5 RPM, 20 RPD free tier)

**Fallback** (auto-rotated on 2× rate limit from primary):

| Attempt | Model | Provider |
|---------|-------|----------|
| 3 | `nousresearch/hermes-3-llama-3.1-405b:free` | OpenRouter |
| 4 | `meta-llama/llama-3.3-70b-instruct:free` | OpenRouter |
| 5 | `qwen/qwen3-coder:free` | OpenRouter |
| 6 | `mistralai/mistral-small-3.1-24b-instruct:free` | OpenRouter |

Failures trigger 60s cooldown (Google) or session skip after 3 failures (OpenRouter).

---

## Memory System

SQLite + FTS5 full-text search (`memory/knowledge_base.db`). WAL mode enables concurrent reads for Phase 3 multi-instance setups.

| Category | Purpose |
|----------|---------|
| `architecture_decisions` | Design choices and rationale |
| `tool_documentation` | Research summaries from BrowserAgent |
| `past_failures` | Failed experiments with full error context |
| `successful_improvements` | Completed improvements with outcomes |
| `ideas_backlog` | Ideas generated but not yet attempted |
| `experiment_results` | Raw Docker experiment outcomes |

Max 1000 entries/category → oldest automatically archived to `memory/archive_<category>.json`.

---

## Docker Experiment Pipeline

```
workspace/source_code/ → tempdir copy
                       → apply code_patches (path traversal blocked)
                       → docker build (from docker/Dockerfile)
                       → docker run:
                             --network none
                             --memory=512m
                             --cpus=1.0
                             --read-only
                             --cap-drop ALL
                             --security-opt no-new-privileges:true
                       → pytest tests/ -v
                       → success → _maybe_auto_apply()
                       → failure → git rollback → checkout main
                       → always → cleanup image + tempdir
```

---

## Security Model

- **Experiments never have network access** `--network none` is non-negotiable
- **Containers are read-only** tmpfs at `/tmp` only
- **No root in containers** dedicated `agent` user in Dockerfile
- **Path traversal blocked** `FileEditor` and `DockerRunner` both validate paths
- **Git subprocess isolation** only safe env vars passed (PATH, HOME, LANG)
- **Operator authorization** Telegram messages from other users are silently dropped
- **No secrets in code** all keys via `.env` + `${VAR}` expansion in config

---

## Immutable Rules

The agent **must request approval** for:
- Architecture changes
- New dependency installation
- Deployment to production
- Executing external scripts
- Any financial operation
- Deleting versioned releases

The agent **can never**:
- Delete memory history
- Modify immutable rules
- Skip the approval gate
- Rollback on main/master branch

---

## Setup

### Prerequisites

- Python 3.12+
- Docker
- Git

### Local Development

```bash
# Clone and setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Install Playwright browser (optional httpx fallback works without it)
playwright install chromium

# Configure secrets
cp .env.example .env
# Edit .env fill in required keys
```

### Environment Variables (`.env`)

```env
# Required
GOOGLE_AI_STUDIO_API_KEY=AIza...
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654321

# Optional fallback LLM when Google hits rate limits
OPENROUTER_API_KEY=sk-or-v1-...
```

### Run

```bash
# Continuous loop (default: every 3600s)
python main.py

# Single cycle then exit
python main.py --once

# Override the improvement goal for this session
python main.py --goal "Focus on adding test coverage for BrowserAgent"

# Custom config file
python main.py --config path/to/config.yaml
```

### Production (Docker Compose)

```bash
docker-compose up --build -d

# View logs
docker-compose logs -f prometheus

# Restart
docker-compose restart prometheus
```

> **Note:** The agent container mounts `/var/run/docker.sock` to spawn experiment containers. In production, replace with a scoped socket proxy that whitelists only build/run/remove operations.

---

## Telegram Commands

Once running, interact with the agent via Telegram:

| Command / Message | Response |
|-------------------|----------|
| `/status` | Uptime, memory counts, model health |
| `/help` | List available commands |
| Any free-form text | Agent answers using memory context (powered by `Brain.chat()`) |
| ✅ Approve button | Approve a pending high-risk change |
| ❌ Reject button | Reject and discard the proposed change |

---

## Testing

```bash
# Run baseline smoke tests (all experiments must keep these green)
python -m pytest tests/ -v

# Tests cover: imports, Planner logic, ImprovementPlan schema, MemoryManager CRUD,
# FileEditor read/write, Brain JSON parsing
```

---

## Project Structure

```
prometheus/
├── main.py                          # Entry point wires all components
├── config/
│   └── config.yaml                  # Full agent configuration
├── core/
│   ├── agent_loop.py                # Main cycle orchestrator
│   ├── brain.py                     # LLM reasoning + code generation
│   ├── context.py                   # AgentContext for plugins
│   ├── model_registry.py            # Model health tracking + fallback
│   └── planner.py                   # ImprovementPlan → ExecutionPlan
├── communication/
│   ├── human_approval.py            # Blocking Telegram approval gate
│   └── telegram_bot.py              # Long-polling bot interface
├── experiments/
│   └── experiment_manager.py        # Docker experiment lifecycle
├── memory/
│   ├── memory_manager.py            # SQLite + FTS5 memory store
│   └── knowledge_base.db            # Runtime memory (auto-created)
├── tools/
│   ├── browser_agent.py             # Web research (Playwright + httpx)
│   ├── docker_runner.py             # Isolated container runner
│   ├── file_editor.py               # Sandboxed file read/write
│   ├── git_manager.py               # Workspace version control
│   └── terminal_exec.py             # Safe shell execution
├── docker/
│   ├── Dockerfile                   # Experiment container image
│   └── Dockerfile.agent             # Production agent image
├── tests/
│   └── test_smoke.py                # Baseline test suite
├── workspace/
│   └── source_code/                 # Separate git repo Prometheus experiments on
├── logs/                            # Rotating log files
├── docker-compose.yml               # Production deployment
└── requirements.txt
```

---

## Roadmap

### Phase 1 Foundation (Active)
- [x] Self-improvement loop (observe → reason → plan → test → commit)
- [x] SQLite + FTS5 memory (upgraded from JSON flat file)
- [x] Plugin tool system (`register_tool()`, `AgentContext`)
- [x] Playwright browser agent with httpx fallback
- [x] Multi-model fallback (Google AI Studio → OpenRouter rotation)
- [x] Telegram chat + approval gate
- [x] Docker experiment isolation
- [x] Git versioning + stable tags

### Phase 2 Economic Agency (Next)
- [ ] `tools/economic/` wallet, payment tracking, daily spending cap
- [ ] `tools/marketplace/` Upwork / Fiverr / RapidAPI integrations
- [ ] Revenue tracking in memory
- [ ] Immutable rule: spending limit enforcement + approval threshold

### Phase 3 Self-Replication
- [ ] `tools/infrastructure/` VPS provisioning (DigitalOcean/Hetzner API)
- [ ] Instance registry master tracks all workers
- [ ] Shared memory via SQLite over network or embedded DB server
- [ ] Immutable rule: cannot spawn instance without human approval

### Phase 4 Collective Intelligence
- [ ] Knowledge aggregation protocol between instances
- [ ] Specialization (coding instance, research instance, monetization instance)
- [ ] Hierarchical control master Prometheus oversees workers
- [ ] Upgrade propagation across all instances

---

## Philosophy

Prometheus is designed as a **digital employee that never sleeps and never stops learning**. It is not configured for specific tasks it decides what to improve next based on its own failure history, the state of its workspace, and a high-level goal set by the operator. The operator's role is to approve or reject risky proposals, not to direct every action.

All memory is permanent. Failures are learning data, not garbage to discard. The agent compounds knowledge across every cycle.
