#!/usr/bin/env bash
# Ensure the uv-tool install dir is on PATH — Claude Code may launch this
# server with a minimal PATH that excludes ~/.local/bin.
export PATH="$HOME/.local/bin:$PATH"
set -a
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/.env" 2>/dev/null || true
set +a
exec mcp_massive "$@"
