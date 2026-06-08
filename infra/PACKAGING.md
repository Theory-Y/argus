# Packaging & distribution

This repo is structured so the **same codebase** serves two business models. The
boundary that makes that possible: the **client** speaks only HTTP and contains no
proprietary logic, while the **core** engine + prompt live behind the server.

## What's proprietary vs distributable

| Path | Contains | Source sale | SaaS |
|------|----------|:----------:|:----:|
| `src/` | Data engine (yfinance, FRED, SEC, sentiment) | ✅ ship | 🔒 server-only |
| `core/` | Engine façade, **memo prompt**, Anthropic writer, render | ✅ ship | 🔒 server-only |
| `scripts/`, `output/theme/` | PDF/DOCX rendering + branded template | ✅ ship | 🔒 server-only |
| `.claude/skills/theory-y-memo/SKILL.md` | Human-readable copy of the prompt | ✅ ship | 🔒 keep private |
| `server/` | API wrapper, auth, billing, jobs | ✅ ship | 🔒 we run it |

The client (CLI/SDK + web dashboard, zero IP) is maintained and shipped from its own repository.

> The memo prompt lives in two places — `core/memo/prompt.py` (used by the server)
> and `.claude/skills/theory-y-memo/SKILL.md` (used by Claude Code). Keep them in
> sync. A later step can make the code the single source of truth.

## Model A — Source sale (high premium)

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

## Model B — SaaS (hosted, lifetime + ops fee)

We host the proprietary side; customers get only the client.

- Deploy the server image (`infra/Dockerfile.server`) with `AUTH_MODE=saas`,
  Postgres (`DATABASE_URL`), S3 (`STORAGE_BACKEND=s3`), Stripe keys, and our
  `ANTHROPIC_API_KEY`. The per-memo token cost is what the operational fee covers.
- Publish the **client** to customers — and only the client. It is built and
  released from its own repository.
- Customers never receive `src/`, `core/`, or `SKILL.md`. The finished memo is
  written server-side via the Anthropic API, so the prompt never leaves our infra.
