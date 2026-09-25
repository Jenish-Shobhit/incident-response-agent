"""The model boundary, with the provider SDK replaced by a fake. No network, no tokens."""

from types import SimpleNamespace

import pytest

from incident_agent import config
from incident_agent.agents.loop import run_agent
from incident_agent.llm import anthropic_api


class Block(SimpleNamespace):
    def model_dump(self):
        return dict(vars(self))


def reply(content, stop_reason="end_turn", stop_details=None):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop_reason, stop_details=stop_details, usage=usage)


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.replies.pop(0)


@pytest.fixture
def live_anthropic(monkeypatch):
    monkeypatch.setattr(config, "MOCK", False)
    monkeypatch.setattr(config, "PROVIDER", "anthropic")

    def install(replies):
        fake = FakeClient(replies)
        monkeypatch.setattr(anthropic_api, "_client", fake)
        return fake

    return install


def test_thinking_blocks_are_replayed_unchanged_before_the_tool_call(live_anthropic, records):
    """A turn that thought and then called a tool must be sent back with its thinking intact."""
    thought = Block(type="thinking", thinking="check the lock first", signature="sig-1")
    fake = live_anthropic([
        reply([thought, Block(type="tool_use", id="t1", name="search_logs", input={"pattern": "lock"})],
              stop_reason="tool_use"),
        reply([Block(type="text", text='{"answer": "done", "claims": []}')]),
    ])

    out = run_agent("log", "system", "question", records)

    assert out["json"] == {"answer": "done", "claims": []}
    assistant = fake.requests[1]["messages"][1]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == {"type": "thinking", "thinking": "check the lock first", "signature": "sig-1"}
    assert assistant["content"][-1]["type"] == "tool_use"
    tool_results = fake.requests[1]["messages"][2]["content"]
    assert [b["type"] for b in tool_results] == ["tool_result"]


def test_a_refusal_raises_instead_of_reading_an_empty_answer(live_anthropic, records):
    live_anthropic([reply([], stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"))])
    with pytest.raises(RuntimeError, match="declined.*cyber"):
        run_agent("planner", "system", "question", records)


def test_requests_carry_the_configured_model_and_the_refusal_fallback(live_anthropic, records):
    fake = live_anthropic([reply([Block(type="text", text="{}")])])
    run_agent("planner", "system", "question", records)
    sent = fake.requests[0]
    assert sent["model"] == config.ANTHROPIC_MODEL
    assert sent["extra_body"] == {"fallbacks": "default"}
    assert "temperature" not in sent, "current models reject temperature; it is only sent when asked"


def test_live_mode_without_a_key_is_reported_not_crashed(monkeypatch):
    monkeypatch.setattr(config, "MOCK", False)
    monkeypatch.setattr(config, "PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert any("ANTHROPIC_API_KEY" in p for p in config.problems())
