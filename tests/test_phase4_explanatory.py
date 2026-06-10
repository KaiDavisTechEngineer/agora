"""
Phase 4 — explanatory interpretability (#5).

  - the colony logs per-cycle Elo deltas and a model on every candidate event
  - explain_elo_attribution names the critiques that moved Elo and the role/model
    that contributed (proposer net-Elo by model; critic credit by model)
  - the explanatory output has a STABLE, asserted shape on a fixed seed, and is
    byte-stable across two independent same-seed evolve runs (determinism)
"""
import json, os, tempfile
import pytest

from agora.evolve import evolve
from agora.interpret import (analyze, render, explain_elo_attribution,
                             win_explanations, load_run_logs)
from agora.roles import FORMAL_ROSTER, kind_of, PROPOSER


def _run(tmp, seed=7):
    runs = os.path.join(tmp, "runs")
    elog = os.path.join(tmp, "e.jsonl")
    evolve(steps=2, cap=5.0, real=False, battery=["majority3", "mux"], inner_cycles=4,
           out_dir=runs, evolve_log=elog, quiet=True, seed=seed)
    return analyze(run_dir=runs, evolve_log=elog)


# --------------------------------------------------- colony emits the new signals
def test_colony_logs_elo_and_model_events():
    with tempfile.TemporaryDirectory() as tmp:
        from agora.config import Config
        from agora.colony import Colony
        cfg = Config(use_mock=True, n_cycles=3, seed=3, patience=99, n_agents=6,
                     roster=FORMAL_ROSTER, oracle_kwargs={"target": "majority3"},
                     state_file=os.path.join(tmp, "s.json"),
                     log_file=os.path.join(tmp, "l.jsonl"),
                     curve_file=os.path.join(tmp, "c.csv"))
        Colony(cfg, "formula").run()
        rows = [json.loads(l) for l in open(cfg.log_file) if l.strip()]
        elos = [r for r in rows if r["event"] == "elo"]
        assert elos, "no elo events logged"
        e = elos[0]
        assert {"agent", "role", "model", "delta", "elo_before", "elo_after", "rank"} <= e.keys()
        # candidate events now carry the model that did the work
        prop = next(r for r in rows if r["event"] == "proposal")
        crit = next(r for r in rows if r["event"] == "critique")
        assert prop["model"] is not None and crit["model"] is not None


# ------------------------------------------------------- explanatory shape
def test_explanatory_shape_is_stable_on_fixed_seed():
    with tempfile.TemporaryDirectory() as tmp:
        rep = _run(tmp, seed=7)
        assert "explanatory" in rep
        ex = rep["explanatory"]
        assert set(ex) == {"elo_by_role", "critic_credit", "decisive_critiques",
                           "win_explanations"}

        # net Elo is attributed to every PROPOSER role, each with a model + numeric net
        proposers = {r for r in FORMAL_ROSTER if kind_of(r) == PROPOSER}
        assert set(ex["elo_by_role"]) == proposers
        for role, d in ex["elo_by_role"].items():
            assert set(d) == {"model", "net_elo", "appearances"}
            assert isinstance(d["net_elo"], float) and isinstance(d["model"], str)
            assert d["appearances"] > 0
        # Elo is zero-sum among proposers each cycle, so the net over all roles is ~0
        # (small drift only from per-event rounding to 0.1)
        assert abs(sum(d["net_elo"] for d in ex["elo_by_role"].values())) < 5.0

        # critic credit names contributing roles, each with a model + counts
        assert ex["critic_credit"]
        for role, d in ex["critic_credit"].items():
            assert set(d) == {"model", "elo_credited", "critiques",
                              "decisive_revisions"}
            assert d["critiques"] > 0

        # decisive critiques (if any) have the full causal record
        assert isinstance(ex["decisive_critiques"], list)
        for c in ex["decisive_critiques"]:
            assert {"run", "cycle", "winner_role", "winner_model", "critic_role",
                    "critic_model", "elo_delta", "revision_gain", "critique"} <= set(c)
            assert c["elo_delta"] > 0 and c["revision_gain"] > 0

        # per-run win explanations name the Elo-winner (role+model) and score-leader
        assert ex["win_explanations"]
        for w in ex["win_explanations"]:
            assert {"run", "top_elo_role", "top_elo_model", "net_elo",
                    "top_score_role", "top_score"} <= set(w)


def test_explanatory_is_deterministic_across_same_seed_runs():
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        ex1 = _run(t1, seed=7)["explanatory"]
        ex2 = _run(t2, seed=7)["explanatory"]
        # run logs live under different tmp dirs but are keyed by basename, so the
        # explanatory attribution must be byte-identical for the same fixed seed
        assert ex1 == ex2


def test_decisive_critiques_name_the_mover_and_the_moved():
    """The headline requirement: the output names the critiques that moved Elo and
    the contributing role/model."""
    with tempfile.TemporaryDirectory() as tmp:
        ex = _run(tmp, seed=7)["explanatory"]
        # at least one decisive critique on this seed (mux gets accepted, score-raising
        # revisions that flip the ranking)
        assert ex["decisive_critiques"], "expected at least one decisive critique"
        c = ex["decisive_critiques"][0]
        # the mover (a critic role + its model) and the moved (a proposer + its model)
        assert c["critic_role"] and c["critic_model"]
        assert c["winner_role"] in {r for r in FORMAL_ROSTER if kind_of(r) == PROPOSER}


def test_render_includes_explanatory_section():
    with tempfile.TemporaryDirectory() as tmp:
        text = render(_run(tmp, seed=7))
        assert "EXPLANATORY" in text
        assert "net Elo by proposer role" in text
        assert "critic credit" in text


def test_explanatory_handles_empty_logs_gracefully():
    with tempfile.TemporaryDirectory() as tmp:
        logs = load_run_logs(tmp)            # no logs
        ex = explain_elo_attribution(logs)
        assert ex == {"elo_by_role": {}, "critic_credit": {}, "decisive_critiques": []}
        assert win_explanations(logs) == []
