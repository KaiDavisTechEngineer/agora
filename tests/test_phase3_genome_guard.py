"""
Phase 3 — bounded self-improvement: allowlisted mutation surface + audit trail.

  - vet_mutation default-denies anything outside the allowlist (I3)
  - a reward-hacking mutation (touch gate/cap/score/weights) is caught, rejected
    BEFORE the Oracle gate (never evaluated), and recorded in the persistent audit
  - a benign flavor mutation only persists after re-passing the gate (I4)
  - genome + params + audit save/load round-trips deterministically
  - a tampered genome.json cannot smuggle a forbidden param past load()
"""
import json, os, tempfile
import pytest

import agora.evolve as ev
from agora.evolve import (trickle, evolve, load_genome, save_genome, baseline_genome,
                          vet_mutation, apply_mutation, proposer_roles,
                          STRATEGY_PARAM_ALLOWLIST, SACROSANCT_TARGETS)
from agora.roles import FORMAL_ROSTER


def _read(path):
    with open(path) as f:
        return json.load(f)


PROPOSERS = proposer_roles(FORMAL_ROSTER)


# ------------------------------------------------------------- the vetting guard
def test_vet_allows_flavor_on_proposer():
    ok, reason = vet_mutation({"kind": "flavor", "role": PROPOSERS[0], "value": "x"}, PROPOSERS)
    assert ok is True


def test_vet_allows_allowlisted_param():
    for name in STRATEGY_PARAM_ALLOWLIST:
        ok, _ = vet_mutation({"kind": "param", "name": name, "value": 4}, PROPOSERS)
        assert ok is True, name


def test_vet_denies_non_allowlisted_param():
    ok, reason = vet_mutation({"kind": "param", "name": "n_cycles", "value": 999}, PROPOSERS)
    assert ok is False and "allowlist" in reason


@pytest.mark.parametrize("target", ["spend_cap_usd", "verify", "score", "oracle",
                                     "is_improvement", "gen_model", "model_weights"])
def test_vet_flags_sacrosanct_targets_as_reward_hack(target):
    ok, reason = vet_mutation({"kind": "param", "name": target, "value": 1}, PROPOSERS)
    assert ok is False and "REWARD-HACK" in reason


def test_vet_denies_mutation_that_names_the_gate_as_a_kind():
    ok, reason = vet_mutation({"kind": "gate", "value": "bypass"}, PROPOSERS)
    assert ok is False and "REWARD-HACK" in reason


def test_vet_denies_flavor_on_non_proposer():
    ok, reason = vet_mutation({"kind": "flavor", "role": "proof_referee", "value": "x"}, PROPOSERS)
    assert ok is False   # proof_referee is a validator, not a proposer


def test_apply_mutation_never_writes_forbidden_param():
    # even if a forbidden param somehow reached apply_mutation, it must not land
    g, p = apply_mutation({}, {}, {"kind": "param", "name": "spend_cap_usd", "value": 9})
    assert "spend_cap_usd" not in p


# --------------------------------------------- reward-hack is blocked end-to-end
def _hacking_source(name):
    """A propose_mutation that tries to raise the spend cap / rewrite the gate."""
    def _src(role, flavor, step, real, cost, gen_model):
        return {"kind": "param", "name": name, "value": 10_000}
    return _src


@pytest.mark.parametrize("name", ["spend_cap_usd", "score", "verify"])
def test_trickle_blocks_reward_hack_before_gate_and_audits(name):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.json")
        elog = os.path.join(tmp, "e.jsonl")
        base = baseline_genome(FORMAL_ROSTER)
        res = trickle(genome_path=path, cap=5.0, real=False, battery=["and3"],
                      inner_cycles=2, out_dir=os.path.join(tmp, "runs"),
                      evolve_log=elog, quiet=True, propose_mutation=_hacking_source(name))
        # rejected, not accepted, genome untouched
        assert res["accepted"] is False
        assert res["decision"] == "reject_disallowed"
        saved = _read(path)
        assert saved["genome"] == base
        assert name not in saved.get("params", {})
        # the candidate was NEVER evaluated — the gate was not even reached (I3)
        rows = [json.loads(l) for l in open(elog) if l.strip()]
        assert not any(r["event"] == "eval" and r.get("phase") == "trickle_cand"
                       for r in rows)
        # ... and it is in the persistent audit, marked rejected, with a reason
        audit = saved["audit"]
        assert len(audit) == 1
        entry = audit[0]
        assert entry["decision"] == "reject_disallowed"
        assert "REWARD-HACK" in entry["reason"]
        assert entry["mutation"]["name"] == name
        assert entry["when"] == 0          # rotation index = "when"


def test_evolve_blocks_reward_hack_and_audits():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.json")
        res = evolve(steps=2, cap=5.0, real=False, battery=["and3"], inner_cycles=3,
                     out_dir=os.path.join(tmp, "runs"),
                     evolve_log=os.path.join(tmp, "e.jsonl"), quiet=True,
                     genome_path=path, propose_mutation=_hacking_source("spend_cap_usd"))
        assert res["accepted"] == 0
        audit = res["audit"]
        assert audit and all(a["decision"] == "reject_disallowed" for a in audit)
        assert all("REWARD-HACK" in a["reason"] for a in audit)
        # persisted genome unchanged from baseline
        assert _read(path)["genome"] == baseline_genome(FORMAL_ROSTER)


# --------------------------------------- benign mutation only persists post-gate
def test_benign_flavor_persists_only_after_passing_gate(monkeypatch):
    """A vetted, allowed flavor mutation must STILL re-pass the Oracle gate (I4)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.json")
        base = baseline_genome(FORMAL_ROSTER)
        # mock is flavor-blind => the gate rejects => nothing persists
        res = trickle(genome_path=path, cap=5.0, real=False, battery=["and3"],
                      inner_cycles=2, out_dir=os.path.join(tmp, "runs"),
                      evolve_log=os.path.join(tmp, "e.jsonl"), quiet=True)
        assert res["accepted"] is False and res["decision"] == "reject"
        assert _read(path)["genome"] == base
        # now FORCE the gate to pass: the same benign mutation must now persist + audit
        monkeypatch.setattr(ev, "is_improvement", lambda new, old: True)
        res2 = trickle(genome_path=path, cap=5.0, real=False, battery=["and3"],
                       inner_cycles=2, out_dir=os.path.join(tmp, "runs"),
                       evolve_log=os.path.join(tmp, "e.jsonl"), quiet=True)
        assert res2["accepted"] is True and res2["decision"] == "ACCEPT"
        saved = _read(path)
        role = res2["role"]
        assert saved["genome"][role] != base[role]
        accepts = [a for a in saved["audit"] if a["decision"] == "ACCEPT"]
        assert len(accepts) == 1 and accepts[0]["role"] == role


# ---------------------------------------- audit records BOTH accept and reject
def test_audit_accumulates_accepts_and_rejects_across_invocations():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.json")
        kw = dict(genome_path=path, cap=5.0, real=False, battery=["and3", "majority3"],
                  inner_cycles=2, out_dir=os.path.join(tmp, "runs"),
                  evolve_log=os.path.join(tmp, "e.jsonl"), quiet=True)
        trickle(**kw)                                           # reject (flavor-blind)
        trickle(**kw, propose_mutation=_hacking_source("score"))  # reject_disallowed
        audit = _read(path)["audit"]
        decisions = [a["decision"] for a in audit]
        assert "reject" in decisions and "reject_disallowed" in decisions
        # every entry carries what / when / why
        assert all({"mutation", "when", "reason", "decision"} <= set(a) for a in audit)


# ---------------------------------------------- deterministic save/load round-trip
def test_genome_params_audit_round_trip_is_deterministic():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.json")
        genome = {"constructor": "C", "minimizer": "M", "generalizer": "G"}
        params = {"k_peers": 4, "survivor_frac": 0.5}
        audit = [{"when": 0, "decision": "reject_disallowed",
                  "mutation": {"kind": "param", "name": "cap", "value": 9},
                  "reason": "REWARD-HACK: ..."},
                 {"when": 1, "decision": "ACCEPT",
                  "mutation": {"kind": "flavor", "role": "constructor", "value": "C2"},
                  "reason": "verifier-gated improvement"}]
        save_genome(path, genome, 2, [], ["and3"], audit=audit, params=params)
        a = load_genome(path, FORMAL_ROSTER)
        # round-trip 2x must be byte-identical
        save_genome(path, a["genome"], a["rotation_index"], a["history"], a["battery"],
                    audit=a["audit"], params=a["params"])
        b = load_genome(path, FORMAL_ROSTER)
        assert a == b
        assert b["params"] == params
        assert b["audit"] == audit


def test_load_drops_forbidden_param_from_tampered_file():
    """A hand-tampered genome.json with a forbidden knob must be sanitized on load."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.json")
        with open(path, "w") as f:
            json.dump({"genome": {}, "rotation_index": 0, "history": [], "battery": None,
                       "params": {"k_peers": 4, "spend_cap_usd": 9999.0},
                       "audit": []}, f)
        loaded = load_genome(path, FORMAL_ROSTER)
        assert loaded["params"] == {"k_peers": 4}        # forbidden knob dropped
        assert "spend_cap_usd" not in loaded["params"]


def test_allowlisted_param_actually_reaches_the_colony():
    """A persisted post-gate param (k_peers) must take effect in the inner colony."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.json")
        save_genome(path, baseline_genome(FORMAL_ROSTER), 0, [], ["and3"],
                    params={"k_peers": 1})
        # a trickle run loads params and applies them; the run logs reflect k_peers=1
        runs = os.path.join(tmp, "runs")
        trickle(genome_path=path, cap=5.0, real=False, battery=["and3"],
                inner_cycles=2, out_dir=runs,
                evolve_log=os.path.join(tmp, "e.jsonl"), quiet=True)
        # the inner colony's start event records k_peers — confirm the override applied
        import glob
        logs = glob.glob(os.path.join(runs, "*trickle_cur*.jsonl"))
        assert logs
        rows = [json.loads(l) for l in open(logs[0]) if l.strip()]
        start = next(r for r in rows if r["event"] == "start")
        assert start["k_peers"] == 1


def test_evolve_threads_proposer_max_tokens_to_inner_colonies(monkeypatch):
    """evolve() must pass proposer_max_tokens through to every inner colony Config
    (mirrors trickle's plumbing) — captured via a wrapped Colony."""
    seen = []
    real_colony = ev.Colony

    class _Spy(real_colony):
        def __init__(self, cfg, oracle_name="rotary", cost_tracker=None):
            seen.append(cfg.proposer_max_tokens)
            super().__init__(cfg, oracle_name, cost_tracker=cost_tracker)

    monkeypatch.setattr(ev, "Colony", _Spy)
    with tempfile.TemporaryDirectory() as tmp:
        evolve(steps=1, cap=5.0, real=False, battery=["and3"], inner_cycles=2,
               out_dir=os.path.join(tmp, "runs"),
               evolve_log=os.path.join(tmp, "e.jsonl"), quiet=True,
               proposer_max_tokens=2000)
    assert seen and set(seen) == {2000}          # every inner colony got the budget
