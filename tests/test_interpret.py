"""
Frontier #5 tests — behavioral interpretability.

  - analyze() parses real (mock-generated) logs and returns a non-empty attribution
  - winning_role attributes the top formula to its author
  - verified wins are attributed to the authoring role
  - the flavor diff correlates an instruction change with a verified-count rise
"""
import json, os, tempfile

from agora.evolve import evolve
from agora.interpret import (analyze, render, winning_role,
                             verified_wins_by_role, flavor_evolution)


def test_analyze_on_mock_runs_is_nonempty_and_safe():
    with tempfile.TemporaryDirectory() as tmp:
        runs = os.path.join(tmp, "runs")
        elog = os.path.join(tmp, "evolve_log.jsonl")
        evolve(steps=2, cap=5.0, real=False, battery=["majority3", "mux"],
               inner_cycles=4, out_dir=runs, evolve_log=elog, quiet=True)

        report = analyze(run_dir=runs, evolve_log=elog)
        assert report["n_run_logs"] > 0
        # revision acceptance is always observable from mock runs
        acc = report["revision_acceptance_by_role"]
        assert acc and all(0.0 <= v["rate"] <= 1.0 for v in acc.values())
        # critique->revision section parsed
        assert report["critique_to_revision"]["n_accepted_revisions"] >= 0
        # flavor diff lists the proposer roles
        assert report["flavor_evolution"]["diff"]
        # rendering must not crash and must produce text
        text = render(report)
        assert "INTERPRETABILITY" in text and len(text) > 100


def test_winning_role_picks_top_scorer():
    rows = [
        {"event": "proposal", "cycle": 1, "agent": 0, "role": "constructor", "score": 75.0},
        {"event": "proposal", "cycle": 1, "agent": 1, "role": "minimizer", "score": 50.0},
        {"event": "revision", "cycle": 1, "agent": 1, "role": "minimizer",
         "after_score": 119.0, "accepted": True},
        {"event": "revision", "cycle": 1, "agent": 0, "role": "constructor",
         "after_score": 200.0, "accepted": False},   # rejected => must NOT count
    ]
    role, score = winning_role(rows)
    assert role == "minimizer" and score == 119.0


def test_verified_wins_attributed_to_author():
    with tempfile.TemporaryDirectory() as tmp:
        run_log = os.path.join(tmp, "s1_candidate_and3.jsonl")
        with open(run_log, "w") as f:
            f.write(json.dumps({"event": "proposal", "cycle": 1, "agent": 0,
                                "role": "constructor", "score": 119.0}) + "\n")
        evolve_rows = [
            {"event": "eval", "step": 1, "phase": "candidate", "target": "and3",
             "verified": True, "score": 119.0, "log": run_log},
            {"event": "eval", "step": 1, "phase": "candidate", "target": "mux",
             "verified": False, "score": 80.0, "log": "missing.jsonl"},
        ]
        wins, detail = verified_wins_by_role(evolve_rows, tmp)
        assert wins["constructor"] == 1
        assert len(detail) == 1 and detail[0]["target"] == "and3"


def test_flavor_diff_correlates_instruction_change_with_verified_gain():
    # a synthetic evolve log where one ACCEPT raises verified-count from 1 -> 2
    evolve_rows = [
        {"event": "baseline_genome", "genome": {"constructor": "base C", "minimizer": "base M"}},
        {"event": "fitness", "phase": "baseline", "verified_count": 1, "total_score": 200},
        {"event": "mutation", "step": 1, "role": "constructor",
         "before": "base C", "after": "be exactly correct and minimal"},
        {"event": "fitness", "step": 1, "phase": "candidate", "verified_count": 2, "total_score": 250},
        {"event": "decision", "step": 1, "decision": "ACCEPT", "role": "constructor",
         "cand_fitness": [2, 250]},
        {"event": "final", "genome": {"constructor": "be exactly correct and minimal",
                                      "minimizer": "base M"}},
    ]
    fe = flavor_evolution(evolve_rows)
    assert fe["diff"]["constructor"]["changed"] is True
    assert fe["diff"]["minimizer"]["changed"] is False
    corr = fe["correlated_with_verified_gain"]
    assert len(corr) == 1
    assert corr[0]["role"] == "constructor" and corr[0]["verified_delta"] == 1
    assert corr[0]["after"] == "be exactly correct and minimal"
