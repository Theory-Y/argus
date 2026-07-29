# Packaging & distribution

The boundary that makes distribution safe: the **client** speaks only HTTP and
contains no proprietary logic, while the **core** engine + prompt live behind
the server.

## What's proprietary vs distributable

| Path | Contains | Source sale |
|------|----------|:----------:|
| `src/` | Data engine (yfinance, FRED, SEC, sentiment) | ✅ ship |
| `core/` | Engine façade, **memo prompt**, Anthropic writer, render | ✅ ship |
| `scripts/`, `output/theme/` | PDF/DOCX rendering + branded template | ✅ ship |
| `.claude/skills/theory-y-memo/SKILL.md` | Human-readable copy of the prompt | ✅ ship |
| `server/` | API wrapper, auth, jobs | ✅ ship |

The client (CLI/SDK + web dashboard, zero IP) is maintained and shipped from its own repository.

> The memo prompt lives in two places — `core/memo/prompt.py` (used by the server)
> and `.claude/skills/theory-y-memo/SKILL.md` (used by Claude Code). Keep them in
> sync. A later step can make the code the single source of truth.

## Source sale (high premium)

The buyer gets and self-hosts everything.

```bash
# Build a source tarball (everything except local junk / secrets):
git archive --format=tar.gz -o theoryy-source.tar.gz HEAD
```

Buyer runs it with `AUTH_MODE=license`:
- Open self-host: leave `LICENSE_SECRET` empty.
- Or gate it: set `LICENSE_SECRET`, mint a token, hand it to the buyer:
  ```python
  from server.auth.license import mint_license_token
  print(mint_license_token("acme-corp", days=3650, secret="<LICENSE_SECRET>"))
  ```
The buyer supplies their own `ANTHROPIC_API_KEY`, `FRED_API_KEY`, `SEC_USER_AGENT`.
