 ## 🔄 In Progress
    - [ ] Install live stack (`scrapegraphai markdownify python-toon`) and run end-to-end
          - **Blocker found:** `ANTHROPIC_API_KEY` is a placeholder in `.env` (MASSIVE_API_KEY,
            SEC_USER_AGENT, FRED_API_KEY are set). Live LLM extraction needs a real Claude key.

    ## ⏳ Pending / Open
    - [ ] Populate `WEB_RESEARCH_SEEDS` (per-ticker forum URLs) — ships empty, so only
          news-article bodies scrape until seeded
    - [ ] Verify twice-run cache hits ("LLM skipped") once a real key is set
    - [ ] Confirm `build_company_context` MCP path surfaces the node live

    The key state change since the plan was approved: all five implementation tasks are done and tests pass, but the live
    end-to-end run is blocked because ANTHROPIC_API_KEY in .env is still the sk-ant-... placeholder. That's the one thing needing
    your input before the live run can proceed.