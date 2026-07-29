"""
server — the TheoryY API.

Wraps the proprietary ``core`` engine behind a stable HTTP contract. Auth is
license mode: an offline license-key check for source-sale / self-host.

The distributable client (../client) talks only to this contract and never
imports ``core`` or ``src`` — so it is safe to ship.
"""
