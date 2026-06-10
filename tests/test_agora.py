"""
agora test suite.  Run:  python -m pytest -q   (from the package root)

Covers the things that must not silently break:
  - the hard spend cap actually raises
  - cost resumes from a starting balance
  - oracles normalize/clamp messy input and score deterministically
  - the detonation cliff penalizes dangerous tunes
  - Elo moves the winner up and loser down
  - memory compression stays bounded and dedupes
  - a mock colony run improves over its first cycle (the loop learns)
  - state round-trips through disk (resume safety)
  - the STOP file halts gracefully
  - the SAME loop runs an entirely different oracle (domain swap)
"""
import os, json, random, tempfile
import pytest

from agora.config import Config
from agora.cost import CostTracker, SpendCapExceeded
from agora.oracles import RotaryOracle, DrugRepurposingOracle
from agora.agent import Agent, update_elo, assign_roles
from agora.colony import Colony


# ----------------------------------------------------------------- cost cap
def test_spend_cap_raises():
    c = CostTracker(cap_usd=0.01)
    with pytest.raises(SpendCapExceeded):
        for _ in range(100):
            c.charge("claude-sonnet-4-6", 10_000, 2_000)
    assert c.usd >= 0.01

def test_cost_resume_starting_balance():
    c = CostTracker(cap_usd=10.0, starting_usd=2.5, starting_calls=40)
    assert c.usd == 2.5 and c.calls == 40
    c.charge("claude-haiku-4-5-20251001", 1000, 100)
    assert c.calls == 41 and c.usd > 2.5


# ------------------------------------------------------------------ oracles
def test_rotary_normalize_clamps():
    o = RotaryOracle()
    t = o.normalize({"afr": 99, "timing": -5, "boost": 500, "port": "bogus", "seal": None})
    assert 10.0 <= t["afr"] <= 15.0
    assert 5.0 <= t["timing"] <= 35.0
    assert 0.0 <= t["boost"] <= 20.0
    assert t["port"] in {"stock", "street", "bridge", "peripheral"}
    assert t["seal"] in {"stock", "ceramic", "steel"}

def test_rotary_score_deterministic():
    o = RotaryOracle()
    t = {"afr": 12.3, "timing": 27, "boost": 8, "port": "street", "seal": "steel"}
    assert o.score(t) == o.score(dict(t))

def test_detonation_cliff_is_punished():
    o = RotaryOracle()
    sane = o.score({"afr": 12.0, "timing": 20, "boost": 6, "port": "street", "seal": "steel"})
    grenade = o.score({"afr": 15.0, "timing": 35, "boost": 20, "port": "street", "seal": "stock"})
    assert grenade < sane  # lean + max boost + max timing must score worse

def test_repurposing_known_winner_beats_random():
    o = DrugRepurposingOracle()
    winner = o.score({"drug": "sirolimus", "target": "mTOR", "mechanism": "inhibit"})
    weak = o.score({"drug": "aspirin", "target": "HDAC", "mechanism": "modulate"})
    assert winner > weak

def test_optimum_estimate_runs():
    assert RotaryOracle().optimum_estimate(samples=5000) > 100


# --------------------------------------------------------------------- elo
def test_elo_winner_gains_loser_loses():
    w, l = Agent(0, "explorer", 1000), Agent(1, "skeptic", 1000)
    update_elo(w, l)
    assert w.elo > 1000 and l.elo < 1000
    assert round(w.elo + l.elo) == 2000  # zero-sum

def test_assign_roles_cycles():
    assert assign_roles(4) == ["explorer", "optimizer", "skeptic", "explorer"]


# ------------------------------------------------------------------- memory
def test_memory_compression_bounded_and_dedupes():
    a = Agent(0, "optimizer")
    for i in range(20):
        a.remember(f"lesson {i}", keep=6)
    assert len(a.memory) == 6
    a.remember("dupe", keep=6); a.remember("dupe", keep=6)
    assert a.memory.count("dupe") == 1


# -------------------------------------------------------------------- loop
def _cfg(tmp, **kw):
    d = dict(use_mock=True, n_cycles=10, n_agents=5, seed=3, patience=99,
             state_file=os.path.join(tmp, "s.json"),
             log_file=os.path.join(tmp, "l.jsonl"),
             curve_file=os.path.join(tmp, "c.csv"))
    d.update(kw)
    return Config(**d)

def test_colony_improves_over_first_cycle():
    with tempfile.TemporaryDirectory() as tmp:
        s = Colony(_cfg(tmp), "rotary").run()
        assert s["cycles_run"] >= 5
        assert s["best_score"] > 150           # climbed well above random baseline
        assert s["gap"] < 30                    # got reasonably close to optimum

def test_state_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, n_cycles=4)
        s1 = Colony(cfg, "rotary").run()
        assert os.path.exists(cfg.state_file)
        # resume: continue 4 more cycles; cost must carry over (be >= prior)
        cfg2 = _cfg(tmp, n_cycles=8); cfg2.state_file = cfg.state_file
        s2 = Colony(cfg2, "rotary").run()
        assert s2["cost"]["calls"] >= s1["cost"]["calls"]
        assert s2["best_score"] >= s1["best_score"]

def test_stop_file_halts():
    with tempfile.TemporaryDirectory() as tmp:
        stop = os.path.join(tmp, "STOP")
        open(stop, "w").close()
        cfg = _cfg(tmp, n_cycles=50, stop_file=stop)
        s = Colony(cfg, "rotary").run()
        assert s["stop_reason"] == "stop_file"

def test_domain_swap_repurposing_runs():
    with tempfile.TemporaryDirectory() as tmp:
        s = Colony(_cfg(tmp, n_cycles=6), "repurposing").run()
        assert s["oracle"] == "repurposing"
        assert s["best"] is not None


# -------------------------------------------------------- candidate logging
def _load_log(path):
    return [json.loads(l) for l in open(path) if l.strip()]

def test_candidate_logging_emits_all_event_types():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, n_cycles=4, n_agents=4, log_candidates=True)
        Colony(cfg, "rotary").run()
        kinds = {r["event"] for r in _load_log(cfg.log_file)}
        assert {"proposal", "critique", "revision"} <= kinds
        # a revision event must record before/after scores and an accept flag
        rev = next(r for r in _load_log(cfg.log_file) if r["event"] == "revision")
        assert {"before_score", "after_score", "accepted"} <= rev.keys()

def test_log_candidates_off_suppresses_events():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, n_cycles=3, log_candidates=False)
        Colony(cfg, "rotary").run()
        kinds = {r["event"] for r in _load_log(cfg.log_file)}
        assert "proposal" not in kinds and "critique" not in kinds
        assert "cycle" in kinds   # cycle-level logging still happens

def test_inspector_signals_runs():
    from agora.inspect_run import load, show_signals, show_cycle
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, n_cycles=4, log_candidates=True)
        Colony(cfg, "rotary").run()
        rows = load(cfg.log_file)
        show_signals(rows)        # must not raise
        show_cycle(rows, 2)       # must not raise


# ----------------------------------------------------- role registry & kinds
def test_role_registry_kinds():
    from agora.roles import (ROLE_REGISTRY, QUANT_ROSTER, BASE_ROSTER,
                             get_role, kind_of, PROPOSER, CRITIC, VALIDATOR)
    assert all(kind_of(r) == PROPOSER for r in BASE_ROSTER)
    assert len(QUANT_ROSTER) == 12
    kinds = [kind_of(r) for r in QUANT_ROSTER]
    assert kinds.count(PROPOSER) == 7
    assert kinds.count(CRITIC) == 4
    assert kinds.count(VALIDATOR) == 1
    assert "leakage_auditor" in QUANT_ROSTER and kind_of("leakage_auditor") == CRITIC
    with pytest.raises(KeyError):
        get_role("does_not_exist")

def test_kind_routing_only_proposers_generate():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, n_cycles=4, n_agents=4,
                   roster=["explorer", "optimizer", "critic", "auditor"])
        Colony(cfg, "rotary").run()
        rows = _load_log(cfg.log_file)
        prop_roles = {r["role"] for r in rows if r["event"] == "proposal"}
        assert prop_roles == {"explorer", "optimizer"}      # critic/auditor never propose
        assert any(r["event"] == "audit" and r["role"] == "auditor" for r in rows)
        assert any(r["event"] == "critique" for r in rows)

def test_roster_with_no_proposer_raises():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, n_cycles=2, n_agents=2, roster=["critic", "auditor"])
        with pytest.raises(ValueError):
            Colony(cfg, "rotary").run()

def test_quant_roster_runs_end_to_end():
    from agora.roles import QUANT_ROSTER
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, n_cycles=3, n_agents=12, roster=QUANT_ROSTER)
        s = Colony(cfg, "rotary").run()          # mechanics are oracle-agnostic
        assert s["cycles_run"] == 3
        rows = _load_log(cfg.log_file)
        # 7 proposer roles -> proposals; 1 validator -> audits
        assert {r["role"] for r in rows if r["event"] == "proposal"} <= set(QUANT_ROSTER)
        assert any(r["event"] == "audit" for r in rows)


# -------------------------------------------- formula synthesis (Z3-verified)
def test_formula_oracle_verify_and_optimum():
    from agora.oracles import FormulaSynthesisOracle
    o = FormulaSynthesisOracle("majority3")
    assert o.verify(o._ref) is True
    assert o.verify({"var": "a"}) is False
    assert o.score(o._ref) == o.optimum_estimate()

def test_formula_oracle_gradient_rewards_minimality():
    from agora.oracles import FormulaSynthesisOracle
    o = FormulaSynthesisOracle("majority3")
    minimal = o.score(o._ref)
    bloated_ast = {"op": "or", "args": [o._ref, o._ref]}
    assert o.verify(bloated_ast) is True
    assert 0 < o.score(bloated_ast) < minimal

def test_formula_normalize_coerces_junk():
    from agora.oracles import FormulaSynthesisOracle
    o = FormulaSynthesisOracle("majority3")
    coerced = o.normalize({"op": "xor", "args": []})
    assert isinstance(coerced, dict) and o.score(coerced) >= 0

def test_colony_runs_on_formula_oracle():
    from agora.roles import FORMAL_ROSTER
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, n_cycles=6, n_agents=6, roster=FORMAL_ROSTER)
        s = Colony(cfg, "formula").run()
        assert s["oracle"] == "formula"
        assert s["best_score"] > 50

def test_formal_roster_shape():
    from agora.roles import FORMAL_ROSTER, kind_of, PROPOSER, CRITIC, VALIDATOR
    assert len(FORMAL_ROSTER) == 6
    kinds = [kind_of(r) for r in FORMAL_ROSTER]
    assert kinds.count(PROPOSER) == 3 and kinds.count(CRITIC) == 2 and kinds.count(VALIDATOR) == 1


# all four spec targets must be present and verifiable by construction
@pytest.mark.parametrize("target", ["majority3", "mux", "and3", "parity3"])
def test_all_formula_targets_verify_and_optimal(target):
    from agora.oracles import FormulaSynthesisOracle
    o = FormulaSynthesisOracle(target)
    # the reference formula is provably equivalent to the spec ...
    assert o.verify(o._ref) is True
    # ... and a constant-false-ish single var is NOT (sanity that verify can say no)
    assert o.verify({"var": "a"}) is False
    # ... and the reference sits exactly at the estimated optimum (correct + minimal)
    assert o.score(o._ref) == o.optimum_estimate()
    assert o.score(o._ref) >= 100  # fully correct => >= 100 before parsimony bonus

def test_formula_target_embedded_in_all_prompts():
    """The CRITICAL bug to avoid: agents must be TOLD the target. The full truth
    table must appear in the system, critique, AND revise prompts."""
    from agora.oracles import FormulaSynthesisOracle
    o = FormulaSynthesisOracle("majority3")
    spec = o.target_spec_text()
    assert "->" in spec  # it really is a truth table
    assert spec in o.system_prompt("flavor")
    assert spec in o.critique_prompt(o._ref)
    assert spec in o.revise_prompt(o._ref, ["c1"])

def test_parity3_minimal_beats_bloated():
    from agora.oracles import FormulaSynthesisOracle
    o = FormulaSynthesisOracle("parity3")
    minimal = o.score(o._ref)
    bloated = o.score({"op": "or", "args": [o._ref, {"op": "and", "args": [o._ref, o._ref]}]})
    assert o.verify(o._ref) is True
    assert 100 <= bloated < minimal  # both correct; minimal wins on parsimony
