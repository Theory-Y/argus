# Setup script for middlemarket-research-agent (Windows)
# Run once on each machine: powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"

# Always operate from the repo root (the directory this script lives in).
Set-Location -Path $PSScriptRoot

Write-Host "=== middlemarket-research-agent setup ===" -ForegroundColor Cyan

# ── 1. Node dependencies ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "[1/5] Installing Node.js dependencies..." -ForegroundColor Yellow
npm install

# ── 2. Python virtual environment ────────────────────────────────────────────
Write-Host ""
Write-Host "[2/5] Setting up Python virtual environment..." -ForegroundColor Yellow
if (-Not (Test-Path ".venv")) {
    python -m venv .venv
}
.venv\Scripts\pip install --quiet --upgrade pip
# Install the full, declared dependency set (not a hardcoded subset).
.venv\Scripts\pip install --quiet -r requirements.txt

# ── 3. System dependency: pandoc ─────────────────────────────────────────────
Write-Host ""
Write-Host "[3/5] Checking for pandoc..." -ForegroundColor Yellow
if (Get-Command pandoc -ErrorAction SilentlyContinue) {
    $v = (pandoc --version | Select-Object -First 1).Split(" ")[1]
    Write-Host "  pandoc $v already installed."
} else {
    Write-Host "  pandoc not found. Installing..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id JohnMacFarlane.Pandoc -e --silent
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install pandoc -y
    } elseif (Get-Command scoop -ErrorAction SilentlyContinue) {
        scoop install pandoc
    } else {
        Write-Host "  ERROR: No package manager found (winget / choco / scoop)." -ForegroundColor Red
        Write-Host "  Install pandoc manually: https://pandoc.org/installing.html" -ForegroundColor Red
        exit 1
    }
    # Refresh PATH so pandoc is available in this session.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
}

# ── 4. System dependency: headless browser (for PDF rendering) ───────────────
Write-Host ""
Write-Host "[4/5] Checking for a Chromium-family browser (PDF rendering)..." -ForegroundColor Yellow
$browser = $null
foreach ($b in @("chrome","chromium","msedge")) {
    $cmd = Get-Command $b -ErrorAction SilentlyContinue
    if ($cmd) { $browser = $cmd.Source; break }
}
if (-Not $browser) {
    foreach ($p in @(
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")) {
        if (Test-Path $p) { $browser = $p; break }
    }
}
if ($browser) {
    Write-Host "  Found browser: $browser"
} else {
    Write-Host "  No browser found. Microsoft Edge ships with Windows 10/11 — if this"
    Write-Host "  fails, install Chrome (winget install Google.Chrome) or set"
    Write-Host "  CHROMIUM_BIN to your browser path."
}

# ── 5. Generate the branded .dotx reference template ─────────────────────────
Write-Host ""
Write-Host "[5/5] Generating branded reference template -> output\theme\reference.dotx" -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "output\theme" | Out-Null
$templatePath = "output\theme\reference.dotx"
# Step (a): produce a base reference.dotx from pandoc's default if missing.
# Use cmd redirection to preserve binary bytes across PowerShell versions.
if (-Not (Test-Path $templatePath)) {
    cmd /c "pandoc --print-default-data-file reference.docx > `"$templatePath`""
}
# Step (b): apply the Theory Y institutional styling in-place (needs lxml from venv).
.venv\Scripts\python scripts\build_reference_dotx.py
Write-Host "  Branded template ready."

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Quick-start:"
Write-Host "  Run a memo         : /theory-y-memo TICKER"
Write-Host "  Re-brand template  : .venv\Scripts\python scripts\build_reference_dotx.py"
