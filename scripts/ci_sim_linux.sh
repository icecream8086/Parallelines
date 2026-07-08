#!/usr/bin/env bash
# ci_sim_linux.sh — Simulate GitHub Actions Ubuntu runner environment
# Usage: bash scripts/ci_sim_linux.sh
#
# Creates a temporary conda env, builds, audits, then removes the env.

set -uo pipefail

# ---- Resolve repo root ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_NAME="_ci_sim_linux"

# Guard against empty REPO_ROOT (defense-in-depth)
if [ -z "${REPO_ROOT:-}" ] || [ ! -d "$REPO_ROOT" ]; then
    echo "ERROR: could not resolve repo root (SCRIPT_DIR=$SCRIPT_DIR)" >&2
    exit 1
fi

# ---- Cleanup trap (runs on exit, error, Ctrl+C, SIGTERM) ----
_cleanup() {
    local exit_rc=$?
    echo ""
    echo "--- Cleanup ---"
    # Remove temp env if it exists (silently ignore env-not-found)
    conda env remove -n "$ENV_NAME" -y 2>/dev/null || true
    # Restore original working directory
    cd "$REPO_ROOT" 2>/dev/null || true
    echo "=== Done (exit $exit_rc) ==="
    exit $exit_rc
}
trap _cleanup EXIT INT TERM

echo "=== CI Simulation: Linux runner ($ENV_NAME) ==="

# ---- 1. Isolate environment ----
unset PYTHONIOENCODING
unset PYTHONUTF8
unset PYTHONLEGACYWINDOWSFSENCODING
unset PYTHONPATH
unset PYTHONSTARTUP
unset PYTHONHOME
unset PYTHONDONTWRITEBYTECODE
unset PYTHONHASHSEED
unset PYTHONWARNINGS
unset PYTHONDEVMODE

# ---- 2. Force CI locale ----
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# ---- 3. Clear repo-level build artifacts ----
rm -rf "$REPO_ROOT/cache" "$REPO_ROOT/build" "$REPO_ROOT/dist" 2>/dev/null || true
rm -f "$REPO_ROOT"/*.spec 2>/dev/null || true

# ---- 4. Create temp conda env ----
echo ""
echo "--- Create conda env: $ENV_NAME ---"

# Remove any leftover env from previous failed run
conda env remove -n "$ENV_NAME" -y 2>/dev/null || true

# Retry up to 3 times for network flakes
for attempt in 1 2 3; do
    echo "  attempt $attempt"
    if conda create -n "$ENV_NAME" "python=3.11" pip setuptools wheel -c conda-forge -y --quiet 2>&1; then
        break
    fi
    if [ "$attempt" -eq 3 ]; then
        echo "FATAL: conda create failed after 3 attempts" >&2
        exit 1
    fi
    echo "  retrying in 5s..."
    sleep 5
done

conda run -n "$ENV_NAME" python -m pip cache purge || echo "  (pip cache purge skipped)"

# ---- 5. Environment sanity check ----
echo ""
echo "--- Environment check ---"
echo "LANG=$LANG, charmap=$(locale charmap 2>/dev/null || echo N/A)"
conda run -n "$ENV_NAME" python -c '
import sys, locale, os
e = os.environ
print("stdout=" + sys.stdout.encoding)
print("preferred=" + locale.getpreferredencoding())
print("fs=" + sys.getfilesystemencoding())
print("PYTHONIOENCODING=" + e.get("PYTHONIOENCODING", "unset"))
print("PYTHONUTF8=" + e.get("PYTHONUTF8", "unset"))
'

# ---- 6. Install project ----
echo ""
echo "--- Install ---"
cd "$REPO_ROOT"
if ! conda run -n "$ENV_NAME" pip install -e "$REPO_ROOT[dev,build]"; then
    echo "FATAL: pip install failed" >&2
    exit 1
fi

# ---- 7. Generate icon ----
echo ""
echo "--- Generate icon ---"
cd "$REPO_ROOT"
conda run -n "$ENV_NAME" python scripts/generate_ico.py || echo "  WARNING: icon generation failed (non-fatal)"

# ---- 8. Build ----
echo ""
echo "--- Build ---"
cd "$REPO_ROOT"
if ! conda run -n "$ENV_NAME" python scripts/build_exe.py --minimal; then
    echo "FATAL: build failed" >&2
    exit 1
fi

# ---- 9. Audit ----
echo ""
echo "--- Audit ---"
cd "$REPO_ROOT"
conda run -n "$ENV_NAME" python scripts/ci_audit.py dist/parallelines --json audit_report.json
AUDIT_RC=$?

# Exit with audit result (trap cleanup fires here)
exit $AUDIT_RC
