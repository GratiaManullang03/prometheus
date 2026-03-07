"""AgentContext — shared resources passed to external tool plugins.

External handlers registered via AgentLoop.register_tool() receive
this context as their last argument, giving them full access to all
agent capabilities without tight coupling to AgentLoop internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from communication.human_approval import HumanApprovalGate
    from core.brain import Brain
    from core.model_registry import ModelRegistry
    from experiments.experiment_manager import ExperimentManager
    from memory.memory_manager import MemoryManager
    from tools.browser_agent import BrowserAgent
    from tools.file_editor import FileEditor
    from tools.git_manager import GitManager


@dataclass
class AgentContext:
    """Bag of shared agent resources for external tool plugins.

    Passed as the final argument to every handler registered via
    AgentLoop.register_tool(). Use this to access brain, memory,
    git, browser, file_editor, experiments, and approval gate.

    Example usage in a plugin handler:
        def my_handler(task, plan, improvement, patches, ctx: AgentContext):
            result = ctx.brain.generate_code(...)
            ctx.memory.store(MemoryCategory.EXPERIMENT_RESULTS, {...})
    """

    brain: "Brain"
    memory: "MemoryManager"
    git: "GitManager"
    browser: "BrowserAgent"
    file_editor: "FileEditor"
    experiments: "ExperimentManager"
    approval: "HumanApprovalGate"
    registry: "ModelRegistry"
    default_branch: str
