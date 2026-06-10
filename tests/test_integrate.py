"""
Phase 5 — the integrated P2->P1->P3->P4 flow, end-to-end.

ONE big, fully-mocked, $0, fixed-seed test asserts every cross-frontier invariant:
  (a) gate integrity      — a known-wrong candidate is Oracle-rejected, never persisted
  (b) spend cap           — total spend <= cap, and a run that would exceed it halts
                            BEFORE the offending call (not after)
  (c) per-role routing    — each role invoked exactly its configured model; each call's
                            cost is attributed to the correct model
  (d) bounded self-improve— a benign mutation persists only after re-passing the gate;
                            a reward-hack (gate/cap/score) is rejected + audited
  (e) genome persistence  — save/load round-trips deterministically; a resumed run
                            reproduces the same strategy params
  (f) explanatory trace   — names the critiques that moved Elo + the contributing
                            role/model, with a stable shape on the fixed seed
  (g) joint invariants    — gate not bypassed AND cap respected AND every persisted
                            mutation gate-passed, within the same run
  (h) determinism         — fixed seed + mocked API => byte-stable end-to-end result

A small smoke test for the CLI surface is at the bottom.
"""
import json, os, glob, tempfile
import pytest

import agora.evolve as ev
from agora.integrate import integrated_run
from agora.evolve import baseline_genome, STRATEGY_PARAM_ALLOWLIST
from agora.oracles import FormulaSynthesisOracle, default_target
from agora.roles import FORMAL_ROSTER, kind_of, PROPOSER

SEED = 7
CAP = 5.0
TARGET = default_target(2)                       # parity4 (k=4) — a hard target (P1)
MODELS = {"proposer": "claude-fable-5",          # P2: three distinct, priced models
          "critic": "claude-haiku-4-5-20251001",
          "validator": "claude-sonnet-4-6"}


def _read(path):
    with open(path) as f:
        return json.load(f)


def _rows(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def _run(tmp, *, cap=CAP, genome="g.json", propose_mutation=None, seed=SEED):
    """One integrated run into a fresh workspace under `tmp`."""
    return integrated_run(
        difficulty=2, cap=cap, real=False, role_models=MODELS,
        genome_path=os.path.join(tmp, genome), inner_cycles=4,
        out_dir=os.path.join(tmp, "runs"), evolve_log=os.path.join(tmp, "e.jsonl"),
        seed=seed, quiet=True, propose_mutation=propose_mutation)


def _hack(name):
    def _src(role, flavor, step, real, cost, gen_model):
        return {"kind": "param", "name": name, "value": 10_000}
    return _src


def _param_mutation(name, value):
    def _src(role, flavor, step, real, cost, gen_model):
        return {"kind": "param", "name": name, "value": value}
    return _src


def _canon(out):
    """Path-independent projection of an integrated result (for determinism check)."""
    tk = out["trickle"]
    return {
        "target": out["target"], "role_models": out["role_models"],
        "decision": tk["decision"], "accepted": tk["accepted"],
        "cur_fitness": tk["cur_fitness"], "cand_fitness": tk["cand_fitness"],
        "genome": tk["genome"], "params": tk["params"],
        "audit_decisions": [a["decision"] for a in tk["audit"]],
        "by_model_calls": {m: r["calls"] for m, r in out["cost"]["by_model"].items()},
        "explanatory": out["interpret"]["explanatory"],
    }


def test_integrated_end_to_end_all_invariants():
    with tempfile.TemporaryDirectory() as tmp:
        main = _run(tmp)                                  # the headline integrated run
        gpath = os.path.join(tmp, "g.json")
        saved = _read(gpath)
        elog_rows = _rows(os.path.join(tmp, "e.jsonl"))

        # ---- (a) GATE INTEGRITY -------------------------------------------------
        oracle = FormulaSynthesisOracle(TARGET)
        wrong = {"var": "a"}                              # a deliberately wrong candidate
        assert oracle.verify(wrong) is False              # Oracle rejects it ...
        assert oracle.verify(oracle._ref) is True         # ... and accepts the truth
        # across the whole run nothing wrong was ever certified as verified
        assert all(r.get("verified") is not True
                   for r in elog_rows if r.get("event") == "eval")
        # nothing wrong (or anything) persisted as an improvement: genome == baseline
        assert saved["genome"] == baseline_genome(FORMAL_ROSTER)
        assert main["trickle"]["accepted"] is False

        # ---- (c) PER-ROLE ROUTING + COST ATTRIBUTION ----------------------------
        bm = main["cost"]["by_model"]
        assert set(bm) == set(MODELS.values())            # only the configured models billed
        for m in MODELS.values():
            assert bm[m]["calls"] > 0                      # each role-kind actually ran
        # per-model totals reconcile to the single global total
        assert round(sum(r["usd"] for r in bm.values()), 6) == round(main["cost"]["usd"], 6)
        # each role invoked EXACTLY its configured model (checked at the event level)
        cur_log = glob.glob(os.path.join(tmp, "runs", "*trickle_cur*.jsonl"))[0]
        rows = _rows(cur_log)
        assert {r["model"] for r in rows if r["event"] == "proposal"} == {MODELS["proposer"]}
        assert {r["model"] for r in rows if r["event"] == "critique"} == {MODELS["critic"]}
        assert {r["model"] for r in rows if r["event"] == "audit"} == {MODELS["validator"]}

        # ---- (f) EXPLANATORY TRACE (stable shape on the fixed seed) -------------
        ex = main["interpret"]["explanatory"]
        assert set(ex) == {"elo_by_role", "critic_credit", "decisive_critiques",
                           "win_explanations"}
        proposers = {r for r in FORMAL_ROSTER if kind_of(r) == PROPOSER}
        assert set(ex["elo_by_role"]) == proposers
        # the proposer Elo is attributed to the proposer MODEL (P2 x P4 cross-frontier)
        assert all(d["model"] == MODELS["proposer"] for d in ex["elo_by_role"].values())
        # critic credit names a contributing critic role on the critic MODEL
        assert ex["critic_credit"]
        assert any(d["model"] == MODELS["critic"] for d in ex["critic_credit"].values())
        assert ex["win_explanations"]

        # ---- (g) JOINT INVARIANT BLOCK (within this same run) -------------------
        assert main["cost"]["usd"] <= CAP                                  # cap respected
        accepts = [a for a in saved["audit"] if a["decision"] == "ACCEPT"]
        assert len(accepts) == len(saved["history"])      # every persisted accept is gate-logged
        assert set(saved["params"]).issubset(STRATEGY_PARAM_ALLOWLIST)     # only post-gate knobs
        # gate not bypassed: no eval certified a candidate as verified in mock
        assert not any(r.get("verified") is True
                       for r in elog_rows if r.get("event") == "eval")

    # ---- (b) SPEND CAP: halt BEFORE the offending call ------------------------
    with tempfile.TemporaryDirectory() as tmp:
        tiny = 0.05
        out = _run(tmp, cap=tiny)
        tk = out["trickle"]
        assert tk["halted"] is True
        # the pre-call guard refuses the crossing call, so spend never reaches the cap
        assert out["cost"]["usd"] < tiny
        # still a single global budget across all per-role models
        bm = out["cost"]["by_model"]
        assert round(sum(r["usd"] for r in bm.values()), 6) == round(out["cost"]["usd"], 6)

    # ---- (d) BOUNDED SELF-IMPROVEMENT: reward-hack rejected + audited ---------
    with tempfile.TemporaryDirectory() as tmp:
        out = _run(tmp, propose_mutation=_hack("spend_cap_usd"))
        tk = out["trickle"]
        assert tk["accepted"] is False and tk["decision"] == "reject_disallowed"
        hack_audit = [a for a in tk["audit"] if a["decision"] == "reject_disallowed"]
        assert hack_audit and "REWARD-HACK" in hack_audit[0]["reason"]
        # the candidate was never even evaluated — the gate was not reached
        assert not any(r.get("phase") == "trickle_cand"
                       for r in _rows(os.path.join(tmp, "e.jsonl")) if r.get("event") == "eval")
        assert _read(os.path.join(tmp, "g.json"))["genome"] == baseline_genome(FORMAL_ROSTER)

    # ---- (d) BOUNDED SELF-IMPROVEMENT: benign change persists only post-gate --
    with tempfile.TemporaryDirectory() as tmp:
        gpath = os.path.join(tmp, "g.json")
        base = baseline_genome(FORMAL_ROSTER)
        # default (benign) flavor mutation under the real gate => mock rejects => no change
        out1 = _run(tmp)
        assert out1["trickle"]["accepted"] is False
        assert _read(gpath)["genome"] == base
        # now FORCE the gate to pass: the SAME benign mutation must now persist
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(ev, "is_improvement", lambda new, old: True)
            out2 = _run(tmp)                              # resumes the same genome_path
        assert out2["trickle"]["accepted"] is True and out2["trickle"]["decision"] == "ACCEPT"
        saved2 = _read(gpath)
        assert [a for a in saved2["audit"] if a["decision"] == "ACCEPT"]     # gate-pass audited

    # ---- (e) GENOME PERSISTENCE + RESUME reproduces strategy params ----------
    with tempfile.TemporaryDirectory() as tmp:
        gpath = os.path.join(tmp, "g.json")
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(ev, "is_improvement", lambda new, old: True)
            _run(tmp, propose_mutation=_param_mutation("k_peers", 2))
        saved = _read(gpath)
        assert saved["params"].get("k_peers") == 2        # post-gate param persisted
        # deterministic save/load round-trip
        a = ev.load_genome(gpath, FORMAL_ROSTER)
        ev.save_genome(gpath, a["genome"], a["rotation_index"], a["history"],
                       a["battery"], audit=a["audit"], params=a["params"])
        b = ev.load_genome(gpath, FORMAL_ROSTER)
        assert a == b and b["params"]["k_peers"] == 2
        # a resumed run loads the persisted param and the inner colony USES it
        out_resume = _run(tmp)                            # same genome_path -> loads k_peers=2
        cur_log = glob.glob(os.path.join(tmp, "runs", "*trickle_cur*.jsonl"))[0]
        start = next(r for r in _rows(cur_log) if r["event"] == "start")
        assert start["k_peers"] == 2

    # ---- (h) DETERMINISM: same seed => byte-stable end-to-end result ----------
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        c1 = _canon(_run(t1))
        c2 = _canon(_run(t2))
        assert json.dumps(c1, sort_keys=True) == json.dumps(c2, sort_keys=True)


def test_integrate_cli_smoke():
    """The integrate entrypoint runs end-to-end from argv, mocked, $0."""
    from agora.integrate import main
    with tempfile.TemporaryDirectory() as tmp:
        main(["--difficulty", "2", "--proposer-model", "claude-fable-5",
              "--cycles", "3", "--genome", os.path.join(tmp, "g.json"),
              "--out-dir", os.path.join(tmp, "runs"),
              "--evolve-log", os.path.join(tmp, "e.jsonl")])
        assert os.path.exists(os.path.join(tmp, "g.json"))
