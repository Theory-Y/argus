"""
theory_y — official client for the TheoryY Research API.

Contains NO proprietary logic: it only knows the HTTP contract. Point it at any
TheoryY server via base_url + key. This is what makes it safe to distribute in
both business models — the same package works whether the engine runs on our
servers (SaaS) or the buyer's (source sale / self-host).
"""

from .client import Client, TheoryYError

__all__ = ["Client", "TheoryYError"]
__version__ = "1.0.0"
