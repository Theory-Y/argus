#!/usr/bin/env bash
set -a
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/.env" 2>/dev/null || true
set +a
exec mcp_massive "$@"
