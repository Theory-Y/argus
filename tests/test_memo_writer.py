"""Unit tests for the server-side memo writer and prompt — no live API calls."""

import os
import sys
from pathlib import Path

# Make the repo root importable so `core` resolves when pytest runs from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.memo import prompt, writer  # noqa: E402


# ── Fakes that mimic the anthropic streaming client surface we use ───────────
class _Block:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class _FinalMessage:
    def __init__(self, blocks):
        self.content = blocks


class _Stream:
    def __init__(self, blocks):
        self._blocks = blocks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return _FinalMessage(self._blocks)


class _Messages:
    def __init__(self, blocks, capture):
        self._blocks = blocks
        self._capture = capture

    def stream(self, **kwargs):
        self._capture.update(kwargs)
        return _Stream(self._blocks)


class _FakeClient:
    def __init__(self, blocks):
        self.captured = {}
        self.messages = _Messages(blocks, self.captured)


def test_prompt_has_six_sections_and_persona():
    assert len(prompt.SECTIONS) == 6
    assert "Principal Equity Research Analyst" in prompt.SYSTEM_PROMPT
    for heading, _ in prompt.SECTIONS:
        assert heading in prompt.SYSTEM_PROMPT


def test_user_message_embeds_ticker_and_payload():
    msg = prompt.user_message("pcor", '{"x":1}')
    assert "PCOR" in msg
    assert '{"x":1}' in msg


def test_write_memo_returns_text_and_caches_system_prompt():
    client = _FakeClient([_Block("thinking", ""), _Block("text", "# Investment Memo: PCOR\n...")])
    out = writer.write_memo("PCOR", '{"meta":{}}', client=client, model="claude-opus-4-7")

    assert out.startswith("# Investment Memo: PCOR")

    # System prompt must be sent as a cached block (prompt caching), and the cache
    # defaults to the 1h window so the static prefix stays warm across spaced runs.
    system = client.captured["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert system[0]["text"] == prompt.SYSTEM_PROMPT
    # The model id is honored.
    assert client.captured["model"] == "claude-opus-4-7"


def test_cache_ttl_is_configurable():
    # "5m" uses the default ephemeral window (no explicit ttl); "1h" is passed through.
    client = _FakeClient([_Block("text", "x")])
    writer.write_memo("X", "{}", client=client, cache_ttl="5m")
    assert client.captured["system"][0]["cache_control"] == {"type": "ephemeral"}

    client = _FakeClient([_Block("text", "x")])
    writer.write_memo("X", "{}", client=client, cache_ttl="1h")
    assert client.captured["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_write_memo_concatenates_only_text_blocks():
    client = _FakeClient([_Block("text", "A"), _Block("thinking", "ignored"), _Block("text", "B")])
    assert writer.write_memo("X", "{}", client=client) == "AB"


# ── Fakes that mimic the anthropic Message Batches client surface we use ──────
class _BatchResultInner:
    def __init__(self, type_, message=None):
        self.type = type_
        self.message = message


class _BatchResult:
    def __init__(self, custom_id, type_, blocks=None):
        self.custom_id = custom_id
        message = _FinalMessage(blocks) if blocks is not None else None
        self.result = _BatchResultInner(type_, message)


class _Batch:
    def __init__(self, id_, status):
        self.id = id_
        self.processing_status = status


class _Batches:
    def __init__(self, results, capture):
        self._results = results
        self._capture = capture

    def create(self, *, requests):
        self._capture["requests"] = requests
        return _Batch("batch_test", "ended")  # completes immediately for the test

    def retrieve(self, _id):
        return _Batch("batch_test", "ended")

    def results(self, _id):
        return iter(self._results)


class _FakeBatchClient:
    def __init__(self, results):
        self.captured = {}
        self.messages = type("M", (), {"batches": _Batches(results, self.captured)})()


def test_write_memos_batch_maps_results_by_ticker():
    results = [
        _BatchResult("PCOR", "succeeded", [_Block("text", "# Investment Memo: PCOR")]),
        _BatchResult("Z", "errored", None),
    ]
    client = _FakeBatchClient(results)
    out = writer.write_memos_batch(
        [("pcor", '{"meta":{}}'), ("z", '{"meta":{}}')], client=client
    )

    assert out["PCOR"].startswith("# Investment Memo: PCOR")
    assert out["Z"] is None
    # Tickers are upper-cased and each request reuses the shared cached system prompt.
    sent = client.captured["requests"]
    assert {r["custom_id"] for r in sent} == {"PCOR", "Z"}
    assert sent[0]["params"]["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_write_memos_batch_empty_is_noop():
    # No client needed — empty input short-circuits before any API call.
    assert writer.write_memos_batch([]) == {}


if __name__ == "__main__":
    # Allow running without pytest.
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok: {name}")
    print("ALL PASSED")
