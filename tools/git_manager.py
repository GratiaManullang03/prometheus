"""Git manager tool — version control for the agent's workspace.

Manages experimental branches, commits, tags, and rollbacks.
All operations are on the workspace path — NOT the agent's own code.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GitStatus:
    branch: str
    is_clean: bool
    modified_files: list[str]
    untracked_files: list[str]
    last_commit: str


class GitError(Exception):
    """Raised on Git operation failure."""


class GitManager:
    """Wraps Git operations for the agent workspace.

    Args:
        repo_path: Absolute path to the Git repository.
        author_name: Commit author name.
        author_email: Commit author email.
    """

    def __init__(
        self,
        repo_path: str,
        author_name: str = "Prometheus Agent",
        author_email: str = "prometheus@agent.local",
    ) -> None:
        self._repo = Path(repo_path)
        self._author_name = author_name
        self._author_email = author_email
        self._env = {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        }

    def init(self) -> None:
        """Initialise repo if not already a Git repo."""
        if (self._repo / ".git").exists():
            return
        self._repo.mkdir(parents=True, exist_ok=True)
        self._git("init")
        self._git("commit", "--allow-empty", "-m", "chore: initial empty commit")
        logger.info("GitManager: initialised repo at %s", self._repo)

    def status(self) -> GitStatus:
        """Return working tree status."""
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD").strip()
        porcelain = self._git("status", "--porcelain").strip()
        last = self._git("log", "-1", "--oneline").strip()
        modified, untracked = [], []
        for line in porcelain.splitlines():
            indicator = line[:2].strip()
            path = line[3:].strip()
            if indicator in ("M", "A", "D", "R"):
                modified.append(path)
            elif indicator == "??":
                untracked.append(path)
        return GitStatus(
            branch=branch,
            is_clean=(not modified and not untracked),
            modified_files=modified,
            untracked_files=untracked,
            last_commit=last,
        )

    def create_branch(self, branch_name: str) -> None:
        """Create and checkout a new experimental branch."""
        self._git("checkout", "-b", branch_name)
        logger.info("GitManager: created branch %s", branch_name)

    def checkout(self, branch_or_ref: str) -> None:
        """Checkout an existing branch or ref."""
        self._git("checkout", branch_or_ref)
        logger.info("GitManager: checked out %s", branch_or_ref)

    def commit_all(self, message: str) -> str:
        """Stage all changes and create a commit; returns commit hash."""
        self._git("add", "-A")
        self._git("commit", "-m", message)
        commit_hash = self._git("rev-parse", "HEAD").strip()
        logger.info("GitManager: committed %s — %s", commit_hash[:8], message)
        return commit_hash

    def tag(self, tag_name: str, message: str = "") -> None:
        """Create an annotated tag."""
        args = ["tag", "-a", tag_name, "-m", message or tag_name]
        self._git(*args)
        logger.info("GitManager: tagged %s", tag_name)

    def rollback_to(self, commit_hash: str) -> None:
        """Hard-reset to a specific commit (experimental branch only)."""
        current = self.status().branch
        if current in ("main", "master"):
            raise GitError("Rollback on main/master branch is not allowed")
        self._git("reset", "--hard", commit_hash)
        logger.info("GitManager: rolled back to %s", commit_hash)

    def merge_to_main(self, feature_branch: str) -> None:
        """Merge an experimental branch into main via --no-ff."""
        self.checkout("main")
        self._git("merge", "--no-ff", feature_branch, "-m", f"merge: {feature_branch}")
        logger.info("GitManager: merged %s into main", feature_branch)

    def list_tags(self) -> list[str]:
        """Return all tags sorted by version."""
        output = self._git("tag", "--sort=version:refname").strip()
        return output.splitlines() if output else []

    def log(self, limit: int = 10) -> str:
        """Return formatted commit log."""
        return self._git("log", f"-{limit}", "--oneline", "--decorate")

    # ------------------------------------------------------------------

    def _git(self, *args: str) -> str:
        """Run a git command and return stdout."""
        import os
        # Minimal env — never expose secrets (API keys, tokens) to git subprocess
        safe_keys = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TERM"}
        env = {k: v for k, v in os.environ.items() if k in safe_keys}
        env.update(self._env)
        cmd = ["git", "-C", str(self._repo), *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            if result.returncode != 0:
                raise GitError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
            return result.stdout
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git command timed out: {args}") from exc
