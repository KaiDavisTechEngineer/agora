"""
Trickle-mode tests — cheap, accumulating, verifier-gated self-improvement.

  - genome.json round-trips (genome + rotation index + history)
  - one trickle invocation does EXACTLY one attempt and respects the cap
  - a rejected trickle leaves the persisted genome unchanged
  - an accepted trickle persists the mutated genome + a history entry
  - rotation advances and selects the next target across invocations
"""
import json, os, tempfile
import pytest

import agora.evolve as ev
from agora.evolve import (trickle, load_genome, save_genome, baseline_genome)
from agora.cost import CostTracker
from agora.roles import FORMAL_ROSTER


def _read(path):
    with open(path) as f:
        return json.load(f)


# --------------------------------------------------------------- persistence
def test_genome_json_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "genome.json")
        genome = {"constructor": "C flavor", "minimizer": "M flavor", "generalizer": "G flavor"}
        history = [{"target": "parity3", "role": "minimizer",
                    "before_fitness": [0, 50.0], "after_fitness": [1, 109.0]}]
        save_genome(path, genome, rotation_index=2, history=history, battery=["a", "b"])

        loaded = load_genome(path, FORMAL_ROSTER)
        assert loaded["genome"] == genome
        assert loaded["rotation_index"] == 2
        assert loaded["history"] == history
        assert loaded["battery"] == ["a", "b"]


def test_load_genome_defaults_to_baseline_when_absent():
    with tempfile.TemporaryDirectory() as tmp:
        loaded = load_genome(os.path.join(tmp, "nope.json"), FORMAL_ROSTER)
        assert loaded["genome"] == baseline_genome(FORMAL_ROSTER)
        assert loaded["rotation_index"] == 0 and loaded["history"] == []


def test_load_genome_keeps_only_current_roster_proposers():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.json")
        # a stale key (no longer a role) must be dropped on load
        save_genome(path, {"constructor": "evolved C", "ZOMBIE": "junk"},
                    rotation_index=0, history=[], battery=None)
        loaded = load_genome(path, FORMAL_ROSTER)
        assert loaded["genome"]["constructor"] == "evolved C"   # kept + applied
        assert "ZOMBIE" not in loaded["genome"]                 # stale role dropped


# ----------------------------------------------------- exactly one attempt
def test_trickle_does_exactly_one_attempt():
    with tempfile.TemporaryDirectory() as tmp:
        elog = os.path.join(tmp, "e.jsonl")
        res = trickle(genome_path=os.path.join(tmp, "g.json"), cap=5.0, real=False,
                      battery=["majority3", "parity3"], inner_cycles=2,
                      out_dir=os.path.join(tmp, "runs"), evolve_log=elog, quiet=True)
        rows = [json.loads(l) for l in open(elog) if l.strip()]
        evals = [r for r in rows if r["event"] == "eval"]
        muts = [r for r in rows if r["event"] == "mutation"]
        # exactly one current eval + one candidate eval + one mutation = one attempt
        assert sum(1 for e in evals if e["phase"] == "trickle_cur") == 1
        assert sum(1 for e in evals if e["phase"] == "trickle_cand") == 1
        assert len(muts) == 1
        assert res["target"] == "majority3"   # rot 0 -> first target


def test_trickle_respects_cap():
    with tempfile.TemporaryDirectory() as tmp:
        shared = CostTracker(cap_usd=0.0005)   # trips on the very first model call
        res = trickle(genome_path=os.path.join(tmp, "g.json"), cap=0.0005, real=False,
                      battery=["majority3", "parity3"], inner_cycles=3,
                      out_dir=os.path.join(tmp, "runs"),
                      evolve_log=os.path.join(tmp, "e.jsonl"), quiet=True, cost=shared)
        assert res["halted"] is True
        assert res["accepted"] is False
        assert shared.usd >= 0.0005            # the shared budget really capped it


# ----------------------------------------------------- accept / reject persist
def test_trickle_reject_leaves_genome_unchanged():
    """Mock is flavor-blind => the gate rejects => persisted genome stays baseline."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.json")
        res = trickle(genome_path=path, cap=5.0, real=False, battery=["and3"],
                      inner_cycles=2, out_dir=os.path.join(tmp, "runs"),
                      evolve_log=os.path.join(tmp, "e.jsonl"), quiet=True)
        assert res["accepted"] is False
        saved = _read(path)
        assert saved["genome"] == baseline_genome(FORMAL_ROSTER)   # unchanged
        assert saved["history"] == []
        assert saved["rotation_index"] == 1                        # rotation advanced


def test_trickle_accept_persists(monkeypatch):
    """Force the gate to accept and confirm the mutated genome + history persist."""
    monkeypatch.setattr(ev, "is_improvement", lambda new, old: True)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.json")
        base = baseline_genome(FORMAL_ROSTER)
        res = trickle(genome_path=path, cap=5.0, real=False, battery=["and3"],
                      inner_cycles=2, out_dir=os.path.join(tmp, "runs"),
                      evolve_log=os.path.join(tmp, "e.jsonl"), quiet=True)
        assert res["accepted"] is True
        saved = _read(path)
        role = res["role"]
        assert saved["genome"][role] != base[role]      # mutated flavor persisted
        assert len(saved["history"]) == 1               # the accepted change is recorded
        assert saved["history"][0]["role"] == role


def test_trickle_rotates_target_across_invocations():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "g.json")
        kw = dict(genome_path=path, cap=5.0, real=False, battery=["majority3", "parity3"],
                  inner_cycles=2, out_dir=os.path.join(tmp, "runs"),
                  evolve_log=os.path.join(tmp, "e.jsonl"), quiet=True)
        r0 = trickle(**kw)
        r1 = trickle(**kw)   # second invocation reads the advanced rotation index
        assert r0["target"] == "majority3"
        assert r1["target"] == "parity3"
