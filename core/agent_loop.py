"""Agent loop — the main autonomous execution cycle.

Continuously:
  1. Observes system state
  2. Identifies weaknesses via the Brain
  3. Builds an ExecutionPlan via the Planner
  4. Executes tasks (with approval gate where required)
  5. Stores results to memory
  6. Sleeps until next cycle

Transaction Boundary: none (stateless cycle, each task is atomic via Docker)
Async Tasks: Telegram polling runs in background thread
Commit Point: after each completed cycle
Rollback Strategy: GitManager.rollback_to on experiment failure
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from communication.human_approval import (
    ApprovalContext,
    ApprovalRejected,
    ApprovalTimeout,
    HumanApprovalGate,
)
from core.brain import Brain, ImprovementPlan
from core.model_registry import ModelRegistry
from core.planner import ExecutionPlan, Planner, TaskStatus, TaskType
from experiments.experiment_manager import ExperimentManager
from memory.memory_manager import MemoryCategory, MemoryManager
from tools.browser_agent import BrowserAgent
from tools.file_editor import FileEditor
from tools.git_manager import GitManager

logger = logging.getLogger(__name__)


@dataclass
class SystemState:
    """Snapshot of agent health at the start of a cycle."""

    cycle_id: str
    timestamp: str
    uptime_seconds: float
    memory_stats: dict[str, int]
    git_status: dict[str, Any]
    recent_failures: list[dict]
    recent_successes: list[dict]
    pending_ideas: list[dict]
    workspace_files: list[str] = None  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "timestamp": self.timestamp,
            "uptime_seconds": self.uptime_seconds,
            "memory_stats": self.memory_stats,
            "git_status": self.git_status,
            "workspace_files": self.workspace_files or [],
            # Kirim konten aktual (bukan hanya hitungan) agar Brain bisa belajar
            "recent_failures": [
                {k: v for k, v in f.items() if k in ("description", "error", "plan_id")}
                for f in self.recent_failures[:3]
            ],
            "recent_successes": [
                {k: v for k, v in s.items() if k in ("description", "plan_id", "summary")}
                for s in self.recent_successes[:3]
            ],
            "pending_ideas_count": len(self.pending_ideas),
        }


class AgentLoop:
    """Main autonomous agent execution loop.

    Args:
        brain: LLM reasoning engine.
        planner: Task sequence builder.
        experiment_manager: Docker experiment runner.
        approval_gate: Human approval interface.
        memory: Persistent knowledge store.
        git: Version control manager.
        browser: Internet research tool.
        loop_interval: Seconds to sleep between cycles.
        goal: High-level objective for this agent instance.
    """

    def __init__(
        self,
        brain: Brain,
        planner: Planner,
        experiment_manager: ExperimentManager,
        approval_gate: HumanApprovalGate,
        memory: MemoryManager,
        git: GitManager,
        browser: BrowserAgent,
        file_editor: FileEditor,
        registry: ModelRegistry,
        loop_interval: int = 300,
        goal: str = "Improve agent performance, reliability and capabilities.",
        default_branch: str = "master",
    ) -> None:
        self._brain = brain
        self._planner = planner
        self._experiments = experiment_manager
        self._approval = approval_gate
        self._memory = memory
        self._git = git
        self._browser = browser
        self._file_editor = file_editor
        self._registry = registry
        self._interval = loop_interval
        self._goal = goal
        self._default_branch = default_branch
        self._start_time = time.time()
        self._running = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """Start the infinite agent loop."""
        self._running = True
        logger.info("AgentLoop: starting (interval=%ds)", self._interval)
        self._approval.notify("Prometheus agent started. Loop interval: %ds." % self._interval)

        while self._running:
            cycle_id = str(uuid.uuid4())[:12]
            try:
                self._run_cycle(cycle_id)
            except KeyboardInterrupt:
                logger.info("AgentLoop: interrupted by user")
                self._running = False
                break
            except Exception as exc:
                logger.error("AgentLoop: unhandled exception in cycle %s: %s", cycle_id, exc)
                self._memory.store(
                    MemoryCategory.PAST_FAILURES,
                    {"cycle_id": cycle_id, "error": str(exc), "phase": "agent_loop"},
                )
            if self._running:
                logger.info("AgentLoop: sleeping %ds until next cycle", self._interval)
                time.sleep(self._interval)

    def stop(self) -> None:
        """Request graceful shutdown after current cycle."""
        self._running = False
        logger.info("AgentLoop: stop requested")

    def get_status(self) -> str:
        """Return a formatted human-readable status string for the operator."""
        uptime = int(time.time() - self._start_time)
        hours, rem = divmod(uptime, 3600)
        minutes, seconds = divmod(rem, 60)

        mem_stats = self._memory.stats()
        model_health = self._registry.status()

        available = [mid for mid, info in model_health.items() if info["available"]]
        cooling = [mid.split("/")[-1] for mid, info in model_health.items() if info["cooling_down"]]

        lines = [
            "=== Prometheus Agent Status ===",
            f"Uptime  : {hours}h {minutes}m {seconds}s",
            f"Running : {'Ya' if self._running else 'Tidak (idle)'}",
            "",
            "Memory entries:",
        ]
        for cat, count in mem_stats.items():
            lines.append(f"  {cat}: {count}")

        lines += [
            "",
            f"Models  : {len(available)} tersedia, {len(cooling)} cooling down",
        ]
        if cooling:
            lines.append("Cooling : " + ", ".join(cooling[:3]))

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    def _run_cycle(self, cycle_id: str) -> None:
        logger.info("=== CYCLE %s START ===", cycle_id)

        state = self._observe(cycle_id)
        logger.info("AgentLoop: state observed — %d failures, %d successes in memory",
                    len(state.recent_failures), len(state.recent_successes))

        plan_obj = self._brain.reason(state.to_dict(), self._goal)
        logger.info("AgentLoop: brain produced plan (risk=%s)", plan_obj.risk)

        self._approval.notify(
            f"[Cycle {cycle_id[:8]}] Plan baru:\n"
            f"Problem: {plan_obj.problem[:120]}\n"
            f"Solusi: {plan_obj.proposed_solution[:120]}\n"
            f"Risk: {plan_obj.risk} | Approval: {'diperlukan' if plan_obj.requires_human_approval else 'tidak'}"
        )

        exec_plan = self._planner.build(plan_obj, cycle_id)
        self._execute_plan(exec_plan, plan_obj)

        completed = sum(1 for t in exec_plan.tasks if t.status.value == "completed")
        failed = sum(1 for t in exec_plan.tasks if t.status.value == "failed")
        self._approval.notify(
            f"[Cycle {cycle_id[:8]}] Selesai — {completed} task sukses, {failed} gagal."
        )

        logger.info("=== CYCLE %s END ===", cycle_id)

    def _observe(self, cycle_id: str) -> SystemState:
        """Build a snapshot of the current agent state."""
        try:
            git_status = vars(self._git.status())
        except Exception:
            git_status = {"error": "git unavailable"}

        return SystemState(
            cycle_id=cycle_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            uptime_seconds=time.time() - self._start_time,
            memory_stats=self._memory.stats(),
            git_status=git_status,
            recent_failures=self._memory.retrieve(MemoryCategory.PAST_FAILURES, limit=5),
            recent_successes=self._memory.retrieve(MemoryCategory.SUCCESSFUL_IMPROVEMENTS, limit=5),
            pending_ideas=self._memory.retrieve(MemoryCategory.IDEAS_BACKLOG, limit=10),
            workspace_files=self._list_workspace_files(),
        )

    def _list_workspace_files(self) -> list[str]:
        """List Python source files in the workspace (for Brain context)."""
        try:
            root = self._file_editor._root
            return sorted(
                str(p.relative_to(root))
                for p in root.rglob("*.py")
                if ".git" not in p.parts and "__pycache__" not in p.parts
            )[:30]
        except Exception:
            return []

    def _execute_plan(self, plan: ExecutionPlan, improvement: ImprovementPlan) -> None:
        """Walk through plan tasks and execute each one."""
        code_patches: dict[str, str] = {}

        for task in plan.tasks:
            if task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
                continue
            task.status = TaskStatus.IN_PROGRESS
            try:
                self._dispatch_task(task, plan, improvement, code_patches)
                task.status = TaskStatus.COMPLETED
            except (ApprovalRejected, ApprovalTimeout) as exc:
                logger.warning("AgentLoop: task %s halted: %s", task.task_id, exc)
                task.status = TaskStatus.SKIPPED
                self._skip_remaining(plan, task.task_id)
                break
            except Exception as exc:
                logger.error("AgentLoop: task %s failed: %s", task.task_id, exc)
                task.status = TaskStatus.FAILED
                self._skip_remaining(plan, task.task_id)
                break

        self._maybe_auto_apply(code_patches, plan, improvement)

    def _maybe_auto_apply(
        self, patches: dict[str, str], plan: ExecutionPlan, improvement: ImprovementPlan
    ) -> None:
        """Auto-persist patches for low-risk plans that passed Docker tests."""
        if improvement.requires_human_approval or not patches:
            return
        docker_passed = any(
            t.task_type == TaskType.DOCKER_TEST and t.status == TaskStatus.COMPLETED
            for t in plan.tasks
        )
        if docker_passed:
            self._auto_apply_patches(patches, plan.plan_id)

    def _auto_apply_patches(self, patches: dict[str, str], plan_id: str) -> None:
        """Write low-risk patches to workspace and commit."""
        try:
            for rel_path, content in patches.items():
                self._file_editor.write(rel_path, content)
                logger.info("AgentLoop: auto-applied → %s", rel_path)
            commit_msg = f"feat: auto-applied improvement from plan {plan_id[:8]}"
            self._git.commit_all(commit_msg)
            self._git.checkout(self._default_branch)
            logger.info("AgentLoop: low-risk patches committed for plan %s", plan_id[:8])
        except Exception as exc:
            logger.error("AgentLoop: gagal auto-apply patches: %s", exc)

    def _dispatch_task(
        self,
        task,
        plan: ExecutionPlan,
        improvement: ImprovementPlan,
        code_patches: dict[str, str],
    ) -> None:
        """Route a task to the appropriate handler."""
        handlers = {
            TaskType.RESEARCH: self._handle_research,
            TaskType.CODE_CHANGE: self._handle_code_change,
            TaskType.CONFIG_CHANGE: self._handle_code_change,
            TaskType.DEPENDENCY_INSTALL: self._handle_dependency,
            TaskType.DOCKER_TEST: self._handle_docker_test,
            TaskType.EVALUATE: self._handle_evaluate,
            TaskType.REQUEST_APPROVAL: self._handle_approval,
            TaskType.STORE_MEMORY: self._handle_store_memory,
            TaskType.ROLLBACK: self._handle_rollback,
        }
        handler = handlers.get(task.task_type)
        if handler is None:
            logger.warning("AgentLoop: no handler for task type %s", task.task_type)
            return
        handler(task, plan, improvement, code_patches)

    # ------------------------------------------------------------------
    # Task handlers
    # ------------------------------------------------------------------

    def _handle_research(self, task, plan, improvement, patches) -> None:
        query = task.payload.get("query", improvement.proposed_solution)
        result = self._browser.research(query)
        task.result = {"summary": result.summary, "sources": len(result.fetched_content)}
        self._memory.store(MemoryCategory.TOOL_DOCUMENTATION, {
            "query": query,
            "summary": result.summary,
        })

    def _handle_code_change(self, task, plan, improvement, patches) -> None:
        target = task.payload.get("target", "")
        description = task.payload.get("description", "")
        if not target:
            logger.warning("AgentLoop: code change task tanpa target — skip")
            return

        # Baca konten file saat ini dari workspace
        try:
            current = self._file_editor.read(target)
        except FileNotFoundError:
            current = ""
            logger.info("AgentLoop: %s belum ada — akan dibuat baru", target)

        # Kumpulkan konteks riset dari task sebelumnya
        research_context = ""
        for t in plan.tasks:
            if t.task_type == TaskType.RESEARCH and t.result:
                research_context = t.result.get("summary", "")
                break

        # Panggil Brain untuk generate kode yang sebenarnya
        new_content = self._brain.generate_code(
            current_content=current,
            change_description=description,
            target_path=target,
            context=research_context,
        )
        patches[target] = new_content
        logger.info(
            "AgentLoop: kode baru di-stage untuk %s (%d chars)",
            target, len(new_content),
        )

    def _handle_dependency(self, task, plan, improvement, patches) -> None:
        logger.info("AgentLoop: dependency install requires approval — deferring to approval gate")
        ctx = ApprovalContext(
            proposal=f"Install dependency: {task.payload.get('target', 'unknown')}",
            reason=task.description,
            expected_benefit=improvement.expected_benefit,
            risk_analysis="New dependencies may introduce security vulnerabilities.",
        )
        self._approval.request_and_wait(ctx)

    def _handle_docker_test(self, task, plan, improvement, patches) -> None:
        exp = self._experiments.run(
            plan_id=plan.plan_id,
            description=improvement.problem,
            code_patches=patches,
        )
        task.result = exp.to_dict()
        if exp.state.value not in ("success",):
            raise RuntimeError(f"Experiment failed: {exp.error}")

    def _handle_evaluate(self, task, plan, improvement, patches) -> None:
        docker_task = next(
            (t for t in plan.tasks if t.task_type == TaskType.DOCKER_TEST), None
        )
        success = (
            docker_task is not None
            and docker_task.status == TaskStatus.COMPLETED
            and docker_task.result.get("state") == "success"
        )
        task.result = {
            "passed": success,
            "expected": improvement.expected_benefit,
        }
        logger.info("AgentLoop: evaluation passed=%s", success)

    def _handle_approval(self, task, plan, improvement, patches) -> None:
        ctx = ApprovalContext(
            proposal=improvement.proposed_solution,
            reason=improvement.root_cause,
            expected_benefit=improvement.expected_benefit,
            risk_analysis=improvement.risk,
        )
        self._approval.request_and_wait(ctx)
        logger.info("AgentLoop: approval diterima untuk plan %s", plan.plan_id)

        # Setelah approval — apply patches ke workspace dan tag stable version
        self._apply_approved_patches(patches, plan.plan_id)

    def _apply_approved_patches(self, patches: dict[str, str], plan_id: str) -> None:
        """Apply kode yang sudah diapprove ke workspace dan buat stable tag."""
        if not patches:
            return
        try:
            for rel_path, content in patches.items():
                self._file_editor.write(rel_path, content)
                logger.info("AgentLoop: patch applied → %s", rel_path)

            commit_msg = f"feat: approved improvement from plan {plan_id[:8]}"
            commit_hash = self._git.commit_all(commit_msg)

            # Tentukan nomor versi dari tag terakhir
            tags = self._git.list_tags()
            version = self._next_version(tags)
            self._git.tag(version, f"Stable release after plan {plan_id[:8]}")
            self._git.checkout(self._default_branch)

            self._approval.notify(
                f"Perubahan berhasil di-commit sebagai {version} ({commit_hash[:8]})"
            )
            logger.info("AgentLoop: stable version tagged: %s", version)
        except Exception as exc:
            logger.error("AgentLoop: gagal apply approved patches: %s", exc)

    @staticmethod
    def _next_version(tags: list[str]) -> str:
        """Hitung versi berikutnya dari daftar tag yang ada."""
        import re
        versions = []
        for tag in tags:
            m = re.match(r"v(\d+)\.(\d+)", tag)
            if m:
                versions.append((int(m.group(1)), int(m.group(2))))
        if not versions:
            return "v0.1"
        major, minor = max(versions)
        return f"v{major}.{minor + 1}"

    def _handle_store_memory(self, task, plan, improvement, patches) -> None:
        self._memory.store(MemoryCategory.ARCHITECTURE_DECISIONS, {
            "plan_id": plan.plan_id,
            "summary": improvement.proposed_solution,
            "outcome": "pending_approval" if plan.requires_approval else "completed",
        })

    def _handle_rollback(self, task, plan, improvement, patches) -> None:
        logger.info("AgentLoop: rollback task triggered")

    @staticmethod
    def _skip_remaining(plan: ExecutionPlan, from_task_id: str) -> None:
        skip = False
        for task in plan.tasks:
            if task.task_id == from_task_id:
                skip = True
                continue
            if skip:
                task.status = TaskStatus.SKIPPED
