import asyncio
import os
import sys
from contextlib import AsyncExitStack

import anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MODEL_NAME = "claude-sonnet-4-6"
_MAX_TOKENS = 4096


def _mcp_tools_to_claude(mcp_tools: list) -> list[dict]:
    """Convert MCP tool descriptors to Claude tool format."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["input_schema"],
        }
        for t in mcp_tools
    ]


async def run_market_agent(ticker: str):
    client = anthropic.AsyncAnthropic()
    print(f"Initializing connection to MCP Server for target: {ticker}...")

    _src_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_src_dir)
    _venv_python = sys.executable
    server_params = StdioServerParameters(
        command=_venv_python,
        args=[os.path.join(_src_dir, "mcp_server.py")],
        env=os.environ.copy(),
    )

    async with AsyncExitStack() as stack:
        stdio_transport = await stack.enter_async_context(stdio_client(server_params))
        read, write = stdio_transport

        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        print("Connected to TheoryY_Finance_Oracle. Fetching available tools...")

        tool_response = await session.list_tools()
        mcp_tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in tool_response.tools
        ]

        claude_tools = _mcp_tools_to_claude(mcp_tools)

        system_prompt = "You are a Principal Equity Research Analyst. Use the provided tools to gather data before writing."
        user_message = f"Please fetch the context payload for {ticker} and write a one-line investment thesis based on the valuation multiples."

        messages = [{"role": "user", "content": user_message}]

        print(f"Asking Claude to analyze {ticker}...")

        response = await client.messages.create(
            model=MODEL_NAME,
            max_tokens=_MAX_TOKENS,
            system=system_prompt,
            tools=claude_tools,
            messages=messages,
        )

        # Agentic loop: keep executing tools until Claude returns end_turn
        while response.stop_reason == "tool_use":
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            # Append assistant turn
            messages.append({"role": "assistant", "content": response.content})

            # Execute each tool and collect results
            tool_results = []
            for tu in tool_use_blocks:
                print(f"Claude requested tool: {tu.name} with args {tu.input}")

                tool_result = await session.call_tool(tu.name, tu.input)
                tool_output = (
                    tool_result.content[0].text
                    if tool_result.content and hasattr(tool_result.content[0], "text")
                    else ""
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": tool_output,
                })

            messages.append({"role": "user", "content": tool_results})

            print("Data retrieved. Claude is continuing analysis...")

            response = await client.messages.create(
                model=MODEL_NAME,
                max_tokens=_MAX_TOKENS,
                system=system_prompt,
                tools=claude_tools,
                messages=messages,
            )

        if response.stop_reason == "max_tokens":
            print("[WARNING] Response was truncated — increase _MAX_TOKENS if needed.")

        print("\n" + "=" * 50 + "\n")
        text_blocks = [b for b in response.content if b.type == "text"]
        if text_blocks:
            print(text_blocks[-1].text)
        else:
            print("[No text response returned]")
        print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "PCOR"
    asyncio.run(run_market_agent(ticker))
