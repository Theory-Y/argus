"""
core.memo.writer — server-side memo generation via the Anthropic API.

This keeps the IP server-side: the finished memo is written here using the
hidden prompt in prompt.py. The customer only ever receives the rendered output.

Token economy (all quality-neutral — same model, prompt, and output):
  • The system prompt is large and static, so it is sent as a cached block
    (cache_control: ephemeral). The first memo pays the write premium, every memo
    after reads it at ~0.1x cost. The per-request user turn (the context JSON) sits
    after the cached prefix so it never invalidates the cache.
  • The cache TTL defaults to "1h" (ANTHROPIC_CACHE_TTL) so the cached prefix stays
    warm across spaced-out or batched runs — the default ephemeral window is only
    5 minutes. The 1h write costs ~2x vs ~1.25x for 5m, so it pays off once ≥3 memos
    share the window; set ANTHROPIC_CACHE_TTL=5m for low-volume/isolated runs.
  • write_memos_batch() generates many memos through the Message Batches API at 50%
    of standard price. All requests share the one cached system-prompt prefix.
  • Every call logs usage (input / cache_read / cache_write / output tokens) so the
    cache hit rate is measurable rather than assumed.
"""

from __future__ import annotations

import logging
import os
import time

from .prompt import SYSTEM_PROMPT, user_message

logger = logging.getLogger(__name__)

# Default to the most capable model; override per-deployment via ANTHROPIC_MODEL.
_DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
_DEFAULT_EFFORT = os.environ.get("ANTHROPIC_EFFORT", "medium")
_DEFAULT_MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "6000"))
# Prompt-cache TTL for the static system prompt: "1h" (default) or "5m". See the
# module docstring for the write-premium vs reuse tradeoff.
_DEFAULT_CACHE_TTL = os.environ.get("ANTHROPIC_CACHE_TTL", "1h")


def _cache_control(cache_ttl: str | None = None) -> dict:
    """
    Build the system-prompt cache_control block.

    "5m" uses the default ephemeral window (no explicit ttl); any other value
    (e.g. "1h") is passed through as the ttl. 1h cache is GA — no beta header.
    """
    control: dict = {"type": "ephemeral"}
    ttl = cache_ttl or _DEFAULT_CACHE_TTL
    if ttl and ttl != "5m":
        control["ttl"] = ttl
    return control


def _request_params(
    ticker: str,
    context_json: str,
    *,
    model: str | None = None,
    effort: str | None = None,
    max_tokens: int | None = None,
    cache_ttl: str | None = None,
) -> dict:
    """
    Shared Messages-API params for both the single and batch paths.

    Keeping one builder guarantees a batched memo is byte-for-byte the same request
    as a single one — identical model, prompt, thinking, and effort — so the 50%
    batch discount comes with no change to the output distribution.
    """
    return {
        "model": model or _DEFAULT_MODEL,
        "max_tokens": max_tokens or _DEFAULT_MAX_TOKENS,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort or _DEFAULT_EFFORT},
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": _cache_control(cache_ttl),
            }
        ],
        "messages": [{"role": "user", "content": user_message(ticker, context_json)}],
    }


def _memo_text(message) -> str:
    """Concatenate the text blocks of a finished message into the memo markdown."""
    return "".join(block.text for block in message.content if block.type == "text")


def _log_usage(label: str, usage) -> None:
    """
    Emit cache-hit + token telemetry so cache effectiveness is observable. After the
    first memo in a warm window, cache_read should dominate input; if it stays zero
    across memos, a silent cache invalidator is at work (see shared/prompt-caching).
    """
    if usage is None:
        return
    logger.info(
        "memo usage [%s]: input=%s cache_read=%s cache_write=%s output=%s",
        label,
        getattr(usage, "input_tokens", None),
        getattr(usage, "cache_read_input_tokens", None),
        getattr(usage, "cache_creation_input_tokens", None),
        getattr(usage, "output_tokens", None),
    )


def write_memo(
    ticker: str,
    context_json: str,
    *,
    model: str | None = None,
    effort: str | None = None,
    max_tokens: int | None = None,
    cache_ttl: str | None = None,
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

    params = _request_params(
        ticker,
        context_json,
        model=model,
        effort=effort,
        max_tokens=max_tokens,
        cache_ttl=cache_ttl,
    )
    with client.messages.stream(**params) as stream:
        message = stream.get_final_message()

    _log_usage(ticker, getattr(message, "usage", None))
    return _memo_text(message)


def write_memos_batch(
    items,
    *,
    model: str | None = None,
    effort: str | None = None,
    max_tokens: int | None = None,
    cache_ttl: str | None = None,
    client=None,
    poll_interval: float = 30.0,
    max_wait: float = 24 * 3600,
) -> dict:
    """Generate many memos via the Message Batches API — 50% cheaper, same output.

    For sector-wide / multi-ticker runs where latency is not critical. Every request
    shares the one cached system-prompt prefix, so the cache is written once and read
    by the rest of the batch; the model, prompt, thinking, and effort are identical to
    ``write_memo`` (via the shared param builder), so only the price changes.

    ``items`` is an iterable of ``(ticker, context_json)`` pairs. Returns a
    ``{ticker: memo_markdown}`` dict; a request that failed maps to ``None``.

    Blocks until the batch finishes, polling every ``poll_interval`` seconds up to
    ``max_wait`` (batches usually complete within an hour; the API cap is 24h).
    ``client`` is injectable for testing (stub ``messages.batches.create/retrieve/
    results``); in production it defaults to ``anthropic.Anthropic()``.
    """
    pairs = [(ticker.upper(), context_json) for ticker, context_json in items]
    if not pairs:
        return {}

    if client is None:
        import anthropic

        client = anthropic.Anthropic()

    requests = [
        {
            "custom_id": ticker,
            "params": _request_params(
                ticker,
                context_json,
                model=model,
                effort=effort,
                max_tokens=max_tokens,
                cache_ttl=cache_ttl,
            ),
        }
        for ticker, context_json in pairs
    ]

    batch = client.messages.batches.create(requests=requests)
    logger.info("memo batch %s created with %d request(s)", batch.id, len(requests))

    deadline = time.monotonic() + max_wait
    while batch.processing_status != "ended":
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"memo batch {batch.id} did not finish within {max_wait:.0f}s"
            )
        time.sleep(poll_interval)
        batch = client.messages.batches.retrieve(batch.id)

    results: dict = {}
    for result in client.messages.batches.results(batch.id):
        custom_id = result.custom_id
        if result.result.type == "succeeded":
            message = result.result.message
            _log_usage(f"batch:{custom_id}", getattr(message, "usage", None))
            results[custom_id] = _memo_text(message)
        else:
            logger.error(
                "memo batch request %s did not succeed: %s",
                custom_id,
                result.result.type,
            )
            results[custom_id] = None
    return results
