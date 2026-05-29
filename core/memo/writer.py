"""
core.memo.writer — server-side memo generation via the Anthropic API.

This is what makes the SaaS model possible without leaking IP: the finished memo
is written here, on our infrastructure, using the hidden prompt in prompt.py. The
customer only ever receives the rendered output.

The system prompt is large and static, so it is sent as a cached block
(cache_control: ephemeral) — the first memo pays the write premium, every memo
after reads it at ~0.1x cost. The per-request user turn (the context JSON) sits
after the cached prefix so it never invalidates the cache.
"""

from __future__ import annotations

import os

from .prompt import SYSTEM_PROMPT, user_message

# Default to the most capable model; override per-deployment via ANTHROPIC_MODEL.
_DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
_DEFAULT_EFFORT = os.environ.get("ANTHROPIC_EFFORT", "medium")
_DEFAULT_MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "6000"))


def write_memo(
    ticker: str,
    context_json: str,
    *,
    model: str | None = None,
    effort: str | None = None,
    max_tokens: int | None = None,
    client=None,
) -> str:
    """Generate the five-section memo markdown for ``ticker`` from ``context_json``.

    ``client`` is injectable for testing (pass a stub exposing
    ``messages.stream(...)``). In production it defaults to ``anthropic.Anthropic()``,
    which reads ``ANTHROPIC_API_KEY`` from the environment.
    """
    if client is None:
        import anthropic

        client = anthropic.Anthropic()

    with client.messages.stream(
        model=model or _DEFAULT_MODEL,
        max_tokens=max_tokens or _DEFAULT_MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": effort or _DEFAULT_EFFORT},
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message(ticker, context_json)}],
    ) as stream:
        message = stream.get_final_message()

    return "".join(block.text for block in message.content if block.type == "text")
