# Setup script for middlemarket-research-agent (Windows)
# Zero prerequisites — only PowerShell 5.1+ is required (ships with Windows 10/11).
# Run:  powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# ── colour helpers ────────────────────────────────────────────────────────────
function Write-Step { param($msg) Write-Host ""; Write-Host $msg -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  [OK]  $msg" -ForegroundColor Green }
function Write-Info { param($msg) Write-Host "  $msg" }
function Write-Warn { param($msg) Write-Host "  WARNING: $msg" -ForegroundColor Yellow }
function Write-Err  { param($msg) Write-Host "  ERROR: $msg" -ForegroundColor Red; exit 1 }

# Re-read Machine + User PATH so newly-installed tools are visible in this session
function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")   + ";" +
                $env:Path
}

Write-Host ""
Write-Host "=== middlemarket-research-agent setup ===" -ForegroundColor Cyan

# ── 1. Node.js ────────────────────────────────────────────────────────────────
Write-Step "[1/5] Node.js"
$needNode = -Not (Get-Command node -ErrorAction SilentlyContinue)
if (-Not $needNode) {
    Write-OK "node $(node --version)  npm $(npm --version)"
} else {
    Write-Info "node/npm not found — installing Node.js LTS..."
    $installed = $false

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id OpenJS.NodeJS.LTS -e --silent `
            --accept-source-agreements --accept-package-agreements
        $installed = $true
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install nodejs-lts -y
        $installed = $true
    } elseif (Get-Command scoop -ErrorAction SilentlyContinue) {
        scoop install nodejs-lts
        $installed = $true
    }

    if (-Not $installed) {
        Write-Info "No package manager found — downloading Node.js LTS installer..."
        try {
            $meta    = Invoke-RestMethod "https://nodejs.org/dist/index.json"
            $ltsVer  = ($meta | Where-Object { $_.lts -ne $false } | Select-Object -First 1).version
        } catch {
            $ltsVer = "v22.14.0"   # pinned fallback (LTS at time of writing)
        }
        $arch  = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
        $msi   = "$env:TEMP\node_lts_installer.msi"
        Invoke-WebRequest "https://nodejs.org/dist/$ltsVer/node-$ltsVer-$arch.msi" -OutFile $msi
        Start-Process msiexec.exe -ArgumentList "/i", $msi, "/quiet", "/norestart" -Wait
        Remove-Item $msi
    }

    Refresh-Path
    if (-Not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Err "Node.js install failed. Install from https://nodejs.org/ and re-run."
    }
    Write-OK "node $(node --version) installed"
}

Write-Info "Running npm install..."
npm install
Write-OK "Node.js dependencies installed"

# ── 2. Python ─────────────────────────────────────────────────────────────────
Write-Step "[2/5] Python"

# Detect Python 3.10+
$pythonOK = $false
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)\." -and [int]$Matches[1] -ge 10) {
            $pythonOK = $true
            $pythonCmd = $cmd
            break
        }
    } catch {}
}

if ($pythonOK) {
    Write-OK "$pythonCmd --version → $($ver)"
} else {
    Write-Info "Python 3.10+ not found — installing Python 3.12..."
    $installed = $false

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Python.Python.3.12 -e --silent `
            --accept-source-agreements --accept-package-agreements
        $installed = $true
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install python312 -y
        $installed = $true
    } elseif (Get-Command scoop -ErrorAction SilentlyContinue) {
        scoop install python
        $installed = $true
    }

    if (-Not $installed) {
        Write-Info "No package manager — downloading Python 3.12 installer..."
        $arch = if ([Environment]::Is64BitOperatingSystem) { "amd64" } else { "win32" }
        $exe  = "$env:TEMP\python312_installer.exe"
        Invoke-WebRequest "https://www.python.org/ftp/python/3.12.10/python-3.12.10-$arch.exe" -OutFile $exe
        Start-Process $exe -ArgumentList `
            "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0" -Wait
        Remove-Item $exe
    }

    Refresh-Path
    $pythonCmd = $null
    foreach ($cmd in @("python", "python3")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) { $pythonCmd = $cmd; break }
    }
    if (-Not $pythonCmd) {
        Write-Err "Python install failed. Download from https://www.python.org/downloads/"
    }
    Write-OK "$($& $pythonCmd --version)"
}

# ── 3. Python virtual environment ─────────────────────────────────────────────
Write-Info "Setting up Python virtual environment..."
if (-Not (Test-Path ".venv")) {
    & $pythonCmd -m venv .venv
}
.venv\Scripts\pip install --quiet --upgrade pip
.venv\Scripts\pip install --quiet -r requirements.txt
Write-OK "Python virtual environment ready (.venv)"

# ── 4. pandoc ─────────────────────────────────────────────────────────────────
Write-Step "[3/5] pandoc"
if (Get-Command pandoc -ErrorAction SilentlyContinue) {
    $v = (pandoc --version | Select-Object -First 1).Split(" ")[1]
    Write-OK "pandoc $v"
} else {
    Write-Info "pandoc not found — installing..."
    $installed = $false

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id JohnMacFarlane.Pandoc -e --silent `
            --accept-source-agreements --accept-package-agreements
        $installed = $true
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install pandoc -y
        $installed = $true
    } elseif (Get-Command scoop -ErrorAction SilentlyContinue) {
        scoop install pandoc
        $installed = $true
    }

    if (-Not $installed) {
        Write-Info "No package manager — downloading pandoc MSI installer..."
        $PANDOC_VER = "3.6.4"
        $arch = if ([Environment]::Is64BitOperatingSystem) { "windows-x86_64" } else { "windows-i386" }
        $msi  = "$env:TEMP\pandoc_installer.msi"
        Invoke-WebRequest `
            "https://github.com/jgm/pandoc/releases/download/$PANDOC_VER/pandoc-$PANDOC_VER-$arch.msi" `
            -OutFile $msi
        Start-Process msiexec.exe -ArgumentList "/i", $msi, "/quiet", "/norestart" -Wait
        Remove-Item $msi
    }

    Refresh-Path
    if (-Not (Get-Command pandoc -ErrorAction SilentlyContinue)) {
        Write-Err "pandoc install failed. Install from https://pandoc.org/installing.html"
    }
    $v = (pandoc --version | Select-Object -First 1).Split(" ")[1]
    Write-OK "pandoc $v installed"
}

# ── 5. Chromium (headless PDF rendering) ──────────────────────────────────────
Write-Step "[4/5] Chromium (headless PDF rendering)"
$browser = $null

# 5a. Commands on PATH
foreach ($b in @("chrome", "chromium", "msedge", "microsoft-edge")) {
    $cmd = Get-Command $b -ErrorAction SilentlyContinue
    if ($cmd) { $browser = $cmd.Source; break }
}

# 5b. Standard Windows install paths
if (-Not $browser) {
    foreach ($p in @(
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "$env:PROGRAMFILES\Microsoft\Edge\Application\msedge.exe")) {
        if (Test-Path $p) { $browser = $p; break }
    }
}

# 5c. Playwright-managed Chromium
if (-Not $browser) {
    $pwBase = "$env:LOCALAPPDATA\ms-playwright"
    if (Test-Path $pwBase) {
        $found = Get-ChildItem -Path $pwBase -Recurse -Filter "chrome.exe" -ErrorAction SilentlyContinue |
                 Select-Object -First 1
        if ($found) { $browser = $found.FullName }
    }
}

if ($browser) {
    Write-OK "Found browser: $browser"
} else {
    Write-Info "No browser found — installing Chromium via Playwright (~150 MB)..."
    .venv\Scripts\pip install --quiet playwright
    .venv\Scripts\playwright install chromium

    # Re-probe
    $pwBase = "$env:LOCALAPPDATA\ms-playwright"
    if (Test-Path $pwBase) {
        $found = Get-ChildItem -Path $pwBase -Recurse -Filter "chrome.exe" -ErrorAction SilentlyContinue |
                 Select-Object -First 1
        if ($found) { $browser = $found.FullName }
    }

    if ($browser) {
        Write-OK "Chromium installed: $browser"
    } else {
        Write-Warn "Could not auto-install Chromium."
        Write-Warn "Install Chrome manually, then set CHROMIUM_BIN=C:\path\to\chrome.exe in .env"
    }
}

# Write CHROMIUM_BIN to .env when browser is at an absolute path not already on PATH
if ($browser -and $browser -match "^[A-Za-z]:\\") {
    $browserName = [System.IO.Path]::GetFileNameWithoutExtension($browser)
    $onPath = Get-Command $browserName -ErrorAction SilentlyContinue
    if (-Not $onPath -or $onPath.Source -ne $browser) {
        $envFile = ".env"
        if (Test-Path $envFile) {
            $lines = Get-Content $envFile | Where-Object { $_ -notmatch "^CHROMIUM_BIN=" }
            Set-Content $envFile $lines
        }
        Add-Content $envFile "CHROMIUM_BIN=$browser"
        Write-Info "CHROMIUM_BIN written to .env"
    }
}

# ── 6. Branded .dotx reference template ──────────────────────────────────────
Write-Step "[5/5] Generating branded reference template -> output\theme\reference.dotx"
New-Item -ItemType Directory -Force -Path "output\theme" | Out-Null
if (-Not (Test-Path "output\theme\reference.dotx")) {
    cmd /c "pandoc --print-default-data-file reference.docx > `"output\theme\reference.dotx`""
}
.venv\Scripts\python scripts\build_reference_dotx.py
Write-OK "Branded template ready"

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Quick-start:"
Write-Host "  Run a memo         : /theory-y-memo TICKER"
Write-Host "  Re-brand template  : .venv\Scripts\python scripts\build_reference_dotx.py"
Write-Host ""
Write-Host "Note: open a new terminal so PATH changes from the installers take effect."
