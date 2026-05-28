# Setup script for middlemarket-research-agent (Windows)
# Run once on each machine: powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== middlemarket-research-agent setup ===" -ForegroundColor Cyan

# ── 1. Node dependencies ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "[1/4] Installing Node.js dependencies..." -ForegroundColor Yellow
npm install

# ── 2. Python virtual environment ────────────────────────────────────────────
Write-Host ""
Write-Host "[2/4] Setting up Python virtual environment..." -ForegroundColor Yellow
if (-Not (Test-Path ".venv")) {
    python -m venv .venv
}
.venv\Scripts\pip install --quiet --upgrade pip
.venv\Scripts\pip install --quiet mcp yfinance requests

# ── 3. System dependency: pandoc ─────────────────────────────────────────────
Write-Host ""
Write-Host "[3/4] Checking for pandoc..." -ForegroundColor Yellow

if (Get-Command pandoc -ErrorAction SilentlyContinue) {
    $v = (pandoc --version | Select-Object -First 1).Split(" ")[1]
    Write-Host "  pandoc $v already installed."
} else {
    Write-Host "  pandoc not found. Installing..."

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  Using winget..."
        winget install --id JohnMacFarlane.Pandoc -e --silent
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        Write-Host "  Using Chocolatey..."
        choco install pandoc -y
    } elseif (Get-Command scoop -ErrorAction SilentlyContinue) {
        Write-Host "  Using Scoop..."
        scoop install pandoc
    } else {
        Write-Host ""
        Write-Host "  ERROR: No package manager found (winget / choco / scoop)." -ForegroundColor Red
        Write-Host "  Install pandoc manually: https://pandoc.org/installing.html" -ForegroundColor Red
        Write-Host "  Then re-run this script."
        exit 1
    }

    # Refresh PATH so pandoc is available in this session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
}

# ── 4. Generate default .dotx reference template ────────────────────────────
Write-Host ""
Write-Host "[4/4] Checking for .dotx reference template..." -ForegroundColor Yellow

$templatePath = "output\theme\reference.dotx"
if (-Not (Test-Path $templatePath)) {
    New-Item -ItemType Directory -Force -Path "output\theme" | Out-Null
    pandoc --print-default-data-file reference.docx | Set-Content $templatePath -Encoding Byte
    Write-Host "  Generated: $templatePath"
    Write-Host "  Open it in Word to apply your branding, then save."
} else {
    Write-Host "  Template already exists: $templatePath"
}

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Quick-start:"
Write-Host "  Customize styles : open output\theme\reference.dotx in Microsoft Word"
Write-Host "  Run a memo       : /theory-y-memo TICKER"
