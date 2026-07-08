"""CI build artifact auditor — PYZ inspection + boot smoke test.

Usage:
    python scripts/ci_audit.py <dist_dir> [--json <out_path>]

Verifies a PyInstaller onedir build for module completeness.  No
subprocess text capture that depends on terminal encoding — the
frozen exe is only invoked with --version (pure ASCII output).
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _collect_expected_modules() -> set[str]:
    """Derive expected parallelines submodules from the source tree."""
    pkg_root = PROJECT_ROOT / "src" / "parallelines"
    modules: set[str] = {"parallelines"}
    for f in sorted(pkg_root.rglob("*.py")):
        rel = f.relative_to(pkg_root)
        parts = list(rel.parts)
        if rel.name == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = rel.stem
        mod = "parallelines." + ".".join(parts) if parts else "parallelines"
        modules.add(mod)
    return modules


EXPECTED_PARALLELINES_MODULES = _collect_expected_modules()

CRITICAL_MODULES = [
    "parallelines.cache",
    "parallelines.cache.manager",
    "parallelines.cache.strategies",
    "parallelines.repl.session",
    "parallelines.repl.commands",
    "parallelines.vfs.builder",
]


def get_pyz_modules(exe_path: Path) -> set[str]:
    """Extract Python module names from PYZ archive inside frozen exe."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller.utils.cliutils.archive_viewer",
            "--list", "--recursive", "--brief",
            str(exe_path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    modules: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("Contents of") and not line.startswith("Options in"):
            modules.add(line)
    return modules


def _find_exe(dist_dir: Path) -> Path | None:
    for name in ("parallelines.exe", "parallelines"):
        candidate = dist_dir / name
        if candidate.is_file():
            return candidate
    return None


def audit_build(dist_dir: Path) -> dict:
    report: dict = {
        "dist_dir": str(dist_dir),
        "status": "ok",
        "issues": [],
        "details": {},
    }

    internal_dir = dist_dir / "_internal"
    base_lib_zip = internal_dir / "base_library.zip"

    # ---- exe existence ----
    exe_path = _find_exe(dist_dir)
    if exe_path is None:
        return {**report, "status": "error", "issues": [f"exe not found in {dist_dir}"]}
    report["details"]["exe_size"] = exe_path.stat().st_size

    # ---- base_library.zip check ----
    if base_lib_zip.exists():
        with zipfile.ZipFile(base_lib_zip) as zf:
            par_in_zip = [f for f in zf.namelist() if "parallelines" in f]
        report["details"]["base_lib_zip_par_entries"] = len(par_in_zip)
        if par_in_zip:
            report["issues"].append(
                f"parallelines modules found in base_library.zip "
                f"({len(par_in_zip)} entries) — should be in PYZ only"
            )

    # ---- PYZ module list ----
    pyz_modules = get_pyz_modules(exe_path)
    par_modules = {m for m in pyz_modules if "parallelines" in m}
    report["details"]["pyz_total_entries"] = len(pyz_modules)
    report["details"]["pyz_par_entries"] = len(par_modules)
    report["details"]["pyz_par_modules"] = sorted(par_modules)

    # ---- Missing modules ----
    missing = EXPECTED_PARALLELINES_MODULES - par_modules
    if missing:
        report["status"] = "fail"
        report["details"]["missing_modules"] = sorted(missing)
        report["issues"].append(
            f"Missing {len(missing)} parallelines modules: {sorted(missing)}"
        )
    else:
        report["details"]["all_modules_present"] = True

    # ---- Critical modules ----
    missing_critical = [m for m in CRITICAL_MODULES if m not in par_modules]
    if missing_critical:
        report["status"] = "fail"
        report["details"]["missing_critical"] = missing_critical
        report["issues"].append(f"CRITICAL: missing {missing_critical}")

    # ---- Boot smoke test (--version only, pure ASCII) ----
    try:
        r = subprocess.run(
            [str(exe_path), "--version"],
            capture_output=True, text=True, timeout=15,
        )
        report["details"]["boot_version"] = r.stdout.strip()
        report["details"]["boot_ok"] = r.returncode == 0
        if r.returncode != 0:
            report["status"] = "fail"
            report["issues"].append(
                f"Boot test failed (rc={r.returncode}, stderr={r.stderr.strip()})"
            )
    except Exception as e:
        report["status"] = "fail"
        report["details"]["boot_ok"] = False
        report["issues"].append(f"Boot test exception: {e}")

    return report


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="CI build artifact auditor")
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument("--json", type=Path, help="JSON report path")
    args = parser.parse_args()

    report = audit_build(args.dist_dir.resolve())
    ok = report["status"] == "ok"

    print(f"\n{'='*60}")
    print(f"Audit: {args.dist_dir} [{'OK' if ok else 'FAIL'} {report['status']}]")
    print(f"{'='*60}")
    print(f"  EXE size:           {report['details'].get('exe_size', 'N/A')} bytes")
    print(f"  PYZ total modules:  {report['details'].get('pyz_total_entries', 'N/A')}")
    print(f"  PYZ parallelines:   {report['details'].get('pyz_par_entries', 'N/A')}")
    if report['details'].get('all_modules_present'):
        print(f"  All modules:        OK")
    if report['details'].get('boot_ok'):
        print(f"  Boot test:          OK ({report['details'].get('boot_version', '')})")
    for issue in report["issues"]:
        print(f"  ISSUE: {issue}")

    if args.json:
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nReport saved to {args.json}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
