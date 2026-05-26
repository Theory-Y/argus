import asyncio
import os
import sys
from contextlib import AsyncExitStack
from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

anthropic = AsyncAnthropic()
MODEL_NAME = "claude-sonnet-4-6"

async def run_market_agent(ticker: str):
    print(f"🔌 Initializing connection to MCP Server for target: {ticker}...")

    server_params = StdioServerParameters(
        command="python",
        args=["mcp_server.py"],
        env=os.environ.copy()
    )

    async with AsyncExitStack() as stack:
        stdio_transport = await stack.enter_async_context(stdio_client(server_params))
        read, write = stdio_transport

        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        print("✅ Connected to TheoryY_Finance_Oracle. Fetching available tools...")

        response = await session.list_tools()
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }
            for tool in response.tools
        ]

        system_prompt = "You are a Principal Equity Research Analyst. Use the provided tools to gather data before writing."
        user_message = f"Please fetch the context payload for {ticker} and write a one-line investment thesis based on the valuation multiples."

        messages = [{"role": "user", "content": user_message}]

        print(f"🧠 Asking Claude to analyze {ticker}...")

        msg = await anthropic.messages.create(
            model=MODEL_NAME,
            max_tokens=1000,
            system=system_prompt,
            messages=messages,
            tools=tools
        )

        # Loop until Claude stops requesting tools
        while msg.stop_reason == "tool_use":
            tool_results = []

            for block in msg.content:
                if block.type != "tool_use":
                    continue

                print(f"🛠️ Claude requested tool: {block.name} with args {block.input}")

                result = await session.call_tool(block.name, block.input)

                if result.content and hasattr(result.content[0], "text"):
                    content = result.content[0].text
                else:
                    content = ""

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content
                })

            messages.append({"role": "assistant", "content": msg.content})
            messages.append({"role": "user", "content": tool_results})

            print("✍️ Data retrieved. Claude is continuing analysis...")

            msg = await anthropic.messages.create(
                model=MODEL_NAME,
                max_tokens=1000,
                system=system_prompt,
                messages=messages,
                tools=tools
            )

        print("\n" + "=" * 50 + "\n")
        print(msg.content[0].text)
        print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "PCOR"
    asyncio.run(run_market_agent(ticker))