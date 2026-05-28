#!/usr/bin/env bash
# Setup script for middlemarket-research-agent (macOS / Linux)
# Run once on each machine:  bash setup.sh

set -euo pipefail

# Always operate from the repo root (the directory this script lives in).
cd "$(dirname "$0")"

echo "=== middlemarket-research-agent setup ==="

# ── helper: install a system package with whatever manager is present ────────
install_pkg() {
  local pkg="$1"
  if [[ "$OSTYPE" == "darwin"* ]]; then
    if command -v brew &>/dev/null; then brew install "$pkg"; return; fi
    echo "  ERROR: Homebrew not found. Install it first: https://brew.sh"; return 1
  elif command -v pacman  &>/dev/null; then sudo pacman -S --noconfirm "$pkg"
  elif command -v apt-get &>/dev/null; then sudo apt-get install -y "$pkg"
  elif command -v dnf     &>/dev/null; then sudo dnf install -y "$pkg"
  elif command -v zypper  &>/dev/null; then sudo zypper install -y "$pkg"
  else
    echo "  ERROR: Could not detect a package manager."; return 1
  fi
}

# ── 1. Node dependencies ──────────────────────────────────────────────────────
echo ""
echo "[1/5] Installing Node.js dependencies..."
npm install

# ── 2. Python virtual environment ────────────────────────────────────────────
echo ""
echo "[2/5] Setting up Python virtual environment..."
# Recreate if pip's shebang interpreter no longer exists on disk
# (happens when the project is moved — shebangs bake in the old absolute path)
if [ -d ".venv" ] && [ -f ".venv/bin/pip" ]; then
  PIP_PYTHON=$(head -1 .venv/bin/pip | sed 's/^#!//')
  if [ ! -f "$PIP_PYTHON" ]; then
    echo "  Stale .venv (shebang '$PIP_PYTHON' missing). Recreating..."
    rm -rf .venv
  fi
fi
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
# Install the full, declared dependency set (not a hardcoded subset).
.venv/bin/pip install --quiet -r requirements.txt

# ── 3. System dependency: pandoc ─────────────────────────────────────────────
echo ""
echo "[3/5] Checking for pandoc..."
if command -v pandoc &>/dev/null; then
  echo "  pandoc $(pandoc --version | head -1 | awk '{print $2}') already installed."
else
  echo "  pandoc not found. Installing..."
  install_pkg pandoc || {
    echo "  Install pandoc manually: https://pandoc.org/installing.html"; exit 1; }
fi

# ── 4. System dependency: headless browser (for PDF rendering) ───────────────
echo ""
echo "[4/5] Checking for a Chromium-family browser (PDF rendering)..."
BROWSER=""
for b in chromium chromium-browser google-chrome google-chrome-stable \
         microsoft-edge microsoft-edge-stable; do
  if command -v "$b" &>/dev/null; then BROWSER="$b"; break; fi
done
# macOS app bundles aren't on PATH — check the standard locations too.
if [ -z "$BROWSER" ]; then
  for p in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
           "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
    [ -x "$p" ] && BROWSER="$p" && break
  done
fi
if [ -n "$BROWSER" ]; then
  echo "  Found browser: $BROWSER"
else
  echo "  No browser found. Installing chromium..."
  if [[ "$OSTYPE" == "darwin"* ]]; then
    if command -v brew &>/dev/null; then
      brew install --cask chromium || true
    else
      echo "  Homebrew not found — install Chrome/Chromium manually."
    fi
  else
    # Debian/Ubuntu call it chromium-browser; most others use chromium.
    install_pkg chromium || install_pkg chromium-browser || true
  fi
  if command -v chromium &>/dev/null || command -v chromium-browser &>/dev/null \
     || [ -x "/Applications/Chromium.app/Contents/MacOS/Chromium" ]; then
    echo "  chromium installed."
  else
    echo "  WARNING: could not auto-install a browser."
    echo "  Install Chrome/Chromium/Edge manually, or set CHROMIUM_BIN=/path/to/browser."
  fi
fi

# ── 5. Generate the branded .dotx reference template ─────────────────────────
echo ""
echo "[5/5] Generating branded reference template → output/theme/reference.dotx"
mkdir -p output/theme
# Step (a): produce a base reference.dotx from pandoc's default if missing.
if [ ! -f "output/theme/reference.dotx" ]; then
  pandoc --print-default-data-file reference.docx > output/theme/reference.dotx
fi
# Step (b): apply the Theory Y institutional styling in-place (needs lxml from venv).
.venv/bin/python3 scripts/build_reference_dotx.py
echo "  Branded template ready."

echo ""
echo "=== Setup complete ==="
echo ""
echo "Quick-start:"
echo "  Run a memo:  /theory-y-memo TICKER"
echo "  Re-brand template:  .venv/bin/python3 scripts/build_reference_dotx.py"
