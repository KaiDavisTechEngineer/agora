"""
Phase 2 — per-role-kind model selection.

  - config parsing: default, valid override, invalid kind, invalid/unpriced model
  - the DEFAULT exactly reproduces the historical gen/grunt single-/two-tier mapping
  - claude-fable-5 is an assignable, priced model
  - per-model cost attribution is correct against mocked API calls
  - each role-kind's work is billed to exactly the model named in config
  - the Z3 verifier verdict is independent of which model proposed (no self-grading)
"""
import os, tempfile
import pytest

from agora.config import (Config, resolve_role_models, PRICES, ROLE_KINDS,
                          GEN_MODEL, GRUNT_MODEL)
from agora.cost import CostTracker, SpendCapExceeded
from agora.colony import Colony


# --------------------------------------------------------- config parsing
def test_default_reproduces_gen_grunt_tiers():
    m = resolve_role_models(Config())
    assert m == {"proposer": GEN_MODEL, "critic": GRUNT_MODEL, "validator": GRUNT_MODEL}


def test_partial_override_keeps_defaults_for_unset_kinds():
    m = resolve_role_models(Config(role_models={"proposer": "claude-fable-5"}))
    assert m["proposer"] == "claude-fable-5"
    assert m["critic"] == GRUNT_MODEL and m["validator"] == GRUNT_MODEL


def test_full_override_per_kind():
    cfg = Config(role_models={"proposer": "claude-fable-5",
                              "critic": "claude-haiku-4-5-20251001",
                              "validator": "claude-sonnet-4-6"})
    m = resolve_role_models(cfg)
    assert m == {"proposer": "claude-fable-5",
                 "critic": "claude-haiku-4-5-20251001",
                 "validator": "claude-sonnet-4-6"}


def test_invalid_role_kind_raises():
    with pytest.raises(ValueError):
        resolve_role_models(Config(role_models={"propozer": "claude-fable-5"}))


def test_unpriced_model_raises():
    with pytest.raises(ValueError):
        resolve_role_models(Config(role_models={"proposer": "gpt-imaginary"}))


def test_fable5_is_priced_and_assignable():
    assert "claude-fable-5" in PRICES
    assert PRICES["claude-fable-5"] == (10.00, 50.00)
    # assigning it must not raise
    assert resolve_role_models(Config(role_models={"proposer": "claude-fable-5"}))["proposer"] \
        == "claude-fable-5"


def test_role_kinds_constant_matches_resolver_keys():
    assert set(ROLE_KINDS) == set(resolve_role_models(Config()))


# --------------------------------------------------- per-model accounting
def test_cost_tracker_per_model_breakdown():
    c = CostTracker(cap_usd=100.0)
    c.charge("claude-fable-5", 1_000_000, 0)          # $10.00
    c.charge("claude-sonnet-4-6", 1_000_000, 0)       # $3.00
    c.charge("claude-fable-5", 0, 1_000_000)          # $50.00
    bm = c.as_dict()["by_model"]
    assert round(bm["claude-fable-5"]["usd"], 2) == 60.00
    assert bm["claude-fable-5"]["calls"] == 2
    assert round(bm["claude-sonnet-4-6"]["usd"], 2) == 3.00
    # per-model totals reconcile with the single global total
    assert round(sum(r["usd"] for r in bm.values()), 6) == round(c.usd, 6)
    assert sum(r["calls"] for r in bm.values()) == c.calls


def test_per_model_breakdown_resumes_from_starting_balance():
    start = {"claude-fable-5": {"usd": 10.0, "calls": 1, "in_tok": 1_000_000, "out_tok": 0}}
    c = CostTracker(cap_usd=100.0, starting_usd=10.0, starting_calls=1,
                    starting_in=1_000_000, starting_by_model=start)
    c.charge("claude-fable-5", 1_000_000, 0)
    bm = c.as_dict()["by_model"]
    assert bm["claude-fable-5"]["calls"] == 2
    assert round(bm["claude-fable-5"]["usd"], 2) == 20.00


# ----------------------------------------------- colony routing + attribution
def _cfg(tmp, **kw):
    from agora.roles import FORMAL_ROSTER
    d = dict(use_mock=True, n_cycles=3, seed=3, patience=99, n_agents=6,
             roster=FORMAL_ROSTER, oracle_kwargs={"target": "majority3"},
             state_file=os.path.join(tmp, "s.json"),
             log_file=os.path.join(tmp, "l.jsonl"),
             curve_file=os.path.join(tmp, "c.csv"))
    d.update(kw)
    return Config(**d)


def test_default_run_bills_only_gen_and_grunt_tiers():
    """With no role_models, the FORMAL roster must bill exactly the two historical
    tiers — proving the default reproduces single-/two-model behaviour."""
    with tempfile.TemporaryDirectory() as tmp:
        s = Colony(_cfg(tmp), "formula").run()
        billed = set(s["cost"]["by_model"])
        assert billed == {GEN_MODEL, GRUNT_MODEL}


def test_per_role_models_attribute_costs_to_named_models():
    """Each role-kind's work must be billed to exactly the model named in config."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, role_models={"proposer": "claude-fable-5",
                                     "critic": "claude-haiku-4-5-20251001",
                                     "validator": "claude-sonnet-4-6"})
        s = Colony(cfg, "formula").run()
        bm = s["cost"]["by_model"]
        # proposer (generate+revise) -> fable-5; critic (critique) -> haiku;
        # validator (audit) -> sonnet. The FORMAL roster has all three kinds.
        assert bm["claude-fable-5"]["calls"] > 0          # proposers generated
        assert bm["claude-haiku-4-5-20251001"]["calls"] > 0  # critics critiqued
        assert bm["claude-sonnet-4-6"]["calls"] > 0       # validator audited
        # no OTHER model was billed
        assert set(bm) == {"claude-fable-5", "claude-haiku-4-5-20251001", "claude-sonnet-4-6"}
        # the per-model breakdown still reconciles to the single global total
        assert round(sum(r["usd"] for r in bm.values()), 6) == round(s["cost"]["usd"], 6)


def test_per_model_spend_feeds_single_global_cap():
    """A tiny cap halts the run regardless of how many models are in play (I2)."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, n_cycles=50, spend_cap_usd=0.0008,
                   role_models={"proposer": "claude-fable-5"})
        s = Colony(cfg, "formula").run()
        assert s["stop_reason"] == "spend_cap"
        assert s["cost"]["usd"] >= 0.0008


def test_proposer_model_does_not_change_verifier_verdict():
    """Swapping the proposer's model must not change whether Z3 verifies a candidate —
    the gate is independent of who/what proposed it (no self-grading shortcut, I1)."""
    from agora.oracles import FormulaSynthesisOracle
    o = FormulaSynthesisOracle("majority3")
    # verify() takes only the candidate; there is no model parameter to influence it
    assert o.verify(o._ref) is True
    assert o.verify({"var": "a"}) is False
    # and the resolved validator model is independent of the proposer model
    m = resolve_role_models(Config(role_models={"proposer": "claude-fable-5"}))
    assert m["validator"] == GRUNT_MODEL   # unaffected by the proposer override
