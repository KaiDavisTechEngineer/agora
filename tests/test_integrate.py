"""
Integration test — the full #1 -> #6 -> #5 flow runs end-to-end (mock, $-metered).
"""
import os, tempfile

from agora.integrate import integrated_run


def test_integrated_flow_runs_and_explains():
    with tempfile.TemporaryDirectory() as tmp:
        out = integrated_run(
            steps=2, cap=5.0, real=False, battery=["majority3", "and3"],
            inner_cycles=4, out_dir=os.path.join(tmp, "runs"),
            evolve_log=os.path.join(tmp, "evolve_log.jsonl"), quiet=True,
        )
        evo, rep = out["evolve"], out["interpret"]
        # #6 produced a fitness on the verifiable oracle
        assert "baseline_fitness" in evo and len(evo["baseline_fitness"]) == 2
        # #5 explained it from the logs that #6 produced
        assert rep["n_run_logs"] > 0
        assert rep["revision_acceptance_by_role"]
        assert "flavor_evolution" in rep
        # one shared budget metered the whole thing
        assert out["cost"]["usd"] > 0
