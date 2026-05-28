"""
server — the TheoryY API.

Wraps the proprietary ``core`` engine behind a stable HTTP contract. The same
codebase runs in two modes, selected by the ``AUTH_MODE`` env var:

  • license  — offline license-key check, no billing. For source-sale / self-host.
  • saas     — DB-backed API keys + Stripe quota. For our hosted offering.

The distributable client (../client) talks only to this contract and never
imports ``core`` or ``src`` — so it is safe to ship in either business model.
"""
