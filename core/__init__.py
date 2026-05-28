"""
core — PROPRIETARY engine façade for the TheoryY research service.

This package is the IP boundary. It is shipped to source-sale buyers and run on
our own servers for SaaS, but it is NEVER bundled into the distributable client.
The server (../server) imports from here; the client (../client) must not.
"""

__all__ = ["engine", "render"]
