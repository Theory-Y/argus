# TheoryY Service Architecture Plan

## Overview

Convert the research agent from a Claude Code skill into a **managed service** with:
- Private backend (your infrastructure)
- Public client (distributed to customers)
- API layer (hidden implementation)
- Auth/billing system

---

## 1. Service Tiers & Deployment Model

### Option A: SaaS (Recommended for scale)
```
Client → HTTPS → Cloud API Gateway → Private Research Engine
                  (auth, rate limit)
```
- Single hosted backend (AWS/GCP/Azure)
- Users access via REST API + web client
- You handle all infrastructure
- Per-user API keys + metering

### Option B: Hybrid (On-premise option)
```
Client → HTTPS → Customer's API Server → Private Research Engine
                  (customer-deployed)
```
- Customers self-host the backend
- You distribute a Docker container / installer
- License key activates features
- Reduces your infra costs, adds support burden

### Option C: Embedded (Lowest friction)
```
Client → Local Python daemon → Private Research Engine
         (runs on user's machine)
```
- Zero server infrastructure
- Users run service locally
- Easier trial/freemium model
- Still protects your code (compiled Python)

---

## 2. API Design (Private Backend)

### Core REST Endpoints

```
POST /api/v1/memos/generate
  - Request: { ticker, format: "markdown|pdf|docx", priority: "standard|urgent" }
  - Response: { job_id, status, estimated_seconds }
  - Stream: Server-Sent Events for progress

GET /api/v1/memos/{job_id}
  - Response: { status, progress, result_url (signed), errors }

GET /api/v1/memos/{job_id}/download
  - Returns: PDF/DOCX/MD file (signed URL or direct download)

GET /api/v1/sector/comparables
  - Request: { tickers: ["PCOR", "APPF", "Z"], metrics: ["ev_ebitda", "pe_fwd"] }
  - Response: CSV or JSON table

GET /api/v1/tickers
  - Response: { supported: ["PCOR", "APPF", ...], categories: {...} }

POST /api/v1/batch/memos
  - Request: { tickers: [list], format, include_sector_sheet: true }
  - Response: { batch_id, job_ids: [...] }
```

### Authentication
```
Header: Authorization: Bearer <API_KEY>
or
Query: ?key=<API_KEY>

API Key format: theory-y_<timestamp>_<random>
  - Scoped by user/customer
  - Rate-limited (e.g., 100 memos/month for free tier)
  - Revocable in dashboard
```

### Rate Limiting & Quotas
```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1234567890

Free tier: 5 memos/month
Pro tier: 100 memos/month
Enterprise: unlimited
```

---

## 3. Client Applications

### 3a. Web Client (Primary)
```
Frontend: React + TypeScript (Vite or Next.js)
Hosted: Static site (Vercel, Netlify, or your CDN)

Pages:
  /dashboard              - memo history, API key mgmt
  /generate              - ticker search, format picker, generate button
  /results/{job_id}      - memo display (markdown render) + download links
  /account               - billing, subscription, usage
  /api-docs              - OpenAPI/Swagger for API access

Features:
  - Real-time progress (polling or WebSocket)
  - Compare multiple tickers side-by-side
  - Export history as CSV
  - Search/filter memos by date, ticker
  - Dark mode
  - Sector sheet generation UI
```

### 3b. CLI Client (Secondary)
```
Tool: Python Click or Node.js commander

Usage:
  $ theory-y generate PCOR --format pdf --output memo.pdf
  $ theory-y list-tickers
  $ theory-y compare PCOR APPF Z --format csv
  $ theory-y batch PCOR APPF Z --output batch/
  $ theory-y auth --key <API_KEY>
  $ theory-y quota --show

Distributed via:
  - PyPI (pip install theory-y-cli)
  - npm (npm install -g theory-y-cli)
  - GitHub releases (single binary)
```

### 3c. Integrations (Future)
```
- Slack bot: /theory-y PCOR → posts memo preview in channel
- Zapier action: Trigger memo generation from any workflow
- Tableau/Looker connector: Embed metrics in dashboards
- Email digest: Auto-send weekly sector sheets
```

---

## 4. Backend Architecture (Private)

### Code Structure
```
backend/
  api/
    app.py                    # FastAPI server
    routes/
      memos.py               # POST /memos, GET /memos/{id}
      tickers.py             # GET /tickers
      sector.py              # GET /sector/comparables
      batch.py               # POST /batch/memos
    middleware/
      auth.py                # API key validation
      rate_limit.py          # Token bucket throttling
      logging.py             # Audit trail
  
  services/
    memo_generator.py        # Calls existing fetch_context.py + memo writing
    pdf_renderer.py          # md-to-pdf integration
    docx_builder.py          # python-docx + template engine
  
  models/
    user.py                  # User, API key, subscription
    job.py                   # Job tracking (queued, processing, done)
    audit_log.py             # Compliance trail
  
  db/
    schema.sql               # Users, API keys, jobs, usage
    migrations/
  
  cache/
    redis_client.py          # Cache memo results, ticker metadata
  
  queue/
    celery_worker.py         # Background job processing
    tasks.py                 # memo_generation_task()
  
  utils/
    validators.py            # Ticker validation, format checks
    errors.py                # Exception classes
    config.py                # Env vars, feature flags
  
  tests/
    test_api.py
    test_auth.py
    test_rate_limit.py
```

### Job Processing Flow
```
POST /api/v1/memos/generate
  ↓
[Auth middleware validates API key]
  ↓
[Rate limit check]
  ↓
Insert Job record (status: queued)
  ↓
Enqueue to Celery/Bull
  ↓
Return job_id immediately (202 Accepted)
  ↓
[Background worker picks up]
  ↓
Call existing fetch_context.py → get JSON
  ↓
Call memo writer → generate markdown
  ↓
Call PDF renderer (if requested)
  ↓
Store result in S3/Cloud Storage
  ↓
Update Job record (status: complete, result_url: <signed URL>)
  ↓
Client polls GET /api/v1/memos/{job_id}
  ↓
Get signed download URL → fetch from storage
```

---

## 5. Data & Storage Strategy

### What's Stored Where

**Stateless (ephemeral)**
- Fetched context JSON: Temp storage, delete after memo generation
- Generated memos: S3/Cloud Storage, delete after 30 days (free tier) or keep indefinitely (paid)

**Stateful (permanent)**
- Users: PostgreSQL (email, subscription, created_at)
- API keys: PostgreSQL (user_id, key_hash, rate_limit, created_at, revoked_at)
- Jobs: PostgreSQL (user_id, ticker, format, status, created_at, completed_at, result_url)
- Audit log: PostgreSQL (user_id, action, timestamp, details)

### Cache Layer
```
Redis:
  - Memo cache (key: memo_{ticker}_{date}, ttl: 7 days)
  - Rate limit counters (key: rate_limit_{user_id}_{month})
  - Ticker metadata (list_supported_tickers result)
```

### Download Strategy
```
User requests memo
  ↓
API generates signed S3 URL (valid for 24 hours)
  ↓
Client redirects to S3 or streams via API
  ↓
User never sees private backend IP
```

---

## 6. Authentication & Access Control

### User Onboarding Flow
```
1. Sign up at web client → create account
2. Receive welcome email with API key
3. Enter API key in CLI or web dashboard
4. Generate first memo (trial credit)
5. Auto-prompt to upgrade after trial expires
```

### API Key Management
```
User Dashboard:
  - View all API keys (created, last used, never used)
  - Create new key
  - Revoke key
  - Rotate key (old key still works for 24h transition period)
  - Set rate limits per key
  - Set key scope (e.g., "memo generation only")
```

### Billing Integration
```
Stripe integration:
  - Free tier: 5 memos/month
  - Pro tier ($29/mo): 100 memos/month
  - Enterprise: custom
  
On quota exceeded:
  - Free user: "Upgrade to continue" prompt
  - Pro user: Email notice → suggest higher tier
  - Disable old API key if payment fails
```

---

## 7. Security & Compliance

### Source Code Protection
```
✓ Private backend (never exposed to client)
✓ API obfuscation (no internal function names in errors)
✓ CLI client compiled (PyInstaller for Python → .exe/.bin)
✓ Web client minified (no source maps in production)
✓ Signed releases (GPG signature for CLI downloads)
```

### Data Security
```
✓ All traffic: HTTPS only
✓ API keys: Hashed in DB (bcrypt)
✓ Passwords: Hashed (argon2)
✓ Memos: Encrypted at rest in S3
✓ Audit log: Immutable, tamper-evident
✓ Data retention policy: Memos deleted after user-configurable period
```

### Compliance
```
GDPR:
  - User data export (download all memos, API keys)
  - Right to delete (purge account + related data)
  - Data processing agreement for enterprise customers

SOC 2 Type II:
  - Encryption in transit + at rest
  - Access logs
  - Incident response plan
  - Background checks for team
```

---

## 8. Deployment & DevOps

### Backend Deployment
```
Option A: Containerized (Recommended)
  - Docker image: theoryy/api:v1.0
  - Push to private ECR/Docker Hub
  - Deploy to: ECS, EKS, or Cloud Run
  - Scale: Auto-scaling on CPU/memory
  - CI/CD: GitHub Actions → ECR → ECS/EKS

Option B: Serverless
  - AWS Lambda + API Gateway
  - Redis on ElastiCache
  - S3 for memo storage
  - Lower ops burden, higher per-request cost
```

### Client Deployment
```
Web client:
  - Build: npm run build → dist/
  - Deploy to Vercel/Netlify
  - CDN: CloudFront
  - Domains: https://app.theoryy.ai

CLI client:
  - Publish to PyPI, npm, GitHub releases
  - Auto-update mechanism (check version on startup)
  - Sign binaries (GPG)
```

---

## 9. Monitoring & Observability

### Dashboards
```
Internal (you only):
  - API response times (p50, p95, p99)
  - Error rates by endpoint
  - Queue depth (pending jobs)
  - Memo generation success rate
  - User growth, active users
  - Revenue (trial→paid conversion)

Customer-facing:
  - Status page (is API up?)
  - Usage dashboard (X/100 memos used)
  - Job history (all past memos)
  - API performance SLA (99.9% uptime)
```

### Logging & Tracing
```
Logs (ELK Stack or CloudWatch):
  - All API requests (timestamp, user, endpoint, response code, latency)
  - Job lifecycle (queued, processing, complete, failed)
  - Errors with full stack trace

Tracing (Datadog or Jaeger):
  - Track single request through: auth → enqueue → process → store
  - Identify bottlenecks
```

---

## 10. Monetization Models

### Option A: Usage-Based
```
Free:    5 memos/month
Pro:     $29/mo  → 100 memos/month
Team:    $99/mo  → 500 memos/month + API access
Enterprise: Custom (unlimited memos, SLA, support)

Overage: $0.50 per memo beyond quota
```

### Option B: Subscription-Only (No usage tracking)
```
Free:    5 memos/month, limited to 14 tickers
Starter: $9/mo  → all 14 tickers, unlimited memos
Pro:     $29/mo → Starter + batch generation, sector sheets, API
```

### Option C: One-Time Purchase
```
Lifetime: $299 (one-time)
  → 1000 memos total
  → no subscription required
  → updates for 2 years
```

---

## 11. File Structure Summary

```
theoryy-service/
├── backend/
│   ├── src/
│   │   ├── api/
│   │   ├── services/
│   │   ├── models/
│   │   ├── db/
│   │   ├── queue/
│   │   ├── utils/
│   │   └── main.py
│   ├── tests/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
│
├── cli/
│   ├── src/
│   │   ├── __init__.py
│   │   ├── client.py (API wrapper)
│   │   ├── commands.py (CLI groups)
│   │   └── utils.py
│   ├── tests/
│   ├── setup.py
│   └── README.md
│
├── web/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── utils/
│   │   └── App.tsx
│   ├── public/
│   ├── package.json
│   ├── vite.config.ts
│   └── README.md
│
├── docs/
│   ├── API.md (OpenAPI spec)
│   ├── SETUP.md (deployment guide)
│   ├── USER_GUIDE.md (how to use service)
│   └── SECURITY.md (compliance docs)
│
└── infra/
    ├── docker-compose.yml (local dev)
    ├── terraform/
    │   ├── aws.tf (RDS, S3, ECR, ECS)
    │   └── variables.tf
    └── k8s/ (Kubernetes manifests)
```

---

## 12. Implementation Roadmap

### Phase 1: MVP (8-10 weeks)
- [ ] FastAPI backend with `/memos/generate`, `/memos/{id}` endpoints
- [ ] PostgreSQL + Redis setup
- [ ] Basic auth (API key validation)
- [ ] Job queue (Celery + RabbitMQ or Bull)
- [ ] React web client (generate page + results)
- [ ] S3 file storage + signed URLs
- [ ] Basic monitoring (logs + metrics)

### Phase 2: Polish & Scale (4-6 weeks)
- [ ] CLI client (Python Click)
- [ ] Rate limiting & quota enforcement
- [ ] Stripe billing integration
- [ ] User dashboard (history, API key mgmt, usage)
- [ ] Improved error handling & user feedback
- [ ] Email notifications (memo ready, quota warnings)

### Phase 3: Enterprise (6-8 weeks)
- [ ] Batch job support (generate 20 memos at once)
- [ ] Sector sheet generation UI
- [ ] Admin dashboard (user mgmt, refunds, support)
- [ ] GDPR export/delete endpoints
- [ ] SOC 2 audit prep
- [ ] SLA monitoring & status page

### Phase 4: Ecosystem (Ongoing)
- [ ] Slack bot integration
- [ ] Zapier integration
- [ ] Webhook support (notify on job complete)
- [ ] Custom branding (for resellers)
- [ ] API + CLI docs site

---

## 13. Cost Estimate (AWS Example)

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| ECS (2 CPU, 4GB RAM) | $50 | Auto-scaling |
| RDS PostgreSQL | $30 | db.t3.micro |
| ElastiCache Redis | $20 | cache.t3.micro |
| S3 storage | $10 | 100GB memos |
| Data transfer out | $20 | 1TB egress/mo |
| API Gateway | $10 | 1M requests/mo |
| CloudFront CDN | $5 | Static assets |
| **Total** | **~$145/mo** | **Fixed + variable** |

*Break-even: ~100 active users on $29/mo plan*

---

## Key Decisions to Make

1. **SaaS vs Hybrid vs Embedded?** (Affects deployment complexity & support)
2. **Which monetization model?** (Usage-based, subscription, or freemium)
3. **Self-host or use AWS/GCP/Azure?** (Cost vs convenience)
4. **CLI + Web, or just web initially?** (Scope & timeline)
5. **How long to keep free memos?** (Storage costs & user experience)

---

