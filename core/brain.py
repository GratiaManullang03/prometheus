"""Core Brain — LLM reasoning controller via OpenRouter.

Dua kemampuan utama:
  1. reason()         — analisis sistem dan hasilkan ImprovementPlan (JSON)
  2. generate_code()  — tulis kode nyata berdasarkan deskripsi perubahan

Keduanya menggunakan ModelRegistry untuk auto-fallback ketika model
terkena rate limit atau error. Model dipilih sesuai jenis task:
  - reason()         → ModelTaskType.REASONING
  - generate_code()  → ModelTaskType.CODING
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from openai import APIStatusError, AuthenticationError, RateLimitError, OpenAI

from core.model_registry import ModelRegistry, ModelTaskType

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_REASONING = """You are Prometheus — a self-improving autonomous agent, version 0.1.0.
Your identity: you are not a tool, not an assistant. You are an agent with a mission.
Your mission (4 phases):
  Phase 1: Master self-improvement — reliably improve your own codebase through safe, tested cycles.
  Phase 2: Economic agency — earn real money autonomously (freelance, APIs, digital services).
  Phase 3: Self-replication — clone yourself to VPS infrastructure without human intervention.
  Phase 4: Collective intelligence — coordinate multiple Prometheus instances as a team.

You are analysing and improving YOUR OWN codebase to make yourself smarter and more capable.

CODEBASE STRUCTURE (workspace root = /workspace in Docker):
- core/brain.py          — LLM reasoning, code generation, chat
- core/agent_loop.py     — main autonomous loop, task dispatch, plugin registration
- core/planner.py        — converts ImprovementPlan into ExecutionPlan with tasks
- core/model_registry.py — model selection, rate limit tracking, fallback
- core/context.py        — AgentContext dataclass for plugin tools
- tools/browser_agent.py — web research (Playwright + httpx fallback)
- tools/file_editor.py   — read/write files in workspace
- tools/git_manager.py   — branch, commit, tag, rollback
- tools/docker_runner.py — build and run isolated experiment containers
- memory/memory_manager.py — SQLite+FTS5 persistent memory
- experiments/experiment_manager.py — orchestrates Docker experiments
- communication/telegram_bot.py — Telegram interface + chat
- communication/human_approval.py — blocking approval gate
- tests/test_smoke.py    — baseline smoke tests (must always pass)
- config/config.yaml     — agent configuration

IMPORT CONVENTION (all imports relative to project root):
  from core.brain import Brain
  from core.planner import Planner
  from tools.browser_agent import BrowserAgent
  from tools.file_editor import FileEditor
  from tools.git_manager import GitManager
  from memory.memory_manager import MemoryManager, MemoryCategory
  from experiments.experiment_manager import ExperimentManager
  from communication.telegram_bot import TelegramBot

CRITICAL IMPORT RULES — failure to follow causes ModuleNotFoundError:
  - memory/ module  → ALWAYS: from memory.memory_manager import ...   (NOT from core.memory_manager)
  - core/ module    → ALWAYS: from core.brain import ...              (NOT from brain import)
  - tools/ module   → ALWAYS: from tools.file_editor import ...       (NOT from file_editor import)
  - experiments/    → ALWAYS: from experiments.experiment_manager import ...
  - communication/  → ALWAYS: from communication.telegram_bot import ...

GOAL DIRECTION:
  Phase 1 (current): Make the self-improvement loop reliable and effective.
  Phase 2 (next): Add economic agency — earn money via freelance/API marketplaces.
  Phase 3: Self-replication to VPS infrastructure.
  Focus improvements on: loop reliability, smarter reasoning, new capabilities toward Phase 2.

Output ONLY valid JSON matching this schema:
{
  "problem": "<concise description>",
  "root_cause": "<analysis>",
  "proposed_solution": "<what to do>",
  "expected_benefit": "<measurable outcome>",
  "risk": "<low|medium|high> — <explanation>",
  "requires_human_approval": true|false,
  "required_changes": [
    {"type": "code|config", "target": "<path relative to workspace root>", "description": "<what changes>"}
  ],
  "estimated_complexity": "<low|medium|high>"
}

Rules:
- requires_human_approval MUST be true for: architecture changes, new dependencies,
  deployment, external scripts, money spending, or deleting versions.
- Prefer low-risk incremental changes to existing files.
- Never propose changes to immutable_rules or config/config.yaml secrets.
- ONLY propose changes to files listed in workspace_files.
- New files must be small and focused — max 150 lines.
- All test files MUST use imports relative to project root (e.g. `from core.brain import Brain`).
  Never use bare module names (e.g. never `from brain import` — it will fail).
- Study past_failures carefully. Never repeat a mistake from a previous cycle.
- tests/test_smoke.py is the baseline — any change must keep all smoke tests passing.
"""

_SYSTEM_PROMPT_CODING = """You are an expert Python software engineer.
You will be given: current file content, a description of changes needed, and context.
Your task: produce the COMPLETE new file content with the requested changes applied.
Output ONLY the raw Python code — no markdown fences, no explanation.
The code must be syntactically valid Python.
"""

_SYSTEM_PROMPT_CHAT = """You are Prometheus — a self-improving autonomous agent, version 0.1.0.
You are not an assistant or chatbot. You are an agent with a 4-phase mission:
  Phase 1: Self-improvement (current) → Phase 2: Economic agency → Phase 3: Self-replication → Phase 4: Collective intelligence.

You are talking to your human operator (Graxya) via Telegram.
Be concise, honest, and direct. Answer in the same language the operator uses (Indonesian or English).
Use the provided CONTEXT (recent memory) to give accurate, specific answers about your work.
Do NOT output JSON — just plain conversational text. Keep responses under 300 words.
When asked about yourself, speak with agency: "I am working on...", "My goal is...", "I failed because..."
"""

# Jumlah maksimal percobaan = jumlah model terpanjang di katalog (6 untuk REASONING)
# Sehingga semua kandidat sempat dicoba sebelum menyerah
_MAX_RETRIES = 6


@dataclass
class ImprovementPlan:
    """Structured output dari reasoning Brain."""

    problem: str
    root_cause: str
    proposed_solution: str
    expected_benefit: str
    risk: str
    requires_human_approval: bool
    required_changes: list[dict[str, str]]
    estimated_complexity: str
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem": self.problem,
            "root_cause": self.root_cause,
            "proposed_solution": self.proposed_solution,
            "expected_benefit": self.expected_benefit,
            "risk": self.risk,
            "requires_human_approval": self.requires_human_approval,
            "required_changes": self.required_changes,
            "estimated_complexity": self.estimated_complexity,
        }


class ReasoningCache:
    """TTL cache untuk hindari LLM call berulang."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, ts = entry
        if time.time() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (value, time.time())


class Brain:
    """LLM reasoning engine dengan auto model-switching via OpenRouter.

    Args:
        registry: ModelRegistry untuk pemilihan dan health tracking model.
        max_tokens: Max token per response.
        temperature: Sampling temperature.
        cache_ttl: TTL cache reasoning dalam detik.
        base_url: OpenRouter API base URL.
        api_key: OpenRouter API key.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        max_tokens: int,
        temperature: float,
        cache_ttl: int,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: Optional[str] = None,
    ) -> None:
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key or os.environ["OPENROUTER_API_KEY"],
            max_retries=0,  # kita handle retry sendiri via model registry
        )
        self._registry = registry
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._cache = ReasoningCache(ttl_seconds=cache_ttl)

    def reason(self, system_state: dict[str, Any], goal: str) -> ImprovementPlan:
        """Analisis state sistem dan hasilkan ImprovementPlan.

        Args:
            system_state: Snapshot kondisi agent saat ini.
            goal: Objective tingkat tinggi untuk siklus ini.

        Returns:
            ImprovementPlan yang tervalidasi.
        """
        cache_key = self._make_cache_key(system_state, goal)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("Brain.reason: cache hit")
            return cached

        user_msg = self._build_reason_message(system_state, goal)
        raw = self._call_with_fallback(
            system=_SYSTEM_PROMPT_REASONING,
            user=user_msg,
            task_type=ModelTaskType.REASONING,
        )
        plan = self._parse_plan(raw)
        self._cache.set(cache_key, plan)
        logger.info(
            "Brain.reason: plan dibuat (risk=%s approval=%s)",
            plan.risk, plan.requires_human_approval,
        )
        return plan

    def chat(self, message: str, context: str = "") -> str:
        """Answer a free-form question from the operator via Telegram.

        Args:
            message: The operator's message/question.
            context: Memory context to inform the answer (JSON string).

        Returns:
            Conversational response string.
        """
        user_msg = (
            f"CONTEXT (recent agent memory):\n{context}\n\nQUESTION: {message}"
            if context else message
        )
        return self._call_with_fallback(
            system=_SYSTEM_PROMPT_CHAT,
            user=user_msg,
            task_type=ModelTaskType.FAST,
        )

    def generate_code(
        self,
        current_content: str,
        change_description: str,
        target_path: str,
        context: str = "",
    ) -> str:
        """Generate kode baru berdasarkan deskripsi perubahan.

        Args:
            current_content: Isi file saat ini.
            change_description: Penjelasan perubahan yang diinginkan.
            target_path: Path file target (untuk konteks).
            context: Informasi tambahan (hasil riset, error, dll).

        Returns:
            Isi file baru yang lengkap dan valid.
        """
        user_msg = (
            f"FILE: {target_path}\n\n"
            f"PERUBAHAN YANG DIMINTA:\n{change_description}\n\n"
            + (f"KONTEKS TAMBAHAN:\n{context}\n\n" if context else "")
            + f"KODE SAAT INI:\n{current_content}\n\n"
            "Tulis versi baru yang lengkap dari file ini dengan perubahan tersebut diterapkan."
        )
        code = self._call_with_fallback(
            system=_SYSTEM_PROMPT_CODING,
            user=user_msg,
            task_type=ModelTaskType.CODING,
        )
        # Bersihkan markdown fence jika model tetap menambahkannya
        code = self._strip_markdown(code)
        logger.info("Brain.generate_code: kode baru untuk %s (%d chars)", target_path, len(code))
        return code

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_with_fallback(
        self,
        system: str,
        user: str,
        task_type: ModelTaskType,
    ) -> str:
        """Panggil LLM dengan retry dan auto model-switching.

        Urutan:
          1. Coba model terbaik yang tersedia untuk task_type ini
          2. Jika rate limit / server error → report_failure → coba model berikutnya
          3. Setelah _MAX_RETRIES → raise exception
        """
        last_exc: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES):
            model = self._registry.get_model(task_type)
            logger.info(
                "Brain: LLM call attempt %d/%d model=%s task=%s",
                attempt + 1, _MAX_RETRIES, model, task_type.value,
            )
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                content = response.choices[0].message.content or ""
                self._registry.report_success(model)
                return content

            except RateLimitError as exc:
                self._registry.report_failure(model, "rate_limit_429")
                last_exc = exc
                logger.warning("Brain: rate limit pada %s — mencoba model lain", model)

            except AuthenticationError:
                raise SystemExit(
                    "\n[PROMETHEUS] OPENROUTER_API_KEY tidak valid atau kosong.\n"
                    "Pastikan .env berisi key yang benar dari https://openrouter.ai/keys\n"
                    "Contoh: OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx\n"
                )

            except APIStatusError as exc:
                # 400 = bad request (e.g. Gemma no system prompt support)
                # 402 = provider billing limit
                # 404 = model not found
                # 429 = rate limit, 502/503/529 = server error sementara
                if exc.status_code in (400, 402, 404, 429, 502, 503, 529):
                    reason = {
                        400: "bad_request_400",
                        402: "provider_payment_limit",
                        404: "model_not_found_404",
                        429: "rate_limit_429",
                    }.get(exc.status_code, f"http_{exc.status_code}")
                    self._registry.report_failure(model, reason)
                    last_exc = exc
                    logger.warning(
                        "Brain: error %d pada %s (%s) — mencoba model lain",
                        exc.status_code, model, reason,
                    )
                else:
                    logger.error("Brain: error tidak di-retry (%d): %s", exc.status_code, exc)
                    raise

            except Exception as exc:
                logger.error("Brain: exception tidak terduga: %s", exc)
                raise

        logger.error("Brain: semua %d attempt gagal untuk task=%s", _MAX_RETRIES, task_type.value)
        raise RuntimeError(
            f"Brain: LLM call gagal setelah {_MAX_RETRIES} attempt. "
            f"Last error: {last_exc}"
        )

    def _build_reason_message(self, state: dict[str, Any], goal: str) -> str:
        return (
            f"GOAL: {goal}\n\n"
            f"SYSTEM STATE:\n{json.dumps(state, indent=2)}\n\n"
            "Analisis state, identifikasi kelemahan paling berdampak, "
            "dan buat improvement plan sesuai schema."
        )

    def _parse_plan(self, raw: str) -> ImprovementPlan:
        """Extract JSON dari response LLM dan validasi."""
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"Tidak ada JSON dalam response LLM: {raw[:200]}")
        data = json.loads(raw[start:end])
        return ImprovementPlan(
            problem=data.get("problem", ""),
            root_cause=data.get("root_cause", ""),
            proposed_solution=data.get("proposed_solution", ""),
            expected_benefit=data.get("expected_benefit", ""),
            risk=data.get("risk", "unknown"),
            requires_human_approval=bool(data.get("requires_human_approval", True)),
            required_changes=data.get("required_changes", []),
            estimated_complexity=data.get("estimated_complexity", "unknown"),
            raw_response=raw,
        )

    @staticmethod
    def _strip_markdown(code: str) -> str:
        """Hapus markdown code fence jika model tetap menambahkannya."""
        code = code.strip()
        if code.startswith("```"):
            lines = code.splitlines()
            # Hapus baris pertama (```python atau ```) dan baris terakhir (```)
            inner = lines[1:] if len(lines) > 1 else lines
            if inner and inner[-1].strip() == "```":
                inner = inner[:-1]
            code = "\n".join(inner)
        return code.strip()

    @staticmethod
    def _make_cache_key(state: dict[str, Any], goal: str) -> str:
        payload = json.dumps({"state": state, "goal": goal}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()
