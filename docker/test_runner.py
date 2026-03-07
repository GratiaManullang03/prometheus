"""Test runner script executed inside Docker containers.

This script runs inside the isolated container and reports
results in a machine-readable JSON format to stdout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def run_tests(test_dir: str = "tests") -> dict:
    """Execute pytest and capture structured output.

    Args:
        test_dir: Directory containing test files.

    Returns:
        Dict with status, counts, and output.
    """
    if not Path(test_dir).exists():
        return {
            "status": "skipped",
            "reason": f"No test directory found at {test_dir}",
            "passed": 0,
            "failed": 0,
            "duration_seconds": 0.0,
        }

    # Set PYTHONPATH to include /workspace for module discovery
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH", "")
    if current_pythonpath:
        env["PYTHONPATH"] = f"/workspace:{current_pythonpath}"
    else:
        env["PYTHONPATH"] = "/workspace"

    start = time.time()
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            test_dir, "-v",
            "--tb=short",
            "--no-header",
            "-q",
        ],
        capture_output=True,
        text=True,
        timeout=240,
        env=env,  # Pass the modified environment
    )
    duration = time.time() - start

    output = result.stdout + result.stderr
    passed = output.count(" passed")
    failed = output.count(" failed")
    errors = output.count(" error")

    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "passed": passed,
        "failed": failed + errors,
        "duration_seconds": round(duration, 2),
        "output": output[:5000],
    }


def run_linting() -> dict:
    """Run ruff for fast linting."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", ".", "--quiet"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {
            "linting_passed": result.returncode == 0,
            "linting_output": result.stdout[:2000],
        }
    except subprocess.TimeoutExpired:
        return {"linting_passed": False, "linting_output": "ruff timed out"}


def run_type_check() -> dict:
    """Run mypy for type checking."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "mypy", ".", "--ignore-missing-imports", "--no-error-summary"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {
            "type_check_passed": result.returncode == 0,
            "type_check_output": result.stdout[:2000],
        }
    except subprocess.TimeoutExpired:
        return {"type_check_passed": False, "type_check_output": "mypy timed out"}


if __name__ == "__main__":
    report = {
        "tests": run_tests(),
        "linting": run_linting(),
        "type_check": run_type_check(),
    }
    overall_pass = (
        report["tests"]["status"] in ("passed", "skipped")
        and report["linting"]["linting_passed"]
    )
    report["overall_passed"] = overall_pass

    print(json.dumps(report, indent=2))
    sys.exit(0 if overall_pass else 1)