"""Model client: request shape, stop reasons, fallback handling and error mapping, with a fake SDK client."""
from types import SimpleNamespace as NS

import anthropic
import httpx2
import pytest

from ticker_agent import brief, llm


class FakeStream:
    def __init__(self, events, final):
        self.events, self.final = events, final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return self.final


class FakeClient:
    def __init__(self, events=(), final=None, error=None):
        self.calls, self.events, self.final, self.error = [], list(events), final, error
        self.beta = NS(messages=NS(stream=self.stream))

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeStream(self.events, self.final)


def msg(content=(), stop="end_turn", parsed=None, category=None):
    return NS(content=list(content), stop_reason=stop, parsed_output=parsed, model="claude-opus-5-5",
              stop_details=NS(category=category) if stop == "refusal" else None,
              usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def text(t, cites=()):
    return NS(type="text", text=t, citations=[NS(type="char_location", document_index=i, document_title=f"S{i + 1}",
                                                  cited_text=c, start_char_index=0, end_char_index=len(c))
                                               for i, c in cites])


@pytest.fixture
def fake(monkeypatch):
    def install(**kw):
        c = FakeClient(**kw)
        monkeypatch.setattr(llm, "_client", c)
        return c
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("BRIEF_EFFORT", raising=False)
    monkeypatch.delenv("CHAT_EFFORT", raising=False)
    return install


def test_brief_request_shape(fake):
    out = brief.BriefOutput(one_liner="x", snapshot=[], recent_developments=[], performance_drivers=[],
                            key_risks=[], client_questions=[])
    c = fake(final=msg(parsed=out))
    assert llm.structured("sys", "user", brief.BriefOutput) is out
    kw = c.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["output_config"] == {"effort": "medium"}
    assert kw["output_format"] is brief.BriefOutput
    assert kw["fallbacks"] == "default" and llm.FALLBACK_BETA in kw["betas"]
    assert not {"temperature", "top_p", "top_k"} & set(kw)


def test_env_overrides_model_and_effort(fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("CHAT_EFFORT", "medium")
    c = fake(final=msg([text("ok")]))
    list(llm.stream_chat("sys", [{"role": "user", "content": "q"}]))
    assert c.calls[0]["model"] == "claude-sonnet-5-5" and c.calls[0]["output_config"] == {"effort": "medium"}
    monkeypatch.setenv("CHAT_EFFORT", "bogus")
    assert llm.effort("chat") == "low"


def test_structured_refusal_and_bad_output(fake):
    fake(final=msg(stop="refusal", category="cyber"))
    with pytest.raises(llm.LLMRefusal) as e:
        llm.structured("s", "u", brief.BriefOutput)
    assert e.value.category == "cyber"
    fake(final=msg(parsed=None))
    with pytest.raises(llm.LLMError) as e:
        llm.structured("s", "u", brief.BriefOutput)
    assert e.value.kind == "bad_output"


def test_stream_chat_text_then_cited_blocks(fake):
    final = msg([NS(type="thinking", thinking=""), text("Revenue rose.", [(0, "Revenue rose 18%.")])])
    fake(events=[NS(type="text", text="Revenue "), NS(type="text", text="rose.")], final=final)
    ev = list(llm.stream_chat("s", []))
    assert [e for e in ev if e[0] == "text"] == [("text", "Revenue "), ("text", "rose.")]
    kind, done = ev[-1]
    assert kind == "done" and done["blocks"] == [{"text": "Revenue rose.", "citations": [
        {"document_index": 0, "document_title": "S1", "cited_text": "Revenue rose 18%.", "start": 0, "end": 17}]}]


def test_stream_chat_fallback_keeps_only_the_answer(fake):
    fb = NS(type="fallback")
    final = msg([text("partial from first model"), fb, text("Answer.")])
    fake(events=[NS(type="text", text="partial"), NS(type="content_block_start", content_block=fb),
                 NS(type="text", text="Answer.")], final=final)
    ev = list(llm.stream_chat("s", []))
    assert ("reset", None) in ev and ev[-1][1]["blocks"] == [{"text": "Answer.", "citations": []}]


def test_stream_chat_refusal(fake):
    fake(final=msg(stop="refusal", category="bio"))
    assert list(llm.stream_chat("s", []))[-1] == ("refusal", "bio")


def test_error_chain_maps_to_friendly_messages(fake):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    cases = [
        (anthropic.AuthenticationError("bad key", response=httpx2.Response(401, request=req), body=None), "auth"),
        (anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=req), body=None), "busy"),
        (anthropic.InternalServerError("oops", response=httpx2.Response(529, request=req), body=None), "outage"),
        (anthropic.APIConnectionError(request=req), "network"),
    ]
    for err, kind in cases:
        fake(error=err)
        with pytest.raises(llm.LLMError) as e:
            llm.structured("s", "u", brief.BriefOutput)
        assert e.value.kind == kind
        assert "key" not in str(e.value).lower() or kind == "auth"
