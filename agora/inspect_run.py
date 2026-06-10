"""
Read candidate-level logs like a code review.

  python -m agora.inspect_run --cycle 5                 # full triples for cycle 5
  python -m agora.inspect_run --signals                 # green/red-flag metrics, all cycles
  python -m agora.inspect_run --log run_log.jsonl --cycle 5

Triples per agent = proposal (+score) -> critiques it received -> revision
(before/after/accepted). The signals view computes the things that distinguish
real reasoning from churn: revision acceptance rate, detonation-cliff hits,
and average score by role.
"""
from __future__ import annotations
import argparse, json
from collections import defaultdict


def load(log_file: str):
    rows = []
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def show_cycle(rows, cycle: int):
    props = {r["agent"]: r for r in rows if r.get("event") == "proposal" and r.get("cycle") == cycle}
    crits = defaultdict(list)
    for r in rows:
        if r.get("event") == "critique" and r.get("cycle") == cycle:
            crits[r["target"]].append(r)
    revs = {r["agent"]: r for r in rows if r.get("event") == "revision" and r.get("cycle") == cycle}
    audits = [r for r in rows if r.get("event") == "audit" and r.get("cycle") == cycle]

    if not props:
        print(f"No proposal events for cycle {cycle}. "
              f"(Was log_candidates on? Is the cycle in range?)")
        return

    print(f"===== CYCLE {cycle} =====\n")
    for aid in sorted(props):
        p = props[aid]
        print(f"[agent {aid} | {p['role']}]  proposed score {p['score']}")
        print(f"   candidate: {json.dumps(p['candidate'])}")
        for c in crits.get(aid, []):
            print(f"   critique from {c['critic']} ({c['critic_role']}): {c['text']}")
        rv = revs.get(aid)
        if rv:
            verdict = "ACCEPTED" if rv["accepted"] else "rejected"
            print(f"   revision [{verdict}]: {rv['before_score']} -> {rv['after_score']}  "
                  f"{json.dumps(rv['after'])}")
        print()
    for au in audits:
        print(f"[AUDIT by {au['auditor']} | {au['role']}] {au['text']}")
    if audits:
        print()


def show_signals(rows):
    cycles = sorted({r["cycle"] for r in rows if r.get("event") == "proposal"})
    if not cycles:
        print("No candidate-level events found. Run with log_candidates=True.")
        return
    props = [r for r in rows if r.get("event") == "proposal"]
    revs = [r for r in rows if r.get("event") == "revision"]

    # revision acceptance rate (informative critiques -> kept revisions)
    acc = sum(1 for r in revs if r["accepted"])
    rate = acc / len(revs) * 100 if revs else 0.0

    # detonation-cliff hits (rotary: negative score == grenaded engine)
    cliff = sum(1 for r in props if r["score"] < 0)
    cliff_by_role = defaultdict(int)
    for r in props:
        if r["score"] < 0:
            cliff_by_role[r["role"]] += 1

    # average proposal score by role (is differentiation real?)
    by_role = defaultdict(list)
    for r in props:
        by_role[r["role"]].append(r["score"])

    print("===== REASONING SIGNALS =====")
    print(f"cycles logged           : {len(cycles)}  ({cycles[0]}..{cycles[-1]})")
    print(f"proposals               : {len(props)}")
    print(f"revision acceptance     : {rate:.0f}%   ({acc}/{len(revs)})   "
          f"[higher = critiques are informative]")
    print(f"detonation-cliff hits   : {cliff}   by role: {dict(cliff_by_role)}   "
          f"[skeptics should be ~0; should fall over time]")
    print("avg proposal score by role:")
    for role in sorted(by_role):
        xs = by_role[role]
        print(f"   {role:<10} {sum(xs)/len(xs):7.1f}   (n={len(xs)})")
    print("\nGreen flags: acceptance climbing, cliff hits -> 0, roles clearly differ.")
    print("Red flags:   acceptance ~0, repeated cliff hits, identical scores across roles.")


def main(argv=None):
    p = argparse.ArgumentParser(description="inspect agora candidate logs")
    p.add_argument("--log", default="run_log.jsonl")
    p.add_argument("--cycle", type=int, help="show full triples for this cycle")
    p.add_argument("--signals", action="store_true", help="show reasoning-quality metrics")
    args = p.parse_args(argv)

    rows = load(args.log)
    if args.cycle is not None:
        show_cycle(rows, args.cycle)
    if args.signals or args.cycle is None:
        show_signals(rows)


if __name__ == "__main__":
    main()
