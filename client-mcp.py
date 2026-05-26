import asyncio
import os
import sys
from contextlib import AsyncExitStack
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MODEL_NAME = "gemini-2.0-flash"


def _mcp_tools_to_gemini(mcp_tools: list) -> list[types.Tool]:
    """Convert MCP tool descriptors to a single Gemini Tool with FunctionDeclarations."""
    declarations = []
    for t in mcp_tools:
        # Strip JSON Schema fields Gemini doesn't accept (e.g. top-level 'title')
        schema = {k: v for k, v in t["input_schema"].items() if k != "title"}
        declarations.append(
            types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=schema,
            )
        )
    return [types.Tool(function_declarations=declarations)]


async def run_market_agent(ticker: str):
    gemini = genai.Client()
    print(f"🔌 Initializing connection to MCP Server for target: {ticker}...")

    _venv_python = os.path.join(os.path.dirname(__file__), ".venv", "bin", "python3.14")
    server_params = StdioServerParameters(
        command=_venv_python,
        args=[os.path.join(os.path.dirname(__file__), "mcp_server.py")],
        env=os.environ.copy()
    )

    async with AsyncExitStack() as stack:
        stdio_transport = await stack.enter_async_context(stdio_client(server_params))
        read, write = stdio_transport

        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        print("✅ Connected to TheoryY_Finance_Oracle. Fetching available tools...")

        tool_response = await session.list_tools()
        mcp_tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in tool_response.tools
        ]

        gemini_tools = _mcp_tools_to_gemini(mcp_tools)

        system_prompt = "You are a Principal Equity Research Analyst. Use the provided tools to gather data before writing."
        user_message = f"Please fetch the context payload for {ticker} and write a one-line investment thesis based on the valuation multiples."

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=gemini_tools,
            max_output_tokens=1000,
        )

        contents = [types.Content(role="user", parts=[types.Part(text=user_message)])]

        print(f"🧠 Asking Gemini to analyze {ticker}...")

        response = await gemini.aio.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=config,
        )

        # Agentic loop: keep executing tools until Gemini returns a plain text response
        while True:
            if not response.candidates:
                break
            function_calls = [
                p.function_call
                for p in response.candidates[0].content.parts
                if p.function_call
            ]
            if not function_calls:
                break

            # Append model turn to history
            contents.append(response.candidates[0].content)

            # Execute each requested tool and collect FunctionResponse parts
            result_parts = []
            for fc in function_calls:
                print(f"🛠️ Gemini requested tool: {fc.name} with args {dict(fc.args)}")

                tool_result = await session.call_tool(fc.name, dict(fc.args))
                tool_output = (
                    tool_result.content[0].text
                    if tool_result.content and hasattr(tool_result.content[0], "text")
                    else ""
                )

                result_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"result": tool_output},
                        )
                    )
                )

            contents.append(types.Content(role="user", parts=result_parts))

            print("✍️ Data retrieved. Gemini is continuing analysis...")

            response = await gemini.aio.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=config,
            )

        print("\n" + "=" * 50 + "\n")
        if response.text is not None:
            print(response.text)
        else:
            print("[No text response — model output may have been blocked by safety filters]")
        print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "PCOR"
    asyncio.run(run_market_agent(ticker))
