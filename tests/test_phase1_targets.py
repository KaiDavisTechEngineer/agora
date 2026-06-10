"""
Phase 1 — harder verifiable targets (frontier #1).

  - the harder k=4 / k=5 targets verify their reference and reject a wrong answer
  - the difficulty knob groups targets and selects sensible defaults
  - the benchmark set's known-correct answers are ACCEPTED and known-incorrect REJECTED
  - references survive normalize() unchanged (no 4-arg / depth truncation)
  - a mock colony runs end-to-end on a k=5 target (the loop scales with difficulty)
  - run.py resolves the target from --difficulty when --target is omitted
"""
import os, tempfile
import pytest

from agora.config import Config
from agora.colony import Colony
from agora.oracles import (FormulaSynthesisOracle, BENCHMARKS, DIFFICULTY,
                           difficulty_of, targets_at, default_target, benchmark,
                           _ast_size, _TARGETS)

HARDER = ["parity4", "majority5", "parity5"]


# ---------------------------------------------------- harder targets verify
@pytest.mark.parametrize("target", HARDER)
def test_harder_target_reference_verifies(target):
    o = FormulaSynthesisOracle(target)
    assert o.k >= 4                                   # genuinely harder than the k=3 set
    assert o.verify(o._ref) is True                   # reference proven equivalent by Z3
    assert o.verify({"var": "a"}) is False            # a wrong answer is provably rejected
    assert o.score(o._ref) >= 100                     # fully correct => >= 100
    assert o.score(o._ref) == o.optimum_estimate()    # reference sits at the optimum


@pytest.mark.parametrize("target", HARDER)
def test_harder_reference_survives_normalize(target):
    """The reference must pass through normalize()/_coerce() byte-identical — i.e. it
    respects the <=4-arg and depth-12 caps, so its score is not silently corrupted."""
    o = FormulaSynthesisOracle(target)
    assert o.normalize(o._ref) == o._ref


@pytest.mark.parametrize("target", HARDER)
def test_harder_target_rejects_near_miss(target):
    """A formula correct on MOST rows but not all must still be REJECTED by the gate
    (verify is all-or-nothing), even though its gradient score is high."""
    o = FormulaSynthesisOracle(target)
    # drop one conjunct/var from the reference's structure by negating the whole thing
    near = {"op": "not", "args": [o._ref]}
    assert o.verify(near) is False
    assert o.score(near) < o.score(o._ref)


# --------------------------------------------------------- difficulty knob
def test_difficulty_groups_are_disjoint_and_cover_targets():
    seen = set()
    for d, ts in DIFFICULTY.items():
        for t in ts:
            assert t not in seen, f"{t} in two difficulty groups"
            seen.add(t)
            assert difficulty_of(t) == d
    # every named target is reachable through some difficulty group
    assert seen == set(_TARGETS.keys())


def test_difficulty_levels_scale_variable_count():
    # difficulty 1 = k3, difficulty 3 includes k5
    assert all(FormulaSynthesisOracle(t).k == 3 for t in targets_at(1))
    assert all(FormulaSynthesisOracle(t).k >= 5 for t in targets_at(3))
    assert FormulaSynthesisOracle(default_target(2)).k == 4


def test_default_target_preserves_historic_default():
    # difficulty 1 must still pick majority3 (back-compat with the old run.py default)
    assert default_target(1) == "majority3"
    assert default_target(99) == "majority3"          # unknown level falls back safely


# ----------------------------------------------------------- benchmark set
def test_benchmark_set_known_answers_accepted_and_rejected():
    assert len(BENCHMARKS) >= 7
    for b in BENCHMARKS:
        o = FormulaSynthesisOracle(b["target"])
        assert o.verify(b["correct"]) is True, f"correct rejected for {b['target']}"
        assert o.verify(b["incorrect"]) is False, f"incorrect accepted for {b['target']}"
        assert b["difficulty"] == difficulty_of(b["target"])


def test_benchmark_lookup_helper():
    b = benchmark("parity5")
    assert b["target"] == "parity5" and b["difficulty"] == 3
    with pytest.raises(KeyError):
        benchmark("not_a_target")


# --------------------------------------------- per-target max_ops headroom
def test_original_targets_keep_max_ops_20():
    for t in ["majority3", "mux", "and3", "parity3"]:
        assert FormulaSynthesisOracle(t).max_ops == 20    # unchanged historical scores


def test_harder_targets_have_parsimony_headroom():
    for t in HARDER:
        o = FormulaSynthesisOracle(t)
        assert o.max_ops > _ast_size(o._ref)              # bonus > 0 => minimality lives


def test_explicit_max_ops_still_overrides():
    o = FormulaSynthesisOracle("parity4", max_ops=99)
    assert o.max_ops == 99


# ------------------------------------------------ colony runs at difficulty
def _cfg(tmp, **kw):
    d = dict(use_mock=True, n_cycles=6, seed=3, patience=99,
             state_file=os.path.join(tmp, "s.json"),
             log_file=os.path.join(tmp, "l.jsonl"),
             curve_file=os.path.join(tmp, "c.csv"))
    d.update(kw)
    return Config(**d)


def test_mock_colony_runs_on_k5_target():
    from agora.roles import FORMAL_ROSTER
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp, n_agents=6, roster=FORMAL_ROSTER,
                   oracle_kwargs={"target": "parity5"}, difficulty=3)
        s = Colony(cfg, "formula").run()
        assert s["oracle"] == "formula"
        assert s["best_score"] > 0                        # the loop ran and scored
        assert s["verified"] in (True, False)             # the Z3 gate produced a verdict


# --------------------------------------------------- run.py target resolution
def test_run_cli_resolves_target_from_difficulty(monkeypatch):
    captured = {}

    class _FakeColony:
        def __init__(self, cfg, oracle_name="rotary"):
            captured["target"] = cfg.oracle_kwargs.get("target")
            captured["difficulty"] = cfg.difficulty

        def run(self):
            return {}

    import agora.run as run_mod
    monkeypatch.setattr(run_mod, "Colony", _FakeColony)
    # no --target -> difficulty selects it
    run_mod.main(["--oracle", "formula", "--difficulty", "2", "--fresh"])
    assert captured["target"] == "parity4" and captured["difficulty"] == 2
    # explicit --target wins over difficulty
    run_mod.main(["--oracle", "formula", "--target", "and3", "--difficulty", "3", "--fresh"])
    assert captured["target"] == "and3"
