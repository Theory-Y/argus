# Linking Argus to the Cloudflare site (Cloudflare owns identity + billing)

This wires the deployed Cloudflare site — `theoryy-homepage`, a Next.js app on
OpenNext with Better Auth (Google), Stripe billing, D1, and R2 — to the Argus memo
engine. **Cloudflare stays the single authority for identity, entitlements, and
billing.** Argus is a private compute backend it calls; it authenticates no end users
and charges no one.

The frontend half (the BFF route handlers) lives in **`theoryy-homepage`**, not here:

```
src/app/api/research/memos/route.ts                 POST submit + GET list
src/app/api/research/memos/[jobId]/route.ts         GET status
src/app/api/research/memos/[jobId]/download/route.ts GET download (302 → R2)
src/server/research.ts                              argusFetch() + MEMO_LIMIT + MEMO_KIND
```

```
Browser ──► theoryy-homepage (Cloudflare Worker / OpenNext)
            │  • Better Auth session (Google)     ← identity  (yours, unchanged)
            │  • Stripe subscription → `subscription` table ← billing (yours)
            │  • /api/research/* route handlers:
            │       - getActiveSubscription + getUsageSince → quota gate
            │       - argusFetch(): Authorization: Bearer <license token> + X-User-Id
            │       - recordUsage(kind="research_memo") on accepted job
            ▼
        Argus backend  (Cloud Run / Fly / VPS — infra/Dockerfile.server)
            │  AUTH_MODE=license, LICENSE_SECRET set  ← trusts only this site
            │  jobs tagged with X-User-Id             ← per-user ownership
            ▼
        Cloudflare R2  (STORAGE_BACKEND=s3 → R2 endpoint)
            └─► presigned URL ─► browser downloads the PDF directly
```

## 1. Deploy the Argus backend (not on Cloudflare — it needs a Python runtime)

Build `infra/Dockerfile.server` and deploy to Cloud Run / Fly.io / a VPS. Set:

```
AUTH_MODE=license
LICENSE_SECRET=<random 64-hex>          # python -c "import secrets;print(secrets.token_hex(32))"
ANTHROPIC_API_KEY=sk-ant-...
FRED_API_KEY=...                        # engine data sources
SEC_USER_AGENT=TheoryY/1.0 ops@yoursite.com

# Persistence: Argus's own Postgres for Job rows (NOT D1 — D1 isn't a wire-protocol DB,
# and it stays the source of truth for users/subscriptions/usage in theoryy-homepage).
DATABASE_URL=postgresql+psycopg://...
QUEUE_BACKEND=rq                        # + REDIS_URL=redis://...   (background memo jobs)

# Storage: point the S3 backend at the existing R2 bucket (theoryy-objects).
STORAGE_BACKEND=s3
S3_BUCKET=theoryy-objects
S3_REGION=auto
S3_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
S3_ACCESS_KEY_ID=<r2-access-key>        # R2 → Manage API Tokens
S3_SECRET_ACCESS_KEY=<r2-secret-key>
```

Give it a public hostname (the site Worker runs with `global_fetch_strictly_public`,
so it can only `fetch()` public URLs) but keep it private with the license token and,
ideally, a Cloudflare Tunnel + Access service token. No public CORS is needed — the
browser only ever talks to the site's own origin.

## 2. Mint the site's license token (once)

The site authenticates to Argus as the single licensed caller:

```python
from server.auth.license import mint_license_token
print(mint_license_token("cloudflare-homepage", days=3650, secret="<LICENSE_SECRET>"))
```

In `theoryy-homepage`: `wrangler secret put ARGUS_LICENSE_TOKEN` (and set
`ARGUS_BASE_URL` as a var). Both are declared in `src/lib/env.ts` and
`.dev.vars.example`.

## 3. Frontend route handlers (already written into theoryy-homepage)

The handlers mirror the existing `src/app/api/agent/run/route.ts` and reuse the
site's own helpers — `getAuth().api.getSession`, `getActiveSubscription`,
`getUsageSince` / `recordUsage` — so there is no second auth/billing system:

- Quota is enforced against the `subscription` + `usage_event` (D1) tables, per the
  `MEMO_LIMIT` map in `src/server/research.ts` (plans: free/base/pro/max/enterprise).
- Usage is metered **at submission** (one `usage_event` of `kind="research_memo"`
  per accepted job), matching `agent/run` — the ledger has no idempotency key, so
  poll-time metering would double-count.
- `X-User-Id` is the Better Auth `session.user.id`; Argus scopes job ownership to it.

## 4. UI

Point the SaaS UI at the site's own origin — `POST /api/research/memos`, poll
`GET /api/research/memos/{id}`, then `GET /api/research/memos/{id}/download?format=pdf`
(a 302 to a short-lived R2 URL). Nothing in the browser ever sees Argus.

## What you deliberately do NOT use

Argus's `saas` mode (`server/auth/saas.py`, `server/billing/`, `server/routes/account.py`,
`server/routes/billing.py`) re-implements Stripe + accounts + JWT — all of which
Cloudflare already owns via Better Auth + Stripe. Leave `AUTH_MODE=license`; those
routers self-disable (404) and no second billing system runs.
