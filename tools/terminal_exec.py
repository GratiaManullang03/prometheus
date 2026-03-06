"""Terminal executor tool — runs shell commands with timeout and capture.

IMPORTANT: This tool must only be used inside Docker experiment containers.
It must NOT be called on the host system during normal agent operation.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60  # seconds
_MAX_OUTPUT_BYTES = 1_000_000  # 1 MB


@dataclass
class CommandResult:
    """Result of a shell command execution."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:2000],
            "stderr": self.stderr[:2000],
            "timed_out": self.timed_out,
            "success": self.success,
        }


class TerminalExecutor:
    """Safe subprocess wrapper with timeout, output capture, and logging.

    Args:
        working_dir: Base directory for all commands.
        timeout: Default timeout in seconds.
        allowed_commands: Optional allowlist prefix list.
    """

    def __init__(
        self,
        working_dir: str = ".",
        timeout: int = _DEFAULT_TIMEOUT,
        allowed_commands: Optional[list[str]] = None,
    ) -> None:
        self._cwd = working_dir
        self._timeout = timeout
        self._allowlist = allowed_commands

    def run(self, command: str, timeout: Optional[int] = None) -> CommandResult:
        """Execute a shell command and return captured output.

        Args:
            command: Shell command string.
            timeout: Override default timeout for this call.

        Returns:
            CommandResult with exit code and output.
        """
        if not self._is_allowed(command):
            raise PermissionError(f"Command not in allowlist: {command!r}")

        effective_timeout = timeout if timeout is not None else self._timeout
        logger.info("TerminalExecutor.run: %s (timeout=%ds)", command, effective_timeout)

        try:
            proc = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                cwd=self._cwd,
                timeout=effective_timeout,
                env=self._safe_env(),
            )
            result = CommandResult(
                command=command,
                exit_code=proc.returncode,
                stdout=proc.stdout[:_MAX_OUTPUT_BYTES],
                stderr=proc.stderr[:_MAX_OUTPUT_BYTES],
            )
        except subprocess.TimeoutExpired:
            logger.warning("TerminalExecutor: command timed out: %s", command)
            result = CommandResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr="Command timed out",
                timed_out=True,
            )
        except Exception as exc:
            logger.error("TerminalExecutor: exception running %s: %s", command, exc)
            result = CommandResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(exc),
            )

        if result.success:
            logger.info("TerminalExecutor: exit_code=0 for %s", command)
        else:
            logger.warning(
                "TerminalExecutor: exit_code=%d for %s\nstderr: %s",
                result.exit_code,
                command,
                result.stderr[:500],
            )
        return result

    # ------------------------------------------------------------------

    def _is_allowed(self, command: str) -> bool:
        if self._allowlist is None:
            return True
        return any(command.strip().startswith(prefix) for prefix in self._allowlist)

    @staticmethod
    def _safe_env() -> dict[str, str]:
        """Minimal environment for subprocess — prevents env injection."""
        import os
        safe_keys = {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONPATH", "VIRTUAL_ENV"}
        return {k: v for k, v in os.environ.items() if k in safe_keys}
