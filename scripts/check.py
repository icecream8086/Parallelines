#!/usr/bin/env python3
"""Pre-commit / CI 全量检查脚本。

等价于 GitHub Actions workflow 的本地复现，但：
  1. 强制 PYTHONIOENCODING=utf-8（规避 Windows cp1252 编码崩溃）
  2. 跳过 queries/、docs/、devdocs/ 等非 Python 目录
  3. 汇总失败数，统一退出码

用法:
  python scripts/check.py              # 全量 (ruff + mypy + pytest)
  python scripts/check.py --quick      # 仅 ruff
  python scripts/check.py --no-pytest  # ruff + mypy
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _set_utf8() -> None:
    """Force UTF-8 for all subprocess and Python I/O on Windows."""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    # Reconfigure stdio if already opened in a lossy encoding
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def _run(cmd: list[str], *, timeout: int = 300) -> tuple[int, str]:
    """Run *cmd* and return (exit_code, output)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
        return proc.returncode, proc.stdout + "\n" + proc.stderr
    except subprocess.TimeoutExpired:
        return 1, f"TIMEOUT after {timeout}s: {' '.join(cmd)}"


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def run_ruff() -> int:
    """Ruff lint check. Only scans src/ and tests/ directories."""
    label = "ruff check"
    print(f"── {label} ──", flush=True)
    code, out = _run(["python", "-m", "ruff", "check", "src/", "tests/"])  # no --fix
    if code == 0:
        print(_green("  PASSED"))
        return 0
    # Only print lines with actual errors
    for line in out.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("Found ") and not stripped.startswith("help:") and not stripped.startswith("All checks"):
            print(f"  {stripped}")
    total = sum(1 for l in out.splitlines() if l.strip() and not l.startswith("help:"))
    print(_red(f"  FAILED ({total} issues)"))
    return code


def run_mypy() -> int:
    """Mypy type check. Only scans src/parallelines/."""
    label = "mypy"
    print(f"── {label} ──", flush=True)
    code, out = _run(["python", "-m", "mypy", "src/parallelines/", "--no-error-summary"])
    if code == 0:
        print(_green("  PASSED"))
        return 0
    # Print error lines only, skip empty/note lines
    errors = [l for l in out.splitlines() if "error:" in l]
    for line in errors[:30]:
        print(f"  {line.strip()}")
    if len(errors) > 30:
        print(f"  ... and {len(errors) - 30} more")
    print(_red(f"  FAILED ({len(errors)} type errors)"))
    return code


def run_pytest() -> int:
    """Full test suite (excludes slow/overnight markers)."""
    label = "pytest"
    print(f"── {label} ──", flush=True)
    code, out = _run([
        "python", "-m", "pytest",
        "-q", "--tb=short",
        "-m", "not slow and not overnight",
    ], timeout=600)
    if code == 0:
        # Extract pass count from final line
        for line in out.splitlines():
            if "passed" in line:
                print(_green(f"  {line.strip()}"))
                break
        return 0
    # Print failures
    for line in out.splitlines():
        if "FAILED" in line or "ERRORS" in line or "assert" in line[:20]:
            print(f"  {line.strip()}")
    final = [l for l in out.splitlines() if "failed" in l.lower() or "error" in l.lower()]
    if final:
        print(_red(f"  {final[-1].strip()}"))
    return code


def main() -> int:
    _set_utf8()

    import argparse
    parser = argparse.ArgumentParser(description="CI check script")
    parser.add_argument("--quick", action="store_true", help="ruff only")
    parser.add_argument("--no-pytest", action="store_true", help="skip pytest")
    parser.add_argument("--ruff-only", action="store_true", help="ruff only (alias)")
    parser.add_argument("--mypy-only", action="store_true", help="mypy only")
    args = parser.parse_args()

    failures = 0

    if args.mypy_only:
        failures += 1 if run_mypy() != 0 else 0
        return failures

    if args.quick or args.ruff_only:
        failures += 1 if run_ruff() != 0 else 0
        return failures

    # Full pipeline
    failures += 1 if run_ruff() != 0 else 0
    failures += 1 if run_mypy() != 0 else 0
    if not args.no_pytest:
        failures += 1 if run_pytest() != 0 else 0

    print()
    if failures == 0:
        print(_green("All checks passed."))
    else:
        print(_red(f"{failures} check(s) failed."))
    return failures


if __name__ == "__main__":
    sys.exit(main())
