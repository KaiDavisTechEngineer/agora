"""
CLI for agora.

Examples
--------
  python -m agora.run                                  # 3 agents, rotary, mock, $0
  python -m agora.run --agents 15 --cycles 30
  python -m agora.run --oracle repurposing --agents 10
  python -m agora.run --real --cap 1.00 --agents 5     # real Claude, $1 ceiling
  python -m agora.run --fresh                           # ignore saved state, start over
  touch STOP                                            # halt a running colony gracefully
"""
from __future__ import annotations
import argparse
from .config import Config
from .colony import Colony


def main(argv=None):
    p = argparse.ArgumentParser(description="agora co-scientist colony")
    p.add_argument("--oracle", default="rotary", choices=["rotary", "repurposing", "formula"])
    p.add_argument("--target", default=None,
                   choices=["majority3", "mux", "and3", "parity3",
                            "parity4", "majority5", "parity5"],
                   help="formula-oracle target (only used with --oracle formula); "
                        "if omitted, picked from --difficulty")
    p.add_argument("--difficulty", type=int, default=1, choices=[1, 2, 3],
                   help="formula difficulty: 1=k3 (easy), 2=k4, 3=k5 (hard). "
                        "Selects the target when --target is not given.")
    p.add_argument("--agents", type=int, default=None,
                   help="agent count; defaults to the roster size (so every role is filled)")
    p.add_argument("--k-peers", type=int, default=3)
    p.add_argument("--cycles", type=int, default=12)
    p.add_argument("--patience", type=int, default=5)
    p.add_argument("--cap", type=float, default=5.00, help="hard spend cap (USD)")
    p.add_argument("--real", action="store_true", help="use real Claude (needs ANTHROPIC_API_KEY)")
    p.add_argument("--proposer-model", default=None,
                   help="model for proposer work (generate/revise); default = gen tier")
    p.add_argument("--critic-model", default=None,
                   help="model for critic work (critique); default = grunt tier")
    p.add_argument("--validator-model", default=None,
                   help="model for validator work (audit); default = grunt tier")
    p.add_argument("--no-revision", action="store_true", help="disable the Phase 1 revision step")
    p.add_argument("--fresh", action="store_true", help="ignore saved state; start over")
    p.add_argument("--quiet-log", action="store_true",
                   help="skip per-agent candidate logging (use at 50-100 agents)")
    p.add_argument("--roster", default="base", choices=["base", "quant", "formal"],
                   help="role lineup: base, the 12-role quant, or the 6-role formal-discovery")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--state-file", default="colony_state.json")
    args = p.parse_args(argv)

    from .roles import QUANT_ROSTER, FORMAL_ROSTER
    roster = {"quant": QUANT_ROSTER, "formal": FORMAL_ROSTER}.get(args.roster)
    # default agent count = roster size, so every named role is actually filled
    n_agents = args.agents if args.agents is not None else (len(roster) if roster else 3)
    # target precedence: explicit --target wins; otherwise pick by --difficulty
    from .oracles import default_target
    target = args.target if args.target is not None else default_target(args.difficulty)
    oracle_kwargs = {"target": target} if args.oracle == "formula" else {}
    role_models = {k: m for k, m in (("proposer", args.proposer_model),
                                     ("critic", args.critic_model),
                                     ("validator", args.validator_model)) if m} or None
    cfg = Config(
        n_agents=n_agents, k_peers=args.k_peers, n_cycles=args.cycles,
        patience=args.patience, spend_cap_usd=args.cap, use_mock=not args.real,
        enable_revision=not args.no_revision, resume=not args.fresh,
        seed=args.seed, state_file=args.state_file, log_candidates=not args.quiet_log,
        roster=roster, oracle_kwargs=oracle_kwargs, difficulty=args.difficulty,
        role_models=role_models,
    )
    Colony(cfg, oracle_name=args.oracle).run()


if __name__ == "__main__":
    main()
