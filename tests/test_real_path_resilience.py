"""
Stage 1 — real-client path resilience (the seams the flavor-blind mock can't exercise).

  - a model call that FAILS (after the SDK's own retries) is contained: not charged,
    an api_error event is logged, and the run completes instead of crashing
  - a model reply that can't be parsed (refusal / prose / empty) degrades to the
    Oracle default and logs a parse_fallback event — never crashes, never corrupts state
  - SpendCapExceeded is never swallowed by the containment
  - _parse_candidate reports fallback only for genuinely unparseable replies
"""
import json, os, tempfile
import pytest

from agora.config import Config
from agora.colony import Colony, _parse_candidate
from agora.cost import CostTracker, SpendCapExceeded
from agora.llm import LLMReply
from agora.oracles import FormulaSynthesisOracle
from agora.roles import FORMAL_ROSTER


def _cfg(tmp, **kw):
    d = dict(use_mock=True, n_cycles=3, seed=3, patience=99, n_agents=6,
             roster=FORMAL_ROSTER, oracle_kwargs={"target": "majority3"},
             state_file=os.path.join(tmp, "s.json"),
             log_file=os.path.join(tmp, "l.jsonl"),
             curve_file=os.path.join(tmp, "c.csv"))
    d.update(kw)
    return Config(**d)


def _rows(path):
    return [json.loads(l) for l in open(path) if l.strip()]


class _RaisingClient:
    """Simulates an API/network failure that survives the SDK's own retries."""
    def complete(self, model, system, user, max_tokens=600):
        raise RuntimeError("simulated API failure (post-retry)")


class _GarbageClient:
    """Returns a successful but unparseable reply (refusal-style prose)."""
    def complete(self, model, system, user, max_tokens=600):
        return LLMReply("I'm sorry, I can't help with that. No JSON here.", 7, 9)


class _CapRaisingClient:
    """A client whose call itself raises SpendCapExceeded (must NOT be contained)."""
    def complete(self, model, system, user, max_tokens=600):
        raise SpendCapExceeded("from inside the client")


# --------------------------------------------------- _parse_candidate contract
def test_parse_candidate_reports_fallback_flag():
    o = FormulaSynthesisOracle("majority3")
    cand, fb = _parse_candidate('{"op":"or","args":[{"var":"a"},{"var":"b"}]}', o)
    assert fb is False and cand["op"] == "or"
    for junk in ["", "I refuse.", "{not json", "[1,2,3]", "answer is {a} or {b}"]:
        cand, fb = _parse_candidate(junk, o)
        assert fb is True and o.score(cand) >= 0          # default, scoreable, no raise


# ------------------------------------------------- API failure is contained
def test_api_failure_does_not_crash_and_is_not_charged():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        col = Colony(cfg, "formula")
        col.client = _RaisingClient()
        s = col.run()                                     # must NOT raise
        rows = _rows(cfg.log_file)
        # every stage that calls the model logged an api_error
        errs = [r for r in rows if r["event"] == "api_error"]
        assert errs and {r["stage"] for r in errs} <= {"generate", "critique",
                                                        "revise", "audit"}
        # a failed call is never charged — zero successful calls, zero spend
        assert s["cost"]["calls"] == 0 and s["cost"]["usd"] == 0.0
        # the run still completed cleanly and saved resumable state
        assert s["cycles_run"] == 3 and os.path.exists(cfg.state_file)


# ------------------------------------------------- garbage output degrades
def test_garbage_output_logs_parse_fallback_and_completes():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        col = Colony(cfg, "formula")
        col.client = _GarbageClient()
        s = col.run()                                     # must NOT raise
        rows = _rows(cfg.log_file)
        pfs = [r for r in rows if r["event"] == "parse_fallback"]
        assert pfs and {r["stage"] for r in pfs} <= {"generate", "revise"}
        # garbage replies DID succeed, so they are charged (they aren't API failures)
        assert s["cost"]["calls"] > 0
        assert s["cycles_run"] == 3


# ------------------------------------------------- SpendCapExceeded not swallowed
def test_spend_cap_exceeded_is_never_contained():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        col = Colony(cfg, "formula")
        col.client = _CapRaisingClient()
        s = col.run()                                     # Colony.run catches it -> halt
        assert s["stop_reason"] == "spend_cap"
        rows = _rows(cfg.log_file)
        # it must NOT have been logged/contained as an api_error
        assert not any(r["event"] == "api_error" for r in rows)


# ------------------------------- mock path unaffected (no spurious degraded events)
def test_mock_path_emits_no_degraded_events():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        Colony(cfg, "formula").run()
        rows = _rows(cfg.log_file)
        assert not any(r["event"] in ("api_error", "parse_fallback") for r in rows)
