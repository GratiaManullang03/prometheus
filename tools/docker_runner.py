"""Docker runner tool — manages containerised experiment lifecycle.

Workflow per experiment:
  1. Prepare temporary workspace copy
  2. Build Docker image
  3. Run container with resource limits and no network
  4. Capture logs
  5. Evaluate exit code
  6. Destroy container and image
"""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ContainerResult:
    """Outcome of a Docker experiment run."""

    experiment_id: str
    image_tag: str
    exit_code: int
    stdout: str
    stderr: str
    build_log: str
    success: bool
    error: Optional[str] = None
    logs_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "image_tag": self.image_tag,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:3000],
            "stderr": self.stderr[:3000],
            "success": self.success,
            "error": self.error,
            "logs_path": self.logs_path,
        }


class DockerRunner:
    """Manages isolated Docker experiments with full lifecycle control.

    Args:
        workspace_path: Host path cloned into containers.
        dockerfile_path: Path to the Dockerfile used for experiments.
        logs_dir: Where to persist container logs.
        memory_limit: Container memory cap (e.g. "512m").
        cpu_limit: CPU quota string (e.g. "1.0").
        timeout: Max seconds before container is killed.
    """

    def __init__(
        self,
        workspace_path: str,
        dockerfile_path: str,
        logs_dir: str,
        memory_limit: str = "512m",
        cpu_limit: str = "1.0",
        timeout: int = 300,
    ) -> None:
        self._workspace = Path(workspace_path)
        self._dockerfile = Path(dockerfile_path)
        self._logs_dir = Path(logs_dir)
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._memory = memory_limit
        self._cpu = cpu_limit
        self._timeout = timeout

    def run_experiment(
        self,
        experiment_id: str,
        code_patches: Optional[dict[str, str]] = None,
        test_command: str = "python -m pytest tests/ -v",
    ) -> ContainerResult:
        """Run a full experiment cycle inside Docker.

        Args:
            experiment_id: Unique identifier for this run.
            code_patches: Dict of {relative_path: new_content} to apply.
            test_command: Command to execute inside the container.

        Returns:
            ContainerResult with full outcome details.
        """
        image_tag = f"prometheus-exp-{experiment_id[:12]}"
        tmpdir = None

        try:
            tmpdir = self._prepare_workspace(code_patches)
            build_log = self._build_image(image_tag, tmpdir)
            result = self._run_container(experiment_id, image_tag, test_command)
            result.build_log = build_log
            result.logs_path = self._save_logs(experiment_id, result)
            logger.info(
                "DockerRunner: experiment %s finished (success=%s exit=%d)",
                experiment_id,
                result.success,
                result.exit_code,
            )
            return result
        except Exception as exc:
            logger.error("DockerRunner: experiment %s failed: %s", experiment_id, exc)
            return ContainerResult(
                experiment_id=experiment_id,
                image_tag=image_tag,
                exit_code=-1,
                stdout="",
                stderr="",
                build_log="",
                success=False,
                error=str(exc),
            )
        finally:
            self._cleanup(image_tag, tmpdir)

    # ------------------------------------------------------------------

    def _prepare_workspace(self, patches: Optional[dict[str, str]]) -> Path:
        """Copy workspace to temp dir and apply patches."""
        tmpdir = Path(tempfile.mkdtemp(prefix="prometheus_exp_"))
        if self._workspace.exists():
            shutil.copytree(
                self._workspace,
                tmpdir / "src",
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(
                    "venv", ".venv", "__pycache__", "*.pyc", "*.pyo",
                    ".git", "logs", "memory", "workspace", ".env",
                    "*.db", "*.db-wal", "*.db-shm",
                ),
            )
        shutil.copy2(self._dockerfile, tmpdir / "Dockerfile")
        if patches:
            src_root = (tmpdir / "src").resolve()
            for rel_path, content in patches.items():
                target = (src_root / rel_path).resolve()
                try:
                    target.relative_to(src_root)
                except ValueError:
                    raise ValueError(f"Path traversal blocked in patch key: {rel_path!r}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        logger.debug("DockerRunner: prepared workspace at %s", tmpdir)
        return tmpdir

    def _build_image(self, image_tag: str, context_dir: Path) -> str:
        """Build Docker image; return build log."""
        cmd = ["docker", "build", "-t", image_tag, str(context_dir)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"Docker build failed:\n{proc.stderr[:2000]}")
        logger.info("DockerRunner: image %s built", image_tag)
        return proc.stdout + proc.stderr

    def _run_container(self, exp_id: str, image_tag: str, command: str) -> ContainerResult:
        """Run container with resource limits; return result."""
        container_name = f"prom-{exp_id[:12]}"
        cmd = [
            "docker", "run",
            "--rm",
            "--name", container_name,
            "--network", "none",
            f"--memory={self._memory}",
            f"--cpus={self._cpu}",
            "--read-only",
            "--tmpfs", "/tmp",
            "--security-opt", "no-new-privileges:true",
            "--cap-drop", "ALL",
            image_tag,
            *shlex.split(command),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            return ContainerResult(
                experiment_id=exp_id,
                image_tag=image_tag,
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                build_log="",
                success=proc.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "stop", container_name], capture_output=True)
            return ContainerResult(
                experiment_id=exp_id,
                image_tag=image_tag,
                exit_code=-1,
                stdout="",
                stderr="Container timed out",
                build_log="",
                success=False,
                error="timeout",
            )

    def _save_logs(self, exp_id: str, result: ContainerResult) -> str:
        log_file = self._logs_dir / f"experiment_{exp_id}.log"
        content = (
            f"=== STDOUT ===\n{result.stdout}\n"
            f"=== STDERR ===\n{result.stderr}\n"
            f"=== BUILD ===\n{result.build_log}\n"
        )
        log_file.write_text(content, encoding="utf-8")
        return str(log_file)

    def _cleanup(self, image_tag: str, tmpdir: Optional[Path]) -> None:
        subprocess.run(["docker", "rmi", "-f", image_tag], capture_output=True)
        if tmpdir and tmpdir.exists():
            shutil.rmtree(tmpdir, ignore_errors=True)
        logger.debug("DockerRunner: cleanup done for %s", image_tag)
