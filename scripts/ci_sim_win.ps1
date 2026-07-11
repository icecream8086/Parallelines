# ci_sim_win.ps1 — Simulate GitHub Actions Windows runner environment
# Usage: pwsh -File scripts/ci_sim_win.ps1

$ErrorActionPreference = "Stop"

# ---- Resolve repo root ----
$repoRoot = $PSScriptRoot | Split-Path -Parent
if (-not $repoRoot -or -not (Test-Path $repoRoot)) {
    throw "Could not resolve repo root: $repoRoot"
}
$envName = "_ci_sim_win"

# ---- Cleanup function ----
function Invoke-Cleanup {
    Write-Host ""
    Write-Host "--- Cleanup: remove $envName ---"
    conda env remove -n $envName -y *>$null
    Write-Host "=== Done ==="
}

try {
    Write-Host "=== CI Simulation: Windows runner ($envName) ==="

    # ---- 1. Isolate environment ----
    @(
        "PYTHONIOENCODING", "PYTHONUTF8", "PYTHONLEGACYWINDOWSFSENCODING",
        "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
        "PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED", "PYTHONWARNINGS", "PYTHONDEVMODE"
    ) | ForEach-Object {
        Remove-Item "Env:$_" -ErrorAction SilentlyContinue
    }

    # ---- 2. Force CI code page ----
    [System.Console]::OutputEncoding = [System.Text.Encoding]::GetEncoding(1252)
    $OutputEncoding = [System.Text.Encoding]::GetEncoding(1252)
    Write-Host "Console encoding: cp1252"

    # ---- 3. Clear repo-level build artifacts ----
    @("$repoRoot\cache", "$repoRoot\build", "$repoRoot\dist") | ForEach-Object {
        if (Test-Path $_) {
            Remove-Item -Recurse -Force $_ -ErrorAction SilentlyContinue
            Write-Host "Cleared: $_"
        }
    }
    Get-ChildItem "$repoRoot\*.spec" -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Force
        Write-Host "Cleared: $($_.Name)"
    }

    # ---- 4. Create temp conda env (with retry) ----
    Write-Host ""
    Write-Host "--- Create conda env: $envName ---"

    # Remove any leftover env from previous failed run
    $existing = conda env list 2>&1 | Select-String "^$envName\s"
    if ($existing) {
        Write-Host "  removing existing env: $envName"
        conda env remove -n $envName -y 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  WARNING: failed to remove existing env, trying --force"
            conda env remove -n $envName -y --force 2>&1 | Out-Null
        }
        # Verify removal
        $stillThere = conda env list 2>&1 | Select-String "^$envName\s"
        if ($stillThere) {
            throw "Cannot remove existing env $envName — delete C:\Users\$env:USERNAME\miniconda3\envs\$envName manually"
        }
        Write-Host "  removed"
    }

    $created = $false
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Write-Host "  attempt $attempt"
        conda create -n $envName "python=3.11" pip setuptools wheel -c conda-forge -y
        if ($LASTEXITCODE -eq 0) {
            $created = $true
            break
        }
        if ($attempt -eq 3) {
            throw "conda create failed after 3 attempts"
        }
        Write-Host "  retrying in 5s..."
        Start-Sleep 5
    }
    if (-not $created) {
        throw "conda create failed"
    }

    conda run -n $envName python -m pip cache purge

    # ---- 5. Environment sanity check ----
    Write-Host ""
    Write-Host "--- Environment check ---"
    $checkScript = Join-Path $env:TEMP "_ci_check_encoding.py"
    @"
import sys, locale, os
e = os.environ
print("stdout=" + sys.stdout.encoding)
print("preferred=" + locale.getpreferredencoding())
print("fs=" + sys.getfilesystemencoding())
print("PYTHONIOENCODING=" + e.get("PYTHONIOENCODING", "unset"))
print("PYTHONUTF8=" + e.get("PYTHONUTF8", "unset"))
"@ | Out-File -FilePath $checkScript -Encoding utf8
    conda run -n $envName python $checkScript
    Remove-Item $checkScript -ErrorAction SilentlyContinue

    # ---- 6. Install project ----
    Write-Host ""
    Write-Host "--- Install ---"
    Push-Location $repoRoot
    try {
        conda run -n $envName pip install -e "$repoRoot[dev,build]"
        if ($LASTEXITCODE -ne 0) {
            throw "pip install failed (exit $LASTEXITCODE)"
        }
    } finally {
        Pop-Location
    }

    # ---- 7. Generate icon ----
    Write-Host ""
    Write-Host "--- Generate icon ---"
    Push-Location $repoRoot
    try {
        conda run -n $envName python scripts/generate_ico.py
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  WARNING: icon generation failed (non-fatal)"
        }
    } finally {
        Pop-Location
    }

    # ---- 8. Build ----
    Write-Host ""
    Write-Host "--- Build ---"
    Push-Location $repoRoot
    try {
        conda run -n $envName python scripts/build_exe.py --minimal
        if ($LASTEXITCODE -ne 0) {
            throw "build failed (exit $LASTEXITCODE)"
        }
    } finally {
        Pop-Location
    }

    # ---- 9. Audit ----
    Write-Host ""
    Write-Host "--- Audit ---"
    Push-Location $repoRoot
    try {
        conda run -n $envName python scripts/ci_audit.py dist/parallelines --json audit_report.json
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    Write-Host ""
    Write-Host "--- Audit exit code: $exitCode ---"
    exit $exitCode

} finally {
    Invoke-Cleanup
}
