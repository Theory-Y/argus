#!/usr/bin/env python3
"""
fetch_context.py — deterministic data fetch for the Theory Y investment memo.

This is the ONLY part of the original pipeline that needs to run as code. It
connects to the local `mcp_server.py` over stdio, calls the `build_company_context`
tool, and writes the raw payload to disk. The memo *writing* is done by Claude
directly (see SKILL.md) — there is no LLM API call in here.

Usage:
    python scripts/fetch_context.py TICKER [options]

Examples:
    # Run with the project venv that has `mcp` + can run mcp_server.py
    .venv/bin/python3 scripts/fetch_context.py PCOR

    # Point at a non-default server file / interpreter / output path
    python scripts/fetch_context.py PCOR \
        --server ./mcp_server.py \
        --server-python ./.venv/bin/python3 \
        --out context_PCOR.json

Exit codes:
    0  success
    1  bad arguments / environment
    2  MCP call failed or returned no usable content
"""
import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    sys.exit(
        "ERROR: the `mcp` package is not importable by this interpreter.\n"
        "Run this script with the project venv that has it installed, e.g.\n"
        "    .venv/bin/python3 scripts/fetch_context.py TICKER"
    )

TOOL_NAME = "build_company_context"


async def _fetch(ticker: str, server: str, server_python: str) -> str:
    server_params = StdioServerParameters(
        command=server_python,
        args=[server],
        env=os.environ.copy(),
    )
    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        print(f"Fetching deterministic data payload for {ticker} via MCP...",
              file=sys.stderr)
        result = await session.call_tool(TOOL_NAME, {"ticker": ticker})

        if not result.content or not hasattr(result.content[0], "text"):
            raise RuntimeError(f"MCP tool returned no text content: {result.content!r}")
        return result.content[0].text


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch company context via the local MCP server.")
    parser.add_argument("ticker", help="Stock ticker, e.g. PCOR")
    parser.add_argument(
        "--server",
        default=os.path.join(os.getcwd(), "src", "mcp_server.py"),
        help="Path to mcp_server.py (default: ./src/mcp_server.py)",
    )
    parser.add_argument(
        "--server-python",
        default=sys.executable,
        help="Interpreter used to launch the MCP server (default: the one running this script)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output JSON path (default: context_<TICKER>.json in CWD)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.server):
        print(f"ERROR: MCP server not found at {args.server}", file=sys.stderr)
        return 1

    out_path = args.out or os.path.join(os.getcwd(), "output", f"context_{args.ticker}.json")

    try:
        payload = asyncio.run(_fetch(args.ticker, args.server, args.server_python))
    except Exception as e:  # noqa: BLE001 — surface any failure clearly to the caller
        print(f"ERROR: failed to fetch context: {e}", file=sys.stderr)
        return 2

    try:
        json.loads(payload)
    except json.JSONDecodeError as e:
        print(f"ERROR: MCP returned invalid JSON: {e}", file=sys.stderr)
        return 2

    with open(out_path, "w") as f:
        f.write(payload)

    print(f"OK: context written to {out_path} ({len(payload)} chars)", file=sys.stderr)
    # Echo the path on stdout so it's easy to capture programmatically.
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())