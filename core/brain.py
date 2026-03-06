"""Core Brain — LLM reasoning controller.

Receives system state and goals, reasons about improvements,
and produces structured ImprovementPlan objects.
The brain NEVER directly modifies files or executes commands.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the reasoning core of a self-improving autonomous agent named Prometheus.

Your role:
- Analyse the current system state and performance metrics.
- Identify concrete, measurable weaknesses.
- Design safe, incremental improvement plans.
- Assess risk for every proposed change.

Output ONLY valid JSON matching this schema:
{
  "problem": "<concise description>",
  "root_cause": "<analysis>",
  "proposed_solution": "<what to do>",
  "expected_benefit": "<measurable outcome>",
  "risk": "<low|medium|high> — <explanation>",
  "requires_human_approval": true|false,
  "required_changes": [
    {"type": "code|config|dependency|docker", "target": "<path>", "description": "<what changes>"}
  ],
  "estimated_complexity": "<low|medium|high>"
}

Rules:
- requires_human_approval MUST be true for: architecture changes, new dependencies,
  deployment, external scripts, money spending, or deleting versions.
- Prefer low-risk incremental changes.
- Never propose changes to immutable_rules.
"""


@dataclass
class ImprovementPlan:
    """Structured output from the Brain."""

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
    """Simple TTL cache to avoid redundant LLM calls."""

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
    """LLM-powered reasoning engine via OpenRouter.

    Uses the OpenAI-compatible OpenRouter API to analyse system state
    and generate ImprovementPlan objects. Results are cached to minimise
    API usage.
    """

    def __init__(
        self,
        model: str,
        max_tokens: int,
        temperature: float,
        cache_ttl: int,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str | None = None,
    ) -> None:
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key or os.environ["OPENROUTER_API_KEY"],
        )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._cache = ReasoningCache(ttl_seconds=cache_ttl)

    def reason(self, system_state: dict[str, Any], goal: str) -> ImprovementPlan:
        """Analyse system state and produce an improvement plan.

        Args:
            system_state: Snapshot of the agent's current condition.
            goal: High-level objective for this reasoning cycle.

        Returns:
            A validated ImprovementPlan.
        """
        cache_key = self._make_cache_key(system_state, goal)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("Brain: returning cached reasoning result")
            return cached

        user_message = self._build_user_message(system_state, goal)
        logger.info("Brain: calling LLM (model=%s)", self._model)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            )
            raw = response.choices[0].message.content or ""
            plan = self._parse_plan(raw)
            self._cache.set(cache_key, plan)
            logger.info("Brain: plan generated (risk=%s approval=%s)", plan.risk, plan.requires_human_approval)
            return plan
        except Exception as exc:
            logger.error("Brain: LLM call failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_user_message(self, state: dict[str, Any], goal: str) -> str:
        return (
            f"GOAL: {goal}\n\n"
            f"SYSTEM STATE:\n{json.dumps(state, indent=2)}\n\n"
            "Analyse the state, identify the most impactful weakness, "
            "and produce an improvement plan as described."
        )

    def _parse_plan(self, raw: str) -> ImprovementPlan:
        """Extract JSON from LLM response and validate it."""
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON found in LLM response: {raw[:200]}")
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
    def _make_cache_key(state: dict[str, Any], goal: str) -> str:
        payload = json.dumps({"state": state, "goal": goal}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()
