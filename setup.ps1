# Setup script for middlemarket-research-agent (Windows)
# Run once on each machine: powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"

# Always operate from the repo root (the directory this script lives in).
Set-Location -Path $PSScriptRoot

Write-Host "=== middlemarket-research-agent setup ===" -ForegroundColor Cyan

# ── 1. Node dependencies ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "[1/3] Installing Node.js dependencies..." -ForegroundColor Yellow
npm install

# ── 2. Python virtual environment ────────────────────────────────────────────
Write-Host ""
Write-Host "[2/3] Setting up Python virtual environment..." -ForegroundColor Yellow
if (-Not (Test-Path ".venv")) {
    python -m venv .venv
}
.venv\Scripts\pip install --quiet --upgrade pip
# Install the full, declared dependency set (not a hardcoded subset).
.venv\Scripts\pip install --quiet -r requirements.txt

# ── 3. Node module: md-to-pdf (bundled with Chromium/Puppeteer) ───────────────
Write-Host ""
Write-Host "[3/3] Verifying md-to-pdf installation..." -ForegroundColor Yellow
if (Test-Path ".\node_modules\.bin\md-to-pdf.cmd") {
    Write-Host "  md-to-pdf ready (bundled with npm dependencies)."
} else {
    Write-Host "  WARNING: md-to-pdf not found in node_modules." -ForegroundColor Yellow
    Write-Host "  Run 'npm install' to set it up."
}

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Quick-start:"
Write-Host "  Export memo to PDF : python scripts/export_pdf.py output/memos/TheoryY_Memo_TICKER.md"
