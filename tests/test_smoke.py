"""Smoke tests — verify Prometheus modules can be imported and initialized.

These are the baseline tests that every self-improvement experiment must pass.
Run with: python -m pytest tests/ -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure workspace root is importable (needed when run in Docker)
sys.path.insert(0, str(Path(__file__).parent.parent))


# ------------------------------------------------------------------
# Import tests
# ------------------------------------------------------------------

def test_import_brain():
    from core.brain import Brain, ImprovementPlan


def test_import_planner():
    from core.planner import Planner, TaskType, ExecutionPlan


def test_import_memory():
    from memory.memory_manager import MemoryManager, MemoryCategory


def test_import_file_editor():
    from tools.file_editor import FileEditor


def test_import_git_manager():
    from tools.git_manager import GitManager


def test_import_browser_agent():
    from tools.browser_agent import BrowserAgent


def test_import_agent_loop():
    from core.agent_loop import AgentLoop, SystemState


def test_import_experiment_manager():
    from experiments.experiment_manager import ExperimentManager, Experiment


# ------------------------------------------------------------------
# Unit tests — core logic
# ------------------------------------------------------------------

def test_planner_builds_plan():
    from core.brain import ImprovementPlan
    from core.planner import Planner, TaskType

    improvement = ImprovementPlan(
        problem="Test problem",
        root_cause="Test root cause",
        proposed_solution="Add a test utility",
        expected_benefit="Better coverage",
        risk="low — reversible",
        requires_human_approval=False,
        required_changes=[
            {"type": "code", "target": "tools/file_editor.py", "description": "Add helper"}
        ],
        estimated_complexity="low",
    )
    plan = Planner().build(improvement, "test-cycle-001")
    assert len(plan.tasks) >= 3
    types = [t.task_type for t in plan.tasks]
    assert TaskType.RESEARCH in types
    assert TaskType.DOCKER_TEST in types
    assert TaskType.STORE_MEMORY in types


def test_improvement_plan_to_dict():
    from core.brain import ImprovementPlan

    plan = ImprovementPlan(
        problem="Bug fix",
        root_cause="Off-by-one",
        proposed_solution="Fix index",
        expected_benefit="No crash",
        risk="low — trivial fix",
        requires_human_approval=False,
        required_changes=[],
        estimated_complexity="low",
    )
    d = plan.to_dict()
    assert d["problem"] == "Bug fix"
    assert isinstance(d["required_changes"], list)


def test_memory_manager_store_retrieve(tmp_path):
    from memory.memory_manager import MemoryManager, MemoryCategory

    db = tmp_path / "test.db"
    mem = MemoryManager(db_path=str(db), max_entries=100)
    mem.store(MemoryCategory.PAST_FAILURES, {"error": "test error", "cycle": "x"})
    results = mem.retrieve(MemoryCategory.PAST_FAILURES, limit=5)
    assert len(results) == 1
    assert results[0]["content"]["error"] == "test error"


def test_memory_manager_stats(tmp_path):
    from memory.memory_manager import MemoryManager, MemoryCategory

    mem = MemoryManager(db_path=str(tmp_path / "stats.db"), max_entries=100)
    stats = mem.stats()
    assert isinstance(stats, dict)
    assert MemoryCategory.PAST_FAILURES.value in stats


def test_file_editor_read_write(tmp_path):
    from tools.file_editor import FileEditor

    editor = FileEditor(workspace_root=tmp_path)
    editor.write("subdir/hello.py", "x = 1\n")
    content = editor.read("subdir/hello.py")
    assert content == "x = 1\n"


def test_brain_parse_valid_json():
    """Brain should correctly parse a well-formed JSON improvement plan."""
    from core.brain import Brain, ImprovementPlan
    from core.model_registry import ModelRegistry

    registry = MagicMock(spec=ModelRegistry)
    brain = Brain(
        registry=registry,
        max_tokens=1024,
        temperature=0.3,
        cache_ttl=0,
        base_url="https://openrouter.ai/api/v1",
        api_key="test",
    )

    raw = json.dumps({
        "problem": "Slow search",
        "root_cause": "No index",
        "proposed_solution": "Add FTS index",
        "expected_benefit": "10x faster search",
        "risk": "low — additive",
        "requires_human_approval": False,
        "required_changes": [],
        "estimated_complexity": "low",
    })

    plan = brain._parse_plan(raw)
    assert isinstance(plan, ImprovementPlan)
    assert plan.problem == "Slow search"
