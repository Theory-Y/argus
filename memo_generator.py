import asyncio
import os
from contextlib import AsyncExitStack
from google import genai
from google.genai import types, errors
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MODEL_NAME = "gemini-2.0-flash"


async def _generate_with_retry(gemini_client, model, contents, config, max_retries=5):
    delay = 15
    for attempt in range(max_retries):
        try:
            return await gemini_client.aio.models.generate_content(
                model=model, contents=contents, config=config
            )
        except (errors.ClientError, errors.ServerError) as e:
            if attempt == max_retries - 1:
                raise
            print(f"⏳ Rate limited, retrying in {delay}s... ({e})")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120)
    raise RuntimeError("unreachable")

async def generate_full_memo(ticker: str):
    gemini = genai.Client()
    # ==========================================
    # PHASE 1: FETCH DETERMINISTIC DATA VIA MCP
    # ==========================================
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

        print(f"📥 Fetching deterministic data payload for {ticker} via MCP...")
        result = await session.call_tool("build_company_context", {"ticker": ticker})
        if not result.content or not hasattr(result.content[0], "text"):
            raise ValueError(f"MCP tool returned no text content: {result.content}")
        context_data = result.content[0].text

    print("✅ Data secured. Booting up the Rolling Writer...\n")

    # ==========================================
    # PHASE 2: THE ROLLING STATE LOOP
    # ==========================================
    output_filename = f"TheoryY_Memo_{ticker}.md"
    with open(output_filename, "w") as f:
        f.write(f"# Investment Memo: {ticker}\n\n")

    sections = [
        {"title": "1. One-Line Thesis & Valuation Snapshot", "words": "400"},
        {"title": "2. Business Overview & Operations", "words": "600"},
        {"title": "3. Alternative Data & Macro Signals", "words": "700"},
        {"title": "4. Key Risks & Structural Barriers", "words": "500"},
        {"title": "5. Investment Recommendation", "words": "300"}
    ]

    report_progress_summary = "No sections written yet."

    system_instruction = f"""
    You are a Principal Equity Research Analyst specializing in B2B PropTech and Industrials.
    Write in a highly institutional, data-dense tone. Rely strictly on hard metrics and operating leverage.
    Avoid generic AI filler like 'Crucial role', 'It is important to note', or 'In conclusion'.
    Output strictly in Markdown format.

    Context Payload (Do not hallucinate data outside of this):
    {context_data}
    """

    gen_config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.2,
        max_output_tokens=2048,
    )
    summary_config = types.GenerateContentConfig(max_output_tokens=200)

    for i, section in enumerate(sections):
        print(f"✍️ Drafting: {section['title']}...")

        user_prompt = f"""
        Executive Summary of previous sections: {report_progress_summary}

        Task: Write the section '{section['title']}'. Target length: ~{section['words']} words.
        Begin your response with the markdown heading: ## {section['title']}
        Go straight into the analytical content based on the provided JSON data.
        """

        response = await _generate_with_retry(gemini, MODEL_NAME, user_prompt, gen_config)

        if not response.text:
            raise ValueError(f"Empty response for section '{section['title']}'")
        section_text = response.text

        with open(output_filename, "a") as f:
            f.write(f"{section_text}\n\n")

        # State Compression: summarize to prevent context blowout
        summary_resp = await _generate_with_retry(
            gemini, MODEL_NAME,
            f"Summarize this text in 2 analytical bullets:\n{section_text}",
            summary_config,
        )
        if not summary_resp.text:
            raise ValueError(f"Empty summary response for section {i+1}")
        report_progress_summary += f"\n- Section {i+1}: " + summary_resp.text

    print(f"\n🎉 Complete! Memo saved to {output_filename}")


if __name__ == "__main__":
    asyncio.run(generate_full_memo("PCOR"))
