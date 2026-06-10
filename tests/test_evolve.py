"""
Frontier #6 tests — verifier-gated self-improvement.

  - the accept/reject GATE is strict and verified-count-first
  - an end-to-end MOCK meta-loop accepts NOTHING (flavor-blind => no improvement)
  - the SHARED global budget halts the battery mid-way
"""
import json, os, tempfile
import pytest

from agora.cost import CostTracker
from agora.evolve import evolve, is_improvement, baseline_genome
from agora.roles import FORMAL_ROSTER, kind_of, PROPOSER


def _load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


# ------------------------------------------------------------------ the gate
def test_gate_strict_and_verified_first():
    # more verified wins beats more score
    assert is_improvement((1, 50.0), (0, 999.0)) is True
    # equal verified -> higher score wins
    assert is_improvement((0, 100.0), (0, 99.0)) is True
    # NOT strict -> rejected
    assert is_improvement((0, 99.0), (0, 99.0)) is False
    # lower score -> rejected
    assert is_improvement((0, 98.0), (0, 99.0)) is False
    # fewer verified -> rejected even with way more score
    assert is_improvement((1, 10.0), (2, 0.0)) is False


def test_baseline_genome_is_only_proposers():
    g = baseline_genome(FORMAL_ROSTER)
    assert set(g) == {r for r in FORMAL_ROSTER if kind_of(r) == PROPOSER}
    assert all(isinstance(v, str) and v for v in g.values())


# -------------------------------------------------------- mock end-to-end
def test_mock_meta_loop_accepts_nothing():
    """Mock agents are flavor-blind, so the gate must reject every mutation."""
    with tempfile.TemporaryDirectory() as tmp:
        elog = os.path.join(tmp, "evolve_log.jsonl")
        res = evolve(steps=3, cap=5.00, real=False,
                     battery=["majority3", "mux"], inner_cycles=4,
                     out_dir=os.path.join(tmp, "runs"), evolve_log=elog,
                     quiet=True)
        assert res["accepted"] == 0                 # the gate rejected non-improvements
        assert res["verified_gain"] == 0
        assert res["best_fitness"] == res["baseline_fitness"]
        rows = _load(elog)
        kinds = {r["event"] for r in rows}
        assert {"baseline_genome", "eval", "mutation", "fitness", "decision", "final"} <= kinds
        # every decision in mock is a REJECT
        assert all(r["decision"] == "REJECT"
                   for r in rows if r["event"] == "decision")


# ---------------------------------------------------- global budget halting
def test_shared_cap_halts_mid_battery():
    """ONE shared CostTracker is the global budget; a low cap halts the battery
    before all targets are evaluated."""
    with tempfile.TemporaryDirectory() as tmp:
        elog = os.path.join(tmp, "evolve_log.jsonl")
        shared = CostTracker(cap_usd=0.02)          # far below a full 3-target battery
        res = evolve(steps=4, cap=0.02, real=False,
                     battery=["majority3", "mux", "parity3"], inner_cycles=6,
                     out_dir=os.path.join(tmp, "runs"), evolve_log=elog,
                     quiet=True, cost=shared)
        assert res["halted"] is True
        # the shared tracker really metered the spend and tripped its cap
        assert shared.usd >= 0.02
        # fewer than the full battery were evaluated (halted MID-battery)
        evals = [r for r in _load(elog) if r["event"] == "eval"]
        assert 0 < len(evals) < 3


def test_shared_cost_tracker_is_truly_global():
    """A pre-spent shared tracker carries its balance into the meta-loop."""
    with tempfile.TemporaryDirectory() as tmp:
        shared = CostTracker(cap_usd=0.05)
        shared.charge("claude-sonnet-4-6", 5000, 1000)   # pre-spend on "other work"
        pre = shared.usd
        evolve(steps=1, cap=0.05, real=False, battery=["majority3"],
               inner_cycles=3, out_dir=os.path.join(tmp, "runs"),
               evolve_log=os.path.join(tmp, "e.jsonl"), quiet=True, cost=shared)
        assert shared.usd > pre        # the meta-loop added to the SAME budget
