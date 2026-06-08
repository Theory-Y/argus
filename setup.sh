#!/usr/bin/env bash
# Setup script for middlemarket-research-agent (macOS / Linux)
# Zero prerequisites — only curl (or wget) and bash are required.
# Run:  bash setup.sh

set -euo pipefail
cd "$(dirname "$0")"

# ── colour helpers ────────────────────────────────────────────────────────────
BOLD='\033[1m'; CYAN='\033[36m'; GREEN='\033[32m'; YELLOW='\033[33m'
RED='\033[31m'; RESET='\033[0m'
say()  { printf "\n${CYAN}${BOLD}%s${RESET}\n" "$*"; }
ok()   { printf "  ${GREEN}✓${RESET}  %s\n" "$*"; }
info() { printf "  %s\n" "$*"; }
warn() { printf "  ${YELLOW}WARNING:${RESET} %s\n" "$*"; }
die()  { printf "  ${RED}ERROR:${RESET} %s\n" "$*"; exit 1; }

echo ""
say "=== middlemarket-research-agent setup ==="

OS=$(uname -s | tr '[:upper:]' '[:lower:]')   # linux | darwin
ARCH=$(uname -m)                               # x86_64 | aarch64 | arm64

# ── core helpers ──────────────────────────────────────────────────────────────
has() { command -v "$1" &>/dev/null; }

# fetch <url> <dest-file>
fetch() {
  if has curl;   then curl -fsSL "$1" -o "$2"
  elif has wget; then wget -q    "$1" -O "$2"
  else die "curl or wget is required — install one and re-run setup.sh"; fi
}

# fetch_out <url>  →  stdout
fetch_out() {
  if has curl;   then curl -fsSL "$1"
  elif has wget; then wget -qO-  "$1"
  else die "curl or wget is required — install one and re-run setup.sh"; fi
}

# Ensure ~/.local/bin is on PATH for this session (used for fnm, uv, pandoc)
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"
[[ ":$PATH:" != *":$LOCAL_BIN:"* ]] && export PATH="$LOCAL_BIN:$PATH"

# ── 0. Environment file (.env) ────────────────────────────────────────────────
say "Environment file (.env)"
if [ -f .env ]; then
  ok ".env already present — leaving it untouched"
elif [ -f .env.example ]; then
  cp .env.example .env
  ok "Created .env from .env.example — add your API keys before running a memo"
else
  warn "No .env or .env.example found — create .env manually before running"
fi

# ── 1. Node.js ────────────────────────────────────────────────────────────────
say "[1/6] Node.js"
if has node && has npm; then
  ok "node $(node --version)  npm $(npm --version)"
else
  info "node/npm not found — installing via fnm (Fast Node Manager)..."

  # Install fnm binary to LOCAL_BIN if not already there
  if ! has fnm && [ ! -x "$LOCAL_BIN/fnm" ]; then
    fetch_out "https://fnm.vercel.app/install" \
      | bash -s -- --install-dir "$LOCAL_BIN" --skip-shell
  fi

  FNM=$(command -v fnm 2>/dev/null || echo "$LOCAL_BIN/fnm")
  eval "$("$FNM" env --shell bash)"   # add fnm-managed node to PATH
  "$FNM" install --lts
  eval "$("$FNM" env --shell bash)"   # re-eval so node/npm resolve

  if has node; then
    ok "node $(node --version) installed via fnm"
  else
    die "Node.js install failed. Install from https://nodejs.org/ and re-run."
  fi
fi

info "Running npm install..."
npm install
ok "Node.js dependencies installed"

# ── 2. Python ─────────────────────────────────────────────────────────────────
say "[2/6] Python"

# Ensure uv is available — it bootstraps Python if needed and replaces pip
UV=$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")
if ! has uv && [ ! -x "$UV" ]; then
  info "Installing uv (Python manager + fast package installer)..."
  fetch_out "https://astral.sh/uv/install.sh" | sh
  [[ ":$PATH:" != *":$HOME/.local/bin:"* ]] && export PATH="$HOME/.local/bin:$PATH"
  UV=$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")
fi

# Check for Python 3.10+; if absent, let uv install it
PYTHON_OK=false
if has python3 && python3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" 2>/dev/null; then
  PYTHON_OK=true
fi

if [ "$PYTHON_OK" = false ]; then
  info "Python 3.10+ not found — installing Python 3.12 via uv..."
  "$UV" python install 3.12
  ok "Python 3.12 installed"
else
  ok "$(python3 --version)"
fi

# Create or refresh the virtual environment.
# Detect a stale venv (its baked interpreter was moved or removed) and recreate.
if [ -d ".venv" ] && ! .venv/bin/python3 -c "" 2>/dev/null; then
  info "Stale .venv detected (interpreter no longer runnable). Recreating..."
  rm -rf .venv
fi

if [ -x "$UV" ] || has uv; then
  # uv auto-selects a managed Python if the system has none.
  # uv refuses to overwrite an existing venv, so only create when absent.
  if [ ! -d ".venv" ]; then
    "$UV" venv .venv --python 3.12 2>/dev/null || "$UV" venv .venv
  fi
  # Target the venv explicitly — uv venvs do not ship their own pip.
  "$UV" pip install --python .venv/bin/python --quiet -r requirements.txt
else
  # Fallback: standard venv + pip
  [ ! -d ".venv" ] && python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi
ok "Python virtual environment ready (.venv)"

# ── 3. pandoc ─────────────────────────────────────────────────────────────────
say "[3/6] pandoc"
if has pandoc; then
  ok "pandoc $(pandoc --version | head -1 | awk '{print $2}')"
else
  info "pandoc not found — downloading standalone binary (no sudo needed)..."
  PANDOC_VER="3.6.4"

  case "$OS-$ARCH" in
    darwin-arm64)          PANDOC_PKG="pandoc-${PANDOC_VER}-arm64-macOS.zip"    ;;
    darwin-x86_64)         PANDOC_PKG="pandoc-${PANDOC_VER}-x86_64-macOS.zip"   ;;
    linux-aarch64|linux-arm64)
                           PANDOC_PKG="pandoc-${PANDOC_VER}-linux-arm64.tar.gz" ;;
    linux-*)               PANDOC_PKG="pandoc-${PANDOC_VER}-linux-amd64.tar.gz" ;;
    *) die "Unsupported OS/arch: $OS/$ARCH — install pandoc manually: https://pandoc.org/installing.html" ;;
  esac

  PANDOC_URL="https://github.com/jgm/pandoc/releases/download/${PANDOC_VER}/${PANDOC_PKG}"
  TMP_DIR=$(mktemp -d)
  # shellcheck disable=SC2064
  trap "rm -rf $TMP_DIR" EXIT

  info "Downloading $PANDOC_PKG..."
  fetch "$PANDOC_URL" "$TMP_DIR/pandoc_pkg"

  if [[ "$PANDOC_PKG" == *.zip ]]; then
    unzip -q "$TMP_DIR/pandoc_pkg" -d "$TMP_DIR/src"
    cp "$TMP_DIR/src/pandoc-${PANDOC_VER}/bin/pandoc" "$LOCAL_BIN/pandoc"
  else
    tar -xzf "$TMP_DIR/pandoc_pkg" -C "$TMP_DIR"
    cp "$TMP_DIR/pandoc-${PANDOC_VER}/bin/pandoc" "$LOCAL_BIN/pandoc"
  fi
  chmod +x "$LOCAL_BIN/pandoc"

  ok "pandoc $(pandoc --version | head -1 | awk '{print $2}') installed → $LOCAL_BIN/pandoc"
fi

# ── 4. Chromium (headless PDF rendering) ──────────────────────────────────────
say "[4/6] Chromium (headless PDF rendering)"
BROWSER=""

# 4a. System browsers
for b in chromium chromium-browser google-chrome google-chrome-stable chrome \
         microsoft-edge microsoft-edge-stable msedge; do
  has "$b" && BROWSER="$b" && break
done

# 4b. macOS application bundles
if [ -z "$BROWSER" ]; then
  for p in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"; do
    [ -x "$p" ] && BROWSER="$p" && break
  done
fi

# 4c. Playwright-managed Chromium (from a previous setup run)
if [ -z "$BROWSER" ]; then
  for cache_dir in "$HOME/.cache/ms-playwright" "$HOME/Library/Caches/ms-playwright"; do
    for p in \
      "$cache_dir/chromium-"*/chrome-linux/chrome \
      "$cache_dir/chromium-"*/chrome-mac/Chromium.app/Contents/MacOS/Chromium; do
      [ -x "$p" ] && BROWSER="$p" && break 2
    done
  done
fi

if [ -n "$BROWSER" ]; then
  ok "Found browser: $BROWSER"
else
  info "No browser found — installing Chromium via Playwright (≈150 MB)..."
  # Install playwright into the venv (dev-only use; not added to requirements.txt).
  # Use uv when available — uv-created venvs do not ship their own pip.
  if [ -x "$UV" ] || has uv; then
    "$UV" pip install --python .venv/bin/python --quiet playwright
  else
    .venv/bin/pip install --quiet playwright
  fi

  # Try with system dependencies first (needs sudo on Linux, safe on macOS)
  if .venv/bin/playwright install chromium --with-deps 2>/dev/null; then
    :
  else
    .venv/bin/playwright install chromium
  fi

  # Re-probe after install
  for cache_dir in "$HOME/.cache/ms-playwright" "$HOME/Library/Caches/ms-playwright"; do
    for p in \
      "$cache_dir/chromium-"*/chrome-linux/chrome \
      "$cache_dir/chromium-"*/chrome-mac/Chromium.app/Contents/MacOS/Chromium; do
      [ -x "$p" ] && BROWSER="$p" && break 2
    done
  done

  if [ -n "$BROWSER" ]; then
    ok "Chromium installed: $BROWSER"
  else
    warn "Could not auto-install Chromium."
    warn "Install Chrome/Chromium manually, then set CHROMIUM_BIN=/path/to/browser in .env"
  fi
fi

# Write CHROMIUM_BIN to .env when the binary is not on PATH (absolute path required)
if [ -n "$BROWSER" ] && [[ "$BROWSER" == /* ]]; then
  BROWSER_CMD=$(basename "$BROWSER")
  if ! has "$BROWSER_CMD" || [ "$(command -v "$BROWSER_CMD")" != "$BROWSER" ]; then
    touch .env
    # Remove any existing CHROMIUM_BIN line, then append the new one
    { grep -v "^CHROMIUM_BIN=" .env || true; } > .env.tmp && mv .env.tmp .env
    echo "CHROMIUM_BIN=$BROWSER" >> .env
    info "CHROMIUM_BIN written to .env"
  fi
fi

# ── 5. MCP servers (.mcp.json + massive tool) ─────────────────────────────────
say "[5/6] MCP servers"

# 5a. massive MCP server — installed as an isolated uv tool (not in the venv).
#     Pinned to the same git tag the project was built against.
MASSIVE_SPEC="git+https://github.com/massive-com/mcp_massive@v0.10.0"
if has mcp_massive; then
  ok "mcp_massive already installed ($(mcp_massive --version 2>/dev/null || echo present))"
elif [ -x "$UV" ] || has uv; then
  info "Installing massive MCP server via uv tool..."
  if "$UV" tool install "$MASSIVE_SPEC" >/dev/null 2>&1; then
    ok "mcp_massive installed"
  else
    warn "Could not install mcp_massive — the 'massive' MCP server will be unavailable."
    warn "Install manually later:  uv tool install \"$MASSIVE_SPEC\""
  fi
else
  warn "uv not available — skipping mcp_massive install (the 'massive' server will be unavailable)."
fi

# 5b. Render .mcp.json from the committed template with this machine's paths.
#     Regenerated every run so the paths always match the current checkout.
if [ -f .mcp.json.template ]; then
  PROJECT_DIR="$(pwd)"
  sed "s#__PROJECT_DIR__#${PROJECT_DIR}#g" .mcp.json.template > .mcp.json
  ok ".mcp.json generated for $PROJECT_DIR"
else
  warn "No .mcp.json.template found — cannot generate .mcp.json"
fi

# ── 6. Branded .dotx reference template ──────────────────────────────────────
say "[6/6] Generating branded reference template → output/theme/reference.dotx"
mkdir -p output/theme
if [ ! -f "output/theme/reference.dotx" ]; then
  pandoc --print-default-data-file reference.docx > output/theme/reference.dotx
fi
.venv/bin/python3 scripts/build_reference_dotx.py
ok "Branded template ready"

echo ""
say "=== Setup complete ==="
echo ""
echo "Quick-start:"
echo "  Run a memo:         /theory-y-memo TICKER"
echo "  Re-brand template:  .venv/bin/python3 scripts/build_reference_dotx.py"
echo ""
echo "Note: if this session installed Node.js or uv, open a new terminal so"
echo "      PATH changes from ~/.bashrc / ~/.zshrc take effect permanently."
