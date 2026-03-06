"""Prometheus — Self-Improving Autonomous Agent entry point.

Bootstraps all components and starts the agent loop.
Configuration is loaded from config/config.yaml with
environment variable overrides for secrets.

Usage:
    python main.py [--once] [--goal "custom goal text"]
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import yaml

# Load .env sebelum apapun — variabel di sini akan tersedia via os.environ
load_dotenv(Path(__file__).parent / ".env")

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent))

from communication.human_approval import HumanApprovalGate
from communication.telegram_bot import TelegramBot
from core.agent_loop import AgentLoop
from core.brain import Brain
from core.model_registry import ModelRegistry
from core.planner import Planner
from experiments.experiment_manager import ExperimentManager
from memory.memory_manager import MemoryManager
from tools.browser_agent import BrowserAgent
from tools.docker_runner import DockerRunner
from tools.file_editor import FileEditor
from tools.git_manager import GitManager


def load_config(config_path: str = "config/config.yaml") -> dict:
    """Load and expand environment variables in config."""
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = fh.read()

    # Expand ${VAR} patterns
    import re
    def expand_env(match: re.Match) -> str:
        var = match.group(1)
        value = os.environ.get(var, "")
        if not value:
            logging.warning("Config: environment variable %s is not set", var)
        return value

    expanded = re.sub(r"\$\{([^}]+)\}", expand_env, raw)
    return yaml.safe_load(expanded)


def setup_logging(level: str, log_dir: str) -> None:
    """Configure structured logging to file and stdout."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / "agent.log"

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=100 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        ),
    ]
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format=fmt, handlers=handlers)


def build_components(cfg: dict) -> tuple:
    """Instantiate all agent components from config."""
    mem_cfg = cfg["memory"]
    memory = MemoryManager(
        db_path=mem_cfg["db_path"],
        max_entries=mem_cfg["max_entries_per_category"],
    )

    llm_cfg = cfg["llm"]
    registry = ModelRegistry(
        default_model=llm_cfg["model"],
        cooldown_seconds=llm_cfg.get("model_cooldown_seconds", 300),
    )
    brain = Brain(
        registry=registry,
        max_tokens=llm_cfg["max_tokens"],
        temperature=llm_cfg["temperature"],
        cache_ttl=llm_cfg["cache_ttl_seconds"],
        base_url=llm_cfg["base_url"],
        api_key=llm_cfg["api_key"],
    )

    planner = Planner()

    git_cfg = cfg["git"]
    git = GitManager(
        repo_path=git_cfg["workspace_path"],
        author_name="Prometheus Agent",
        author_email="prometheus@agent.local",
    )
    git.init()

    docker_cfg = cfg["docker"]
    docker = DockerRunner(
        workspace_path=git_cfg["workspace_path"],
        dockerfile_path="docker/Dockerfile",
        logs_dir=cfg["logging"]["path"],
        memory_limit=docker_cfg["memory_limit"],
        cpu_limit=docker_cfg["cpu_limit"],
        timeout=docker_cfg["timeout_seconds"],
    )

    experiments = ExperimentManager(
        docker=docker,
        git=git,
        memory=memory,
    )

    file_editor = FileEditor(workspace_root=Path(git_cfg["workspace_path"]))

    tg_cfg = cfg["telegram"]
    bot = TelegramBot(
        token=tg_cfg["bot_token"],
        chat_id=tg_cfg["chat_id"],
    )
    bot.start_polling()

    gate = HumanApprovalGate(
        bot=bot,
        default_timeout=tg_cfg["approval_timeout_seconds"],
    )

    browser = BrowserAgent()

    return brain, planner, experiments, gate, memory, git, browser, bot, file_editor, registry


def main() -> None:
    """Bootstrap and run the Prometheus agent."""
    parser = argparse.ArgumentParser(description="Prometheus Self-Improving Agent")
    parser.add_argument("--config", default="config/config.yaml", help="Config file path")
    parser.add_argument("--once", action="store_true", help="Run a single cycle then exit")
    parser.add_argument("--goal", default=None, help="Override agent goal")
    args = parser.parse_args()

    cfg = load_config(args.config)
    agent_cfg = cfg["agent"]

    setup_logging(
        level=agent_cfg.get("log_level", "INFO"),
        log_dir=cfg["logging"]["path"],
    )

    logger = logging.getLogger("prometheus.main")
    logger.info("Prometheus v%s starting", agent_cfg["version"])

    brain, planner, experiments, gate, memory, git, browser, bot, file_editor, registry = build_components(cfg)

    loop = AgentLoop(
        brain=brain,
        planner=planner,
        experiment_manager=experiments,
        approval_gate=gate,
        memory=memory,
        git=git,
        browser=browser,
        file_editor=file_editor,
        registry=registry,
        loop_interval=agent_cfg["loop_interval_seconds"],
        goal=args.goal or "Improve agent performance, reliability, and capabilities.",
    )

    bot.set_status_provider(loop.get_status)

    try:
        if args.once:
            import uuid
            loop._run_cycle(str(uuid.uuid4())[:12])
        else:
            loop.run_forever()
    except KeyboardInterrupt:
        logger.info("Prometheus: shutdown requested")
    finally:
        bot.stop_polling()
        logger.info("Prometheus: shutdown complete")


if __name__ == "__main__":
    main()
