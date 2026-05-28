#!/usr/bin/env bash
# Setup script for middlemarket-research-agent
# Run once on each machine: bash setup.sh

set -euo pipefail

echo "=== middlemarket-research-agent setup ==="

# ── 1. Node dependencies ──────────────────────────────────────────────────────
echo ""
echo "[1/3] Installing Node.js dependencies..."
npm install

# ── 2. Python virtual environment ────────────────────────────────────────────
echo ""
echo "[2/3] Setting up Python virtual environment..."
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
.venv/bin/pip install --quiet mcp yfinance requests

# ── 3. System dependency: pandoc ─────────────────────────────────────────────
echo ""
echo "[3/3] Checking for pandoc..."
if command -v pandoc &>/dev/null; then
  echo "  pandoc $(pandoc --version | head -1 | awk '{print $2}') already installed."
else
  echo "  pandoc not found. Installing..."
  if [[ "$OSTYPE" == "darwin"* ]]; then
    if command -v brew &>/dev/null; then
      brew install pandoc
    else
      echo "  ERROR: Homebrew not found. Install it first: https://brew.sh"
      exit 1
    fi
  elif command -v pacman &>/dev/null; then
    sudo pacman -S --noconfirm pandoc
  elif command -v apt-get &>/dev/null; then
    sudo apt-get install -y pandoc
  elif command -v dnf &>/dev/null; then
    sudo dnf install -y pandoc
  elif command -v zypper &>/dev/null; then
    sudo zypper install -y pandoc
  else
    echo "  ERROR: Could not detect package manager."
    echo "  Install pandoc manually: https://pandoc.org/installing.html"
    exit 1
  fi
fi

# ── 4. Generate default .dotx reference template ────────────────────────────
TEMPLATE_PATH="output/theme/reference.dotx"
if [ ! -f "$TEMPLATE_PATH" ]; then
  echo ""
  echo "[4/4] Generating default pandoc reference template → $TEMPLATE_PATH"
  mkdir -p output/theme
  pandoc --print-default-data-file reference.docx > "$TEMPLATE_PATH"
  echo "  Done. Open $TEMPLATE_PATH in Word to customize styles, then save."
else
  echo ""
  echo "[4/4] Reference template already exists: $TEMPLATE_PATH"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Quick-start:"
echo "  Customize styles: open output/theme/reference.dotx in Microsoft Word"
echo "  Run a memo:       /theory-y-memo TICKER"
