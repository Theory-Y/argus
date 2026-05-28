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

    # System prompt must be sent as a cached block (prompt caching).
    system = client.captured["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["text"] == prompt.SYSTEM_PROMPT
    # The model id is honored.
    assert client.captured["model"] == "claude-opus-4-7"


def test_write_memo_concatenates_only_text_blocks():
    client = _FakeClient([_Block("text", "A"), _Block("thinking", "ignored"), _Block("text", "B")])
    assert writer.write_memo("X", "{}", client=client) == "AB"


if __name__ == "__main__":
    # Allow running without pytest.
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok: {name}")
    print("ALL PASSED")
