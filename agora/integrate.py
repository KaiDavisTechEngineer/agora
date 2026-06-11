"""
Integration — the four frontiers in one coherent loop, behind one shared budget.

A single integrated run:
  P2  selects a per-role-kind model       (proposer / critic / validator)
  P1  attempts a HARD verifiable target   (Z3-decidable, picked by --difficulty)
  P3  runs ONE cheap "trickle" self-improvement step that adjusts strategy params
      strictly behind the Oracle gate, persisting to a genome store (allowlisted +
      audited; a reward-hack can't touch the gate/cap/score)
  P4  emits an EXPLANATORY trace: which critiques moved Elo, and which role/model
      contributed — read back from the very logs the run produced.

  per-role models ─▶ hard target ─▶ trickle (gate-bounded) ─▶ explanatory trace
        (P2)             (P1)              (P3)                      (P4)

ONE shared CostTracker caps the whole thing as a single global budget (I2), and the
Z3 verifier remains the only real gate (I1).

CLI:  python -m agora.integrate --difficulty 2 --cap 5.00 [--real]
      python -m agora.integrate --proposer-model claude-fable-5 --difficulty 3
"""
from __future__ import annotations
import argparse

from .cost import CostTracker
from .config import resolve_role_models, Config
from .evolve import trickle, DEFAULT_BATTERY
from .interpret import analyze, render
from .oracles import default_target, difficulty_of


def integrated_run(difficulty=2, cap=5.00, real=False, target=None,
                   role_models=None, genome_path="genome.json", inner_cycles=4,
                   out_dir="runs", evolve_log="evolve_log.jsonl", seed=7,
                   quiet=False, cost=None, propose_mutation=None,
                   halt_before_overspend=True, proposer_max_tokens=600):
    """Run the integrated P2->P1->P3->P4 flow. Returns a structured result.

    `cost` lets a caller pass a pre-existing shared CostTracker (the single global
    budget). `target` overrides the difficulty-selected hard target. `role_models`
    assigns a model per role-kind (P2). `propose_mutation` is injectable for tests."""
    target = target or default_target(difficulty)
    resolved_models = resolve_role_models(Config(role_models=role_models))
    cost = cost or CostTracker(cap)

    if not quiet:
        print("===== AGORA INTEGRATED RUN =====")
        print(f"P2 models={resolved_models}")
        print(f"P1 target={target} (difficulty {difficulty_of(target)})  "
              f"P3 genome={genome_path}  cap=${cap:.2f}  "
              f"mode={'REAL' if real else 'MOCK'}\n")

    # P1 hard target + P2 per-role models + P3 ONE gate-bounded trickle step, all under
    # the single shared budget. trickle persists evolved strategy params + an audit.
    tk = trickle(genome_path=genome_path, cap=cap, real=real, battery=[target],
                 inner_cycles=inner_cycles, out_dir=out_dir, evolve_log=evolve_log,
                 seed=seed, quiet=True, cost=cost, role_models=role_models,
                 propose_mutation=propose_mutation,
                 halt_before_overspend=halt_before_overspend,
                 proposer_max_tokens=proposer_max_tokens)

    # P4 explanatory trace, read back from the logs this run produced
    report = analyze(run_dir=out_dir, evolve_log=evolve_log)

    if not quiet:
        print(render(report))
        print("\n===== INTEGRATION SUMMARY =====")
        print(f"target          : {target}  (verified-gated; mutation {tk['decision']})")
        print(f"genome          : {genome_path}  (rotation -> {tk['rotation_index']})")
        print(f"self-improvement: accepted={tk['accepted']}  reason={tk['reason']}")
        print(f"audit trail     : {len(tk['audit'])} entries "
              f"({sum(1 for a in tk['audit'] if a['decision']=='ACCEPT')} accepted)")
        bm = cost.as_dict()["by_model"]
        print(f"global spend    : ${cost.usd:.4f} / ${cap:.2f}"
              f"{'  (HALTED on budget)' if tk['halted'] else ''}")
        print(f"per-model spend : "
              + ", ".join(f"{m}=${r['usd']:.4f}/{r['calls']}c" for m, r in bm.items()))

    return {"trickle": tk, "interpret": report, "cost": cost.as_dict(),
            "target": target, "role_models": resolved_models,
            "genome_path": genome_path}


def main(argv=None):
    p = argparse.ArgumentParser(
        description="agora integration: per-role models -> hard target -> "
                    "trickle self-improvement -> explanatory trace")
    p.add_argument("--difficulty", type=int, default=2, choices=[1, 2, 3],
                   help="hard target difficulty: 1=k3, 2=k4, 3=k5")
    p.add_argument("--target", default=None, help="override the difficulty-selected target")
    p.add_argument("--cap", type=float, default=5.00, help="GLOBAL spend cap (USD)")
    p.add_argument("--real", action="store_true", help="real Claude (needs ANTHROPIC_API_KEY)")
    p.add_argument("--proposer-model", default=None)
    p.add_argument("--critic-model", default=None)
    p.add_argument("--validator-model", default=None)
    p.add_argument("--cycles", type=int, default=4, help="inner colony cycles")
    p.add_argument("--proposer-max-tokens", type=int, default=600,
                   help="output budget for proposer generate/revise calls "
                        "(raise for large-AST targets; default 600)")
    p.add_argument("--out-dir", default="runs")
    p.add_argument("--evolve-log", default="evolve_log.jsonl")
    p.add_argument("--genome", default="genome.json")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args(argv)

    role_models = {k: m for k, m in (("proposer", args.proposer_model),
                                     ("critic", args.critic_model),
                                     ("validator", args.validator_model)) if m} or None
    integrated_run(difficulty=args.difficulty, cap=args.cap, real=args.real,
                   target=args.target, role_models=role_models,
                   genome_path=args.genome, inner_cycles=args.cycles,
                   out_dir=args.out_dir, evolve_log=args.evolve_log, seed=args.seed,
                   proposer_max_tokens=args.proposer_max_tokens)


if __name__ == "__main__":
    main()
