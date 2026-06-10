"""
Integration — verified, self-improving, and explained, in one flow.

Runs the #6 self-improvement meta-loop ON the #1 verifiable formula oracle (so
fitness is the count of Z3-PROVEN discoveries, un-gameable), then runs the #5
interpretability pass over the very logs that run produced. One shared CostTracker
caps the whole thing as a single global budget.

  #1 verifiable oracle  --->  #6 evolves strategy genome  --->  #5 explains the wins
        (truth)                   (climbs proven fitness)            (reads the logs)

CLI:  python -m agora.integrate --steps 4 --cap 5.00 [--real]
"""
from __future__ import annotations
import argparse, os

from .cost import CostTracker
from .evolve import evolve, DEFAULT_BATTERY
from .interpret import analyze, render


def integrated_run(steps=3, cap=5.00, real=False, battery=None, inner_cycles=6,
                   out_dir="runs", evolve_log="evolve_log.jsonl", seed=7,
                   quiet=False):
    battery = battery or list(DEFAULT_BATTERY)
    # ONE shared budget spans the entire self-improvement run
    cost = CostTracker(cap)

    if not quiet:
        print("===== AGORA INTEGRATED RUN =====")
        print(f"#1 oracle=formula  #6 battery={battery}  steps={steps}  "
              f"cap=${cap:.2f}  mode={'REAL' if real else 'MOCK'}\n")

    evo = evolve(steps=steps, cap=cap, real=real, battery=battery,
                 inner_cycles=inner_cycles, out_dir=out_dir,
                 evolve_log=evolve_log, seed=seed, quiet=quiet,
                 cost=cost, oracle_name="formula")

    report = analyze(run_dir=out_dir, evolve_log=evolve_log)
    if not quiet:
        print("\n" + render(report))
        print("\n===== INTEGRATION SUMMARY =====")
        print(f"verified discoveries : baseline {evo['baseline_fitness'][0]} "
              f"-> best {evo['best_fitness'][0]}  (+{evo['verified_gain']})")
        print(f"accepted mutations   : {evo['accepted']}")
        print(f"global spend         : ${cost.usd:.4f} / ${cap:.2f}"
              f"{'  (HALTED on budget)' if evo['halted'] else ''}")
        print(f"explained by         : {len(report['verified_wins_by_role'])} winning role(s); "
              f"{report['n_run_logs']} run logs")

    return {"evolve": evo, "interpret": report, "cost": cost.as_dict()}


def main(argv=None):
    p = argparse.ArgumentParser(
        description="agora integration: verified, self-improving, explained")
    p.add_argument("--steps", type=int, default=3)
    p.add_argument("--cap", type=float, default=5.00, help="GLOBAL spend cap (USD)")
    p.add_argument("--real", action="store_true", help="real Claude (needs ANTHROPIC_API_KEY)")
    p.add_argument("--battery", default=",".join(DEFAULT_BATTERY))
    p.add_argument("--cycles", type=int, default=6, help="inner colony cycles per run")
    p.add_argument("--out-dir", default="runs")
    p.add_argument("--evolve-log", default="evolve_log.jsonl")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args(argv)
    integrated_run(steps=args.steps, cap=args.cap, real=args.real,
                   battery=[t.strip() for t in args.battery.split(",") if t.strip()],
                   inner_cycles=args.cycles, out_dir=args.out_dir,
                   evolve_log=args.evolve_log, seed=args.seed)


if __name__ == "__main__":
    main()
