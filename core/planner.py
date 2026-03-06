"""Planner — converts ImprovementPlan into actionable task sequences."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.brain import ImprovementPlan

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    RESEARCH = "research"
    CODE_CHANGE = "code_change"
    CONFIG_CHANGE = "config_change"
    DEPENDENCY_INSTALL = "dependency_install"
    DOCKER_TEST = "docker_test"
    EVALUATE = "evaluate"
    REQUEST_APPROVAL = "request_approval"
    ROLLBACK = "rollback"
    STORE_MEMORY = "store_memory"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Task:
    """A single executable step in an experiment plan."""

    task_id: str
    task_type: TaskType
    description: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "description": self.description,
            "payload": self.payload,
            "status": self.status.value,
            "result": self.result,
            "depends_on": self.depends_on,
        }


@dataclass
class ExecutionPlan:
    """Ordered sequence of tasks for a single improvement cycle."""

    plan_id: str
    origin: ImprovementPlan
    tasks: list[Task] = field(default_factory=list)
    requires_approval: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "requires_approval": self.requires_approval,
            "origin": self.origin.to_dict(),
            "tasks": [t.to_dict() for t in self.tasks],
        }


class Planner:
    """Converts an ImprovementPlan into a concrete ExecutionPlan.

    Task sequencing rules:
    1. Research always comes first.
    2. Code/config changes come after research.
    3. Docker tests come after changes.
    4. Approval request (if needed) comes after tests.
    5. Memory storage is always the final step.
    """

    def build(self, improvement: ImprovementPlan, cycle_id: str) -> ExecutionPlan:
        """Build an ordered ExecutionPlan from an ImprovementPlan."""
        plan = ExecutionPlan(
            plan_id=cycle_id,
            origin=improvement,
            requires_approval=improvement.requires_human_approval,
        )

        step = 0

        def make_id() -> str:
            nonlocal step
            step += 1
            return f"{cycle_id}_task_{step:02d}"

        # Step 1 — research (always)
        plan.tasks.append(Task(
            task_id=make_id(),
            task_type=TaskType.RESEARCH,
            description=f"Research solutions for: {improvement.problem}",
            payload={"query": improvement.proposed_solution},
        ))

        # Step 2 — changes derived from required_changes
        prev_id = plan.tasks[-1].task_id
        change_ids: list[str] = []
        for change in improvement.required_changes:
            tid = make_id()
            task_type = self._change_type(change.get("type", "code"))
            plan.tasks.append(Task(
                task_id=tid,
                task_type=task_type,
                description=change.get("description", "Apply change"),
                payload=change,
                depends_on=[prev_id],
            ))
            change_ids.append(tid)
            prev_id = tid

        # Step 3 — Docker test (always)
        test_id = make_id()
        plan.tasks.append(Task(
            task_id=test_id,
            task_type=TaskType.DOCKER_TEST,
            description="Run isolated Docker test suite",
            payload={"improvement": improvement.problem},
            depends_on=change_ids or [plan.tasks[0].task_id],
        ))

        # Step 4 — evaluate results
        eval_id = make_id()
        plan.tasks.append(Task(
            task_id=eval_id,
            task_type=TaskType.EVALUATE,
            description="Evaluate experiment outcomes against expected benefit",
            payload={"expected_benefit": improvement.expected_benefit},
            depends_on=[test_id],
        ))

        # Step 5 — request approval if required
        if improvement.requires_human_approval:
            approve_id = make_id()
            plan.tasks.append(Task(
                task_id=approve_id,
                task_type=TaskType.REQUEST_APPROVAL,
                description="Send improvement proposal to human operator",
                payload=improvement.to_dict(),
                depends_on=[eval_id],
            ))
            prev_last = approve_id
        else:
            prev_last = eval_id

        # Step 6 — store memory (always last)
        plan.tasks.append(Task(
            task_id=make_id(),
            task_type=TaskType.STORE_MEMORY,
            description="Persist experiment results to memory",
            payload={},
            depends_on=[prev_last],
        ))

        logger.info(
            "Planner: built %d tasks for plan %s (approval=%s)",
            len(plan.tasks),
            plan.plan_id,
            plan.requires_approval,
        )
        return plan

    # ------------------------------------------------------------------

    @staticmethod
    def _change_type(change_type_str: str) -> TaskType:
        mapping = {
            "code": TaskType.CODE_CHANGE,
            "config": TaskType.CONFIG_CHANGE,
            "dependency": TaskType.DEPENDENCY_INSTALL,
            "docker": TaskType.DOCKER_TEST,
        }
        return mapping.get(change_type_str, TaskType.CODE_CHANGE)
