"""
Frontier #6 — verifier-gated self-improvement.

A META-loop that evolves the colony's OWN proposer strategies (their instruction
"flavors" — the GENOME). Each candidate genome is scored by FITNESS:

    fitness = (# Z3-VERIFIED discoveries across a battery of targets,
               total score as a tiebreak)

A mutation is KEPT only if fitness STRICTLY improves. Because the count is of
*formally verified* wins, fitness cannot be reward-hacked: you cannot fake a Z3
proof. The verifier (#1) is the un-gameable ground the self-improvement climbs.

Budget: ONE shared CostTracker threads through every inner colony run, so the
spend cap is a single GLOBAL budget across the whole battery × every step. The
instant it is crossed, the current battery halts and the meta-loop stops.

Mock note: MockClient is flavor-BLIND (it local-searches via oracle.mutate and
ignores the genome), so rewriting flavors never changes fitness and the gate
correctly ACCEPTS NOTHING. That is the gate working — it refuses non-improvements.
Real agents read the flavor, so that is where the genome actually evolves.

CLI:  python -m agora.evolve --steps 4 --cap 5.00 [--real]
"""
from __future__ import annotations
import argparse, json, os
from dataclasses import replace

from .config import Config
from .cost import CostTracker, SpendCapExceeded
from .colony import Colony
from .roles import FORMAL_ROSTER, get_role, kind_of, PROPOSER

DEFAULT_BATTERY = ["majority3", "mux", "parity3"]


# --------------------------------------------------------------------- genome
def proposer_roles(roster: list[str]) -> list[str]:
    return [r for r in roster if kind_of(r) == PROPOSER]


def baseline_genome(roster: list[str]) -> dict:
    """The starting genome = each proposer role's baseline flavor."""
    return {r: get_role(r).flavor for r in proposer_roles(roster)}


# ----------------------------------------------------- genome persistence
# genome.json lets improvements ACCUMULATE across separate invocations: each run
# loads the evolved genome (or baseline if none yet), improves it, and saves it.
def load_genome(path, roster):
    """Load the persisted genome, falling back to baseline flavors. Only proposer
    roles present in the current roster are kept, so the roster can change safely."""
    base = baseline_genome(roster)
    if not path or not os.path.exists(path):
        return {"genome": base, "rotation_index": 0, "history": [], "battery": None}
    with open(path) as f:
        data = json.load(f)
    genome = dict(base)
    genome.update({k: v for k, v in data.get("genome", {}).items() if k in base})
    return {"genome": genome,
            "rotation_index": int(data.get("rotation_index", 0)),
            "history": list(data.get("history", [])),
            "battery": data.get("battery")}


def save_genome(path, genome, rotation_index, history, battery, history_keep=20):
    """Atomically persist genome + rotation index + a short accepted-change history."""
    data = {"genome": genome, "rotation_index": rotation_index,
            "history": history[-history_keep:], "battery": battery}
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)   # atomic — safe if killed mid-write


# ------------------------------------------------------------------- fitness
def is_improvement(new_fit, old_fit) -> bool:
    """STRICT, lexicographic: more verified wins, or equal wins + higher score.

    This is the whole anti-reward-hacking gate. (verified, score) tuples compare
    lexicographically in Python, so `>` already does the right thing — but we name
    it so the gating rule is testable and unmistakable."""
    return tuple(new_fit) > tuple(old_fit)


class EvolveLog:
    """JSONL meta-log: every eval, mutation, and accept/reject decision."""
    def __init__(self, path: str):
        self.path = path
        open(path, "w").close()

    def emit(self, kind: str, **data) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps({"event": kind, **data}) + "\n")


def _evaluate(genome, step, phase, *, battery, cost, base_cfg, oracle_name,
              out_dir, elog, quiet):
    """Run the colony on every target in the battery with this genome.

    Returns ((verified_count, total_score), halted, n_evaluated). Stops early and
    sets halted=True the moment the shared budget is exhausted (mid-battery)."""
    verified_count = 0
    total = 0.0
    halted = False
    n_eval = 0
    for target in battery:
        tag = f"s{step}_{phase}_{target}"
        cfg = replace(
            base_cfg,
            oracle_kwargs={"target": target},
            flavor_overrides=genome,
            quiet=True, resume=False,
            log_file=os.path.join(out_dir, f"{tag}.jsonl"),
            state_file=os.path.join(out_dir, f"{tag}.state.json"),
            curve_file=os.path.join(out_dir, f"{tag}.curve.csv"),
        )
        summ = Colony(cfg, oracle_name, cost_tracker=cost).run()
        n_eval += 1
        verified = summ.get("verified") is True
        verified_count += int(verified)
        total += summ["best_score"]
        elog.emit("eval", step=step, phase=phase, target=target,
                  verified=verified, score=summ["best_score"],
                  stop_reason=summ["stop_reason"], log=cfg.log_file)
        if not quiet:
            mark = "VERIFIED" if verified else f"{summ['best_score']:.1f}"
            print(f"    [{phase}] {target:10} -> {mark}   "
                  f"(${cost.usd:.4f}/{cost.cap:.2f})")
        if summ["stop_reason"] == "spend_cap" or cost.usd >= cost.cap:
            halted = True
            break
    fit = (verified_count, round(total, 2))
    elog.emit("fitness", step=step, phase=phase, verified_count=verified_count,
              total_score=round(total, 2), n_evaluated=n_eval, halted=halted,
              genome=genome)
    return fit, halted, n_eval


# ----------------------------------------------------------------- mutation
def _mutate_flavor(role: str, flavor: str, step: int, real: bool, cost, gen_model):
    """Produce a new flavor for `role`. Mock = deterministic tweak (flavor-blind,
    so fitness won't move). Real = ask the model to rewrite toward correct, minimal
    formulas (this is where the genome can actually improve)."""
    if not real:
        return f"{flavor} Push variant {step}: output a CORRECT, MINIMAL formula."
    from .llm import AnthropicClient
    client = AnthropicClient()
    system = ("You rewrite a one-line instruction for an AI agent that synthesizes "
              "Boolean formulas. Make it push HARDER toward formulas that are exactly "
              "correct on every truth-table row and as SMALL as possible. "
              "Reply with ONLY the new one-line instruction, no preamble.")
    user = f"Role: {role}. Current instruction: {flavor}"
    r = client.complete(gen_model, system, user, max_tokens=120)
    cost.charge(gen_model, r.in_tok, r.out_tok)   # shared global budget
    new = " ".join(r.text.strip().split())
    return new or flavor


# ------------------------------------------------------------------- meta-loop
def evolve(steps=4, cap=5.00, real=False, battery=None, inner_cycles=8,
           inner_agents=None, seed=7, out_dir="runs",
           evolve_log="evolve_log.jsonl", quiet=False, cost=None,
           oracle_name="formula", roster=None, genome_path=None):
    """Run the self-improvement meta-loop. Returns a summary dict.

    `cost` lets a caller (or test) pass in a pre-existing shared CostTracker so the
    cap spans this AND other work — a true global budget. `genome_path`, if given,
    LOADS the persisted genome at start and SAVES the improved one at the end so
    gains accumulate across runs."""
    battery = battery or list(DEFAULT_BATTERY)
    roster = roster or FORMAL_ROSTER
    inner_agents = inner_agents or len(roster)
    os.makedirs(out_dir, exist_ok=True)
    cost = cost or CostTracker(cap)
    elog = EvolveLog(evolve_log)

    base_cfg = Config(
        n_agents=inner_agents, roster=roster, n_cycles=inner_cycles,
        patience=inner_cycles, spend_cap_usd=cap, use_mock=not real, seed=seed,
        quiet=True,
    )
    proposers = proposer_roles(roster)
    loaded = load_genome(genome_path, roster) if genome_path else None
    genome = loaded["genome"] if loaded else baseline_genome(roster)
    history = loaded["history"] if loaded else []
    rot = loaded["rotation_index"] if loaded else 0
    elog.emit("baseline_genome", genome=genome, battery=battery,
              roster=roster, real=real)
    if not quiet:
        print(f"[evolve] battery={battery} steps={steps} cap=${cap:.2f} "
              f"mode={'REAL' if real else 'MOCK'}")

    base_fit, halted, _ = _evaluate(genome, 0, "baseline", battery=battery,
                                    cost=cost, base_cfg=base_cfg,
                                    oracle_name=oracle_name, out_dir=out_dir,
                                    elog=elog, quiet=quiet)
    best_fit = base_fit
    if not quiet:
        print(f"[evolve] baseline fitness = {best_fit}  "
              f"(verified={best_fit[0]}, score={best_fit[1]})")

    accepted = 0
    for step in range(1, steps + 1):
        if halted:
            break
        # mutate ONE proposer's flavor (round-robin across proposers by step)
        role = proposers[(step - 1) % len(proposers)]
        before = genome[role]
        try:
            after = _mutate_flavor(role, before, step, real, cost, base_cfg.gen_model)
        except SpendCapExceeded:
            halted = True
            elog.emit("decision", step=step, decision="HALT_ON_MUTATION")
            break
        cand = dict(genome)
        cand[role] = after
        elog.emit("mutation", step=step, role=role, before=before, after=after)

        cand_fit, halted, _ = _evaluate(cand, step, "candidate", battery=battery,
                                        cost=cost, base_cfg=base_cfg,
                                        oracle_name=oracle_name, out_dir=out_dir,
                                        elog=elog, quiet=quiet)
        if is_improvement(cand_fit, best_fit):
            history.append({"target": "battery", "role": role,
                            "before_fitness": list(best_fit), "after_fitness": list(cand_fit),
                            "before": before, "after": after})
            genome, best_fit = cand, cand_fit
            accepted += 1
            decision = "ACCEPT"
        else:
            decision = "REJECT"
        elog.emit("decision", step=step, decision=decision, role=role,
                  from_fitness=list(best_fit if decision == "REJECT" else cand_fit),
                  cand_fitness=list(cand_fit), accepted_genome=genome)
        if not quiet:
            tag = "[ACCEPT]" if decision == "ACCEPT" else "[reject]"
            print(f"{tag} step {step} role={role}: cand={cand_fit} best={best_fit}")

    if genome_path:
        save_genome(genome_path, genome, rot, history, battery)
    result = {
        "steps_run": min(steps, step if steps else 0),
        "accepted": accepted,
        "baseline_fitness": list(base_fit),
        "best_fitness": list(best_fit),
        "verified_gain": best_fit[0] - base_fit[0],
        "halted": halted,
        "genome": genome,
        "cost": cost.as_dict(),
        "evolve_log": evolve_log,
        "battery": battery,
        "genome_path": genome_path,
    }
    elog.emit("final", **result)
    if not quiet:
        print(f"\n=== EVOLVE RESULT ===")
        print(f"accepted mutations : {accepted}")
        print(f"baseline fitness   : {base_fit}")
        print(f"best fitness       : {best_fit}   (+{result['verified_gain']} verified)")
        print(f"halted (budget)    : {halted}")
        print(f"spend              : ${cost.usd:.4f} / ${cap:.2f}")
    return result


def trickle(genome_path="genome.json", cap=0.50, real=False, battery=None,
            inner_cycles=2, inner_agents=None, seed=7, out_dir="runs",
            evolve_log="evolve_log.jsonl", quiet=False, cost=None,
            oracle_name="formula", roster=None):
    """A gentle, ACCUMULATING entry point: exactly ONE attempt per invocation.

    Loads the persisted genome, rotates to ONE target, evaluates the current genome
    and ONE mutated variant on just that target, keeps the mutation only if it is a
    verifier-gated improvement (more verified, ties by score), then saves genome.json.
    Same gate as the full meta-loop — only cheaper and incremental."""
    roster = roster or FORMAL_ROSTER
    inner_agents = inner_agents or len(roster)
    os.makedirs(out_dir, exist_ok=True)
    cost = cost or CostTracker(cap)
    elog = EvolveLog(evolve_log)

    loaded = load_genome(genome_path, roster)
    genome = loaded["genome"]
    history = loaded["history"]
    rot = loaded["rotation_index"]
    battery = battery or loaded["battery"] or list(DEFAULT_BATTERY)
    proposers = proposer_roles(roster)
    target = battery[rot % len(battery)]          # rotate the target each invocation
    role = proposers[rot % len(proposers)]        # ... and which proposer we nudge

    base_cfg = Config(n_agents=inner_agents, roster=roster, n_cycles=inner_cycles,
                      patience=inner_cycles, spend_cap_usd=cap, use_mock=not real,
                      seed=seed, quiet=True)
    elog.emit("trickle_start", target=target, role=role, rotation_index=rot,
              genome=genome, real=real)
    if not quiet:
        print(f"[trickle] target={target} nudge={role} rot={rot} "
              f"cap=${cap:.2f} mode={'REAL' if real else 'MOCK'}")

    # 1) current genome on the one rotated target
    cur_fit, halted, _ = _evaluate(genome, rot, "trickle_cur", battery=[target],
                                   cost=cost, base_cfg=base_cfg, oracle_name=oracle_name,
                                   out_dir=out_dir, elog=elog, quiet=quiet)
    before = genome[role]
    after = before
    cand_fit = cur_fit
    accepted = False
    # 2) ONE mutated variant on the SAME target (skip if the budget is already spent)
    if not halted:
        try:
            after = _mutate_flavor(role, before, rot, real, cost, base_cfg.gen_model)
            cand = dict(genome)
            cand[role] = after
            elog.emit("mutation", step=rot, role=role, before=before, after=after)
            cand_fit, halted, _ = _evaluate(cand, rot, "trickle_cand", battery=[target],
                                            cost=cost, base_cfg=base_cfg,
                                            oracle_name=oracle_name, out_dir=out_dir,
                                            elog=elog, quiet=quiet)
            if is_improvement(cand_fit, cur_fit):     # the SAME verifier-gate
                genome = cand
                accepted = True
                history.append({"target": target, "role": role,
                                "before_fitness": list(cur_fit), "after_fitness": list(cand_fit),
                                "before": before, "after": after})
        except SpendCapExceeded:
            halted = True

    rot_next = rot + 1                                  # advance rotation for next time
    save_genome(genome_path, genome, rot_next, history, battery)
    decision = "ACCEPT" if accepted else ("HALT" if halted else "reject")
    elog.emit("decision", step=rot, decision=decision, role=role, target=target,
              cur_fitness=list(cur_fit), cand_fitness=list(cand_fit))

    result = {
        "target": target, "role": role, "accepted": accepted, "halted": halted,
        "cur_fitness": list(cur_fit), "cand_fitness": list(cand_fit),
        "rotation_index": rot_next, "genome": genome, "history": history,
        "cost": cost.as_dict(), "genome_path": genome_path,
    }
    if not quiet:
        tag = "[ACCEPT]" if accepted else ("[HALT]" if halted else "[reject]")
        print(f"{tag} target={target} role={role}: cur={cur_fit} cand={cand_fit}")
        print(f"        saved {genome_path} (rot->{rot_next})  "
              f"spend ${cost.usd:.4f}/${cap:.2f}")
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="agora #6: verifier-gated self-improvement")
    p.add_argument("--trickle", action="store_true",
                   help="cheap ACCUMULATING mode: exactly ONE attempt on one rotated "
                        "target, persisting to genome.json (defaults to real, tiny, $0.50 cap)")
    p.add_argument("--steps", type=int, default=4)
    p.add_argument("--cap", type=float, default=None,
                   help="GLOBAL spend cap USD (default 5.00; trickle default 0.50)")
    p.add_argument("--real", action="store_true", help="use real Claude (needs ANTHROPIC_API_KEY)")
    p.add_argument("--mock", action="store_true", help="force mock (overrides trickle's real default)")
    p.add_argument("--battery", default=",".join(DEFAULT_BATTERY),
                   help="comma-separated formula targets")
    p.add_argument("--cycles", type=int, default=None,
                   help="inner colony cycles per run (default 8; trickle default 2)")
    p.add_argument("--agents", type=int, default=None, help="inner agents (default roster size)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out-dir", default="runs")
    p.add_argument("--evolve-log", default="evolve_log.jsonl")
    p.add_argument("--genome", default="genome.json", help="persisted evolved genome file")
    args = p.parse_args(argv)
    battery = [t.strip() for t in args.battery.split(",") if t.strip()]

    if args.trickle:
        # gentle defaults: real API, tiny + cheap, one attempt
        real = not args.mock
        trickle(genome_path=args.genome, cap=args.cap if args.cap is not None else 0.50,
                real=real, battery=battery,
                inner_cycles=args.cycles if args.cycles is not None else 2,
                inner_agents=args.agents, seed=args.seed,
                out_dir=args.out_dir, evolve_log=args.evolve_log)
    else:
        evolve(steps=args.steps,
               cap=args.cap if args.cap is not None else 5.00,
               real=args.real and not args.mock,
               battery=battery,
               inner_cycles=args.cycles if args.cycles is not None else 8,
               inner_agents=args.agents, seed=args.seed,
               out_dir=args.out_dir, evolve_log=args.evolve_log,
               genome_path=args.genome)


if __name__ == "__main__":
    main()
