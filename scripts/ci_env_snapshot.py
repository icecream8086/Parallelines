"""Environment snapshot for CI build diagnosis.

Captures Python/pip/conda environment state before PyInstaller build.
Outputs JSON for later comparison between CI and local environments.

Usage:
    python scripts/ci_env_snapshot.py [--output <path>]
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception as e:
        return f"<ERROR: {e}>"


def snapshot() -> dict:
    snap: dict = {
        "timestamp": run(["python", "-c", "import datetime; print(datetime.datetime.utcnow().isoformat())"]),
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "sys_path": sys.path,
            "prefix": sys.prefix,
            "base_prefix": getattr(sys, "base_prefix", ""),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "platform": platform.platform(),
        },
        "env_vars": {
            "CONDA_PREFIX": os.environ.get("CONDA_PREFIX", ""),
            "CONDA_DEFAULT_ENV": os.environ.get("CONDA_DEFAULT_ENV", ""),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "PATH_conda": [p for p in os.environ.get("PATH", "").split(os.pathsep) if "conda" in p.lower()],
        },
        "pip_list": run([sys.executable, "-m", "pip", "list", "--format", "json"]),
        "conda_list": run([sys.executable, "-m", "conda", "list", "--json"]),
        "collect_submodules_parallelines": run([
            sys.executable, "-c",
            "from PyInstaller.utils.hooks import collect_submodules; "
            "mods = collect_submodules('parallelines'); "
            "print(len(mods)); print('\\n'.join(sorted(mods)))",
        ]),
        "pyinstaller_version": run([
            sys.executable, "-c", "import PyInstaller; print(PyInstaller.__version__)"
        ]),
        "site_packages": run([
            sys.executable, "-c", "import site; print(site.getsitepackages())"
        ]),
        "pip_list_raw": run([sys.executable, "-m", "pip", "list", "--format", "freeze"]),
    }
    return snap


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="CI environment snapshot")
    parser.add_argument("--output", type=Path, default=Path("env_snapshot.json"))
    args = parser.parse_args()

    snap = snapshot()
    args.output.write_text(json.dumps(snap, indent=2, ensure_ascii=False))
    print(f"Environment snapshot saved to {args.output}")
    print(f"Python: {snap['python']['version']}")
    print(f"PyInstaller: {snap['pyinstaller_version']}")
    print(f"CONDA_PREFIX: {snap['env_vars']['CONDA_PREFIX']}")

    # Print collect_submodules summary
    cs_lines = snap['collect_submodules_parallelines'].split('\n')
    if cs_lines:
        print(f"collect_submodules('parallelines'): {cs_lines[0]} modules")

    return 0


if __name__ == "__main__":
    sys.exit(main())
