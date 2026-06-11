"""
Proposer-path structured-output prompting (prompt-quality only — no gate/verifier/
scoring/parse/cap changes).

  - the rendered proposer prompts (system_prompt = generate+revise system; revise_prompt
    = revise user) carry an explicit strict-JSON / no-markdown / no-prose instruction
  - the truth-table spec, the evolved flavor, and the mock's "Revise to" trigger survive
  - the `{` prefill is sent only on prefill-supporting models and is prepended to the
    reply; the mock accepts-and-ignores prefill; only the proposer path requests it
"""
import json
import pytest

from agora.oracles import FormulaSynthesisOracle, default_target
from agora.llm import AnthropicClient, MockClient, _supports_prefill, LLMReply
import random


O = FormulaSynthesisOracle(default_target(1))      # majority3
CAND = {"op": "or", "args": [{"var": "a"}, {"var": "b"}]}

STRICT_MARKERS = ("OUTPUT FORMAT", "ONLY", "NO markdown", "NO prose", "start with '{'")


# ---------------------------------------------------- strict-format instruction
def test_system_prompt_has_strict_json_instruction():
    s = O.system_prompt("FLAVORX")
    for m in STRICT_MARKERS:
        assert m in s, f"missing strict-format marker: {m!r}"
    # a concrete schema example is present
    assert '{"op":"or","args":[{"var":"a"},{"var":"b"}]}' in s
    # the truth-table spec and the (evolved) flavor still reach the proposer prompt
    assert O.target_spec_text() in s
    assert "FLAVORX" in s


def test_revise_prompt_has_strict_json_instruction_and_mock_trigger():
    r = O.revise_prompt(CAND, ["rows 110,011 disagree"])
    for m in ("OUTPUT FORMAT", "ONLY", "NO markdown", "NO prose", "start with '{'"):
        assert m in r
    assert O.target_spec_text() in r
    # the MockClient routes on this exact phrase — it must survive the rewrite
    assert "revise to" in r.lower()


def test_critique_prompt_unchanged_is_not_proposer_path():
    # the critique (critic) path is NOT a JSON path and must stay prose-friendly
    c = O.critique_prompt(CAND)
    assert "OUTPUT FORMAT" not in c
    assert "disagrees" in c.lower()          # mock critique trigger intact


# ----------------------------------------------------------- prefill behavior
def test_supports_prefill_gate():
    assert _supports_prefill("claude-haiku-4-5-20251001") is True
    assert _supports_prefill("claude-sonnet-4-6") is False
    assert _supports_prefill("claude-fable-5") is False
    assert _supports_prefill("claude-opus-4-8") is False


def test_anthropic_client_prefill_assembly(monkeypatch):
    """On a prefill-supporting model the client appends an assistant '{' turn and
    re-attaches the prefix; on a non-supporting model it sends no prefill (no 400)."""
    sent = {}

    class _FakeMessages:
        def create(self, *, model, max_tokens, system, messages):
            sent["messages"] = messages
            class _Block:  # noqa
                type = "text"; text = '"op":"var"}'   # continuation after the '{'
            class _R:  # noqa
                content = [_Block()]
                class usage:  # noqa
                    input_tokens = 10; output_tokens = 5
            return _R()

    c = AnthropicClient.__new__(AnthropicClient)      # bypass __init__ (no SDK/key)
    c.c = type("X", (), {"messages": _FakeMessages()})()

    # supporting model: prefill turn appended, prefix re-attached -> parseable JSON
    out = c.complete("claude-haiku-4-5-20251001", "sys", "user", prefill="{")
    assert sent["messages"][-1] == {"role": "assistant", "content": "{"}
    assert out.text.startswith("{") and json.loads(out.text) == {"op": "var"}

    # non-supporting model: no assistant prefill turn, text returned as-is
    out2 = c.complete("claude-sonnet-4-6", "sys", "user", prefill="{")
    assert all(m["role"] != "assistant" for m in sent["messages"])
    assert not out2.text.startswith("{")


def test_mock_client_accepts_and_ignores_prefill():
    mc = MockClient(O, random.Random(0))
    r = mc.complete("claude-haiku-4-5-20251001",
                    O.system_prompt("x"), "ROLE=constructor\nBEST_KNOWN={}", prefill="{")
    # mock already returns valid JSON; prefill changes nothing and does not crash
    assert json.loads(r.text)


def test_only_proposer_path_requests_prefill():
    """Generate/revise request the '{' prefill; critique/audit must not."""
    import inspect
    from agora import colony
    src = inspect.getsource(colony.Colony._cycle)
    # exactly the two proposer call sites pass prefill
    assert src.count('prefill="{"') == 2
