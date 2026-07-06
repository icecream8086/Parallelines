#!/usr/bin/env python
"""Parallelines build toolchain — lib + launcher separation.

Output structure:
    dist/parallelines/
    ├── parallelines.exe          # 启动器 (bootloader)
    └── _internal/                # Python 运行时 + 依赖库
        ├── parallelines/         #   lib: 主程序代码
        ├── srctools/             #   第三方依赖
        ├── networkx/
        └── ...
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
SPEC_DIR = PROJECT_ROOT / "scripts"
ICO_PATH = PROJECT_ROOT / "ico" / "logo.ico"


def _get_version() -> str:
    try:
        from importlib.metadata import version
        return version("parallelines")
    except Exception:
        return "0.1.0"


def _pyinstaller(*extra_args: str, name: str = "parallelines", minimal: bool = False) -> None:
    """Run PyInstaller with common base args.

    Args:
        minimal: If True, exclude pyarrow/pandas/numpy for a ~40MB build.
                 Cache falls back to no-cache mode in the runtime.
    """
    # Modules to exclude from the build (heavy or unnecessary)
    EXCLUDE = [
        "pytest", "_pytest",
        "setuptools", "distutils",
        "jinja2", "markupsafe",
        "matplotlib", "PIL",
        "scipy", "sklearn",
        "cv2", "torch",
        "tensorflow",
        # pyarrow optional modules (heavy, rarely used)
        "pyarrow.flight", "pyarrow.gandiva",
        # pyarrow optional
        "pyarrow.flight", "pyarrow.gandiva",
        "pyarrow.parquet.encryption",
        # textual extras
        "textual.devtools",
    ]

    args = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "--name", name,
        "--distpath", str(DIST_DIR),
        "--specpath", str(SPEC_DIR),
        # lib + launcher separation
        "--onedir",
        # strip debug symbols from binaries
        "--strip",
        # optimization level 1 (docstrings stripped, bytecode optimized)
        "--optimize", "1",
        # UPX compression (optional: ~40% smaller exe, slower build)
        # install upx from https://upx.github.io/ and uncomment:
        # "--upx-dir", "C:/path/to/upx",
        "--noupx",
        # collect data for our packages
        "--collect-data", "parallelines",
        "--collect-data", "srctools",
        "--collect-data", "textual",
        # bundle queries/ for --query / --list-presets
        "--add-data", f"queries{os.pathsep}queries",
    ]

    # Exclude unnecessary modules to reduce size
    # 极致缩小模式: 移除 pandas/pyarrow/numpy (~120MB)
    # 运行时自动回退到无缓存模式
    if minimal:
        for mod in ["pandas", "numpy", "pyarrow", "matplotlib"]:
            if mod not in EXCLUDE:
                EXCLUDE.append(mod)

    for mod in EXCLUDE:
        if mod not in args:
            args.append("--exclude-module")
            args.append(mod)

    if ICO_PATH.exists():
        args.extend(["--icon", str(ICO_PATH)])

    args.extend(extra_args)
    args.append(str(PROJECT_ROOT / "src" / "parallelines" / "cli.py"))

    print(f"\n$ {' '.join(args)}\n")
    subprocess.check_call(args)


def build_exe(minimal: bool = False) -> Path:
    """Build launcher + lib directory.

    Args:
        minimal: True for ~40MB build (no pandas/pyarrow, cache disabled).

    Structure:
        dist/parallelines/
        ├── parallelines.exe      # 启动器
        └── _internal/            # 库文件
            ├── parallelines/     #   主程序代码
            ├── srctools/
            ├── networkx/
            └── ...
    """
    label = "MINIMAL" if minimal else "DEFAULT"
    print("=" * 60)
    print(f"Parallelines v{_get_version()} — Build ({label})")
    print("=" * 60)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    _pyinstaller(minimal=minimal)
    out_dir = DIST_DIR / "parallelines"

    print(f"\n✅ Build complete: {out_dir}")
    print(f"   Launcher: {out_dir / 'parallelines.exe'}")
    print(f"   Library:  {out_dir / '_internal' / 'parallelines'}")
    return out_dir


def build_zip() -> Path:
    """Package the project source as .zip for distribution."""
    zip_name = DIST_DIR / f"parallelines-{_get_version()}-src.zip"
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    exclude_dirs = {".git", "__pycache__", ".venv", "cache", "reports",
                    ".mypy_cache", ".ruff_cache", ".pytest_cache", ".eggs",
                    "dist", "build", "*.egg-info"}
    exclude_exts = {".pyc", ".pyo"}

    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            rel = Path(root).relative_to(PROJECT_ROOT)
            # Skip excluded dirs
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.endswith(".egg-info")]
            parts = rel.parts
            if any(p in exclude_dirs for p in parts):
                continue
            for f in files:
                if any(f.endswith(ext) for ext in exclude_exts):
                    continue
                file_path = Path(root) / f
                arcname = f"parallelines-{_get_version()}/{rel / f}"
                zf.write(file_path, arcname)

    size = zip_name.stat().st_size / 1_000_000
    print(f"\n✅ Source zip: {zip_name} ({size:.1f} MB)")
    return zip_name


def build_msi() -> Path:
    """Build .msi installer with lib+launcher structure.

    Requires WiX toolset (candle.exe + light.exe) in PATH.
    Falls back to PyInstaller's MSI support if WiX is not available.
    """
    print("=" * 60)
    print(f"Parallelines v{_get_version()} — MSI Installer")
    print("=" * 60)

    has_wix = shutil.which("candle") and shutil.which("light")

    if has_wix:
        # First build the onedir
        build_exe()
        print("\nBuilding MSI with WiX...")
        # TODO: WiX .wxs template → candle → light → .msi
        print("WiX MSI builder not yet implemented")
        raise NotImplementedError("WiX MSI")
    else:
        # PyInstaller has built-in MSI via --msi flag with onedir
        print("Using PyInstaller MSI generator...")
        _pyinstaller("--msi")
        msi_path = DIST_DIR / "parallelines.msi"
        if not msi_path.exists():
            # PyInstaller names MSI after the spec
            for p in DIST_DIR.glob("*.msi"):
                msi_path = p
                break
        print(f"\n✅ MSI installer: {msi_path}")
        return msi_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Parallelines build toolchain")
    parser.add_argument("--exe", action="store_true", help="Build lib + launcher (default)")
    parser.add_argument("--minimal", action="store_true", help="极致缩小 (~40MB, 无缓存)")
    parser.add_argument("--msi", action="store_true", help="Build MSI installer")
    parser.add_argument("--zip", action="store_true", help="Package source as .zip")
    parser.add_argument("--all", action="store_true", help="Build all targets")

    args = parser.parse_args()

    opts = {k: v for k, v in vars(args).items() if v}
    if not opts or opts == {"minimal": True}:
        # Default or --minimal alone → build exe
        build_exe(minimal=bool(args.minimal))
        return 0

    if args.all or args.exe or args.minimal:
        build_exe(minimal=bool(args.minimal))
    if args.all or args.msi:
        # MSI 默认使用极致缩小模式（32MB），体积小适合分发
        build_exe(minimal=True)
        build_msi()
    if args.all or args.zip:
        build_zip()

    return 0


if __name__ == "__main__":
    sys.exit(main())
