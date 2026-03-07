"""Experiment manager — orchestrates controlled improvement cycles.

Responsibilities:
- Spawn Docker-isolated experiment runs.
- Track experiment states and results.
- Evaluate outcomes against expected benefits.
- Trigger rollback on failure.
- Persist results to memory.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from memory.memory_manager import MemoryCategory, MemoryManager
from tools.docker_runner import DockerRunner
from tools.git_manager import GitManager

logger = logging.getLogger(__name__)


class ExperimentState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class Experiment:
    """Tracks the lifecycle of a single experiment."""

    experiment_id: str
    plan_id: str
    branch_name: str
    description: str
    code_patches: dict[str, str]
    test_command: str
    state: ExperimentState = ExperimentState.CREATED
    result: dict[str, Any] = field(default_factory=dict)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    rollback_commit: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "plan_id": self.plan_id,
            "branch_name": self.branch_name,
            "description": self.description,
            "state": self.state.value,
            "result": self.result,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


class ExperimentManager:
    """Manages the full experiment lifecycle.

    Args:
        docker: DockerRunner instance.
        git: GitManager for the workspace repo.
        memory: MemoryManager for persistence.
        branch_prefix: Prefix for experiment branches.
    """

    def __init__(
        self,
        docker: DockerRunner,
        git: GitManager,
        memory: MemoryManager,
        branch_prefix: str = "experiment",
    ) -> None:
        self._docker = docker
        self._git = git
        self._memory = memory
        self._branch_prefix = branch_prefix
        self._active: dict[str, Experiment] = {}

    def run(
        self,
        plan_id: str,
        description: str,
        code_patches: dict[str, str],
        test_command: str = "python -m pytest tests/ -v",
    ) -> Experiment:
        """Create, run, and evaluate an experiment.

        Args:
            plan_id: Parent plan identifier.
            description: Human-readable experiment goal.
            code_patches: File changes to apply in the container.
            test_command: Command to verify correctness.

        Returns:
            Completed Experiment with state set to SUCCESS or FAILED.
        """
        exp_id = str(uuid.uuid4())[:12]
        branch = f"{self._branch_prefix}/{exp_id}"

        exp = Experiment(
            experiment_id=exp_id,
            plan_id=plan_id,
            branch_name=branch,
            description=description,
            code_patches=code_patches,
            test_command=test_command,
        )
        self._active[exp_id] = exp

        try:
            self._start(exp)
            container_result = self._docker.run_experiment(
                experiment_id=exp_id,
                code_patches=code_patches,
                test_command=test_command,
            )
            exp.result = container_result.to_dict()

            if container_result.success:
                self._on_success(exp)
            else:
                reason = (
                container_result.error
                or container_result.stderr
                or container_result.stdout[:500]
                or "unknown error"
            )
                self._on_failure(exp, reason)

        except Exception as exc:
            self._on_failure(exp, str(exc))

        self._persist(exp)
        return exp

    # ------------------------------------------------------------------

    def _start(self, exp: Experiment) -> None:
        exp.state = ExperimentState.RUNNING
        exp.started_at = datetime.now(timezone.utc).isoformat()
        status = self._git.status()
        parts = status.last_commit.split()
        exp.rollback_commit = parts[0] if parts else None
        exp._original_branch = status.branch  # type: ignore[attr-defined]
        self._git.create_branch(exp.branch_name)
        logger.info("Experiment %s started on branch %s", exp.experiment_id, exp.branch_name)

    def _on_success(self, exp: Experiment) -> None:
        exp.state = ExperimentState.SUCCESS
        exp.finished_at = datetime.now(timezone.utc).isoformat()
        logger.info("Experiment %s SUCCEEDED", exp.experiment_id)

    def _on_failure(self, exp: Experiment, reason: str) -> None:
        exp.state = ExperimentState.FAILED
        exp.error = reason
        exp.finished_at = datetime.now(timezone.utc).isoformat()
        logger.warning("Experiment %s FAILED: %s", exp.experiment_id, reason[:200])
        self._rollback(exp)

    def _rollback(self, exp: Experiment) -> None:
        if not exp.rollback_commit:
            logger.warning("Experiment %s: no rollback commit known", exp.experiment_id)
            return
        try:
            original_branch = getattr(exp, "_original_branch", "main")
            self._git.rollback_to(exp.rollback_commit)
            self._git.checkout(original_branch)
            exp.state = ExperimentState.ROLLED_BACK
            logger.info("Experiment %s: rolled back to %s", exp.experiment_id, exp.rollback_commit[:8])
        except Exception as exc:
            logger.error("Experiment %s: rollback failed: %s", exp.experiment_id, exc)

    def _persist(self, exp: Experiment) -> None:
        category = (
            MemoryCategory.SUCCESSFUL_IMPROVEMENTS
            if exp.state == ExperimentState.SUCCESS
            else MemoryCategory.PAST_FAILURES
        )
        self._memory.store(category, exp.to_dict())
        logger.info("Experiment %s persisted to memory (%s)", exp.experiment_id, category.value)
