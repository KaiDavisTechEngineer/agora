"""
Frontier #5 — behavioral interpretability of the self-improvement.

Reads the run logs (per inner colony) and the evolve meta-log and explains WHICH
evolved strategies produced the verified wins — purely from logged behavior, not
model internals. It reports:

  1. VERIFIED WINS BY ROLE     — which proposer role authored each Z3-verified best
  2. REVISION ACCEPTANCE BY ROLE — how often each role's revisions were kept
  3. CRITIQUE PATTERNS -> ACCEPTED REVISIONS — which critics/words precede a kept revision
  4. FLAVOR EVOLUTION DIFF      — baseline vs evolved flavors, and which specific
                                  instruction change correlated with a verified-count rise

CLI:  python -m agora.interpret --run-dir runs --evolve-log evolve_log.jsonl
"""
from __future__ import annotations
import argparse, glob, json, os, re
from collections import Counter, defaultdict

_STOP = {"the", "a", "an", "and", "or", "is", "it", "to", "of", "in", "on", "for",
         "this", "that", "with", "as", "be", "are", "if", "at", "by", "its", "not",
         "no", "but", "they", "you", "your", "row", "rows", "input", "inputs",
         "formula", "target", "where", "disagrees", "say", "whether", "minimal"}


# ------------------------------------------------------------------- loading
def _load_jsonl(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def load_run_logs(run_dir, evolve_log=None):
    """All inner run logs in run_dir (the per-target JSONL files), as {path: rows}."""
    skip = os.path.abspath(evolve_log) if evolve_log else None
    logs = {}
    for path in sorted(glob.glob(os.path.join(run_dir, "*.jsonl"))):
        if skip and os.path.abspath(path) == skip:
            continue
        logs[path] = _load_jsonl(path)
    return logs


# --------------------------------------------------------- 1. verified wins
def winning_role(rows):
    """The role whose candidate reached the highest score in this run (the one a
    verified=True certificate is attributable to)."""
    best_score, best_role = float("-inf"), None
    for r in rows:
        if r.get("event") == "proposal":
            if r["score"] > best_score:
                best_score, best_role = r["score"], r["role"]
        elif r.get("event") == "revision" and r.get("accepted"):
            if r["after_score"] > best_score:
                best_score, best_role = r["after_score"], r["role"]
    return best_role, best_score


def verified_wins_by_role(evolve_rows, run_dir):
    """Attribute every Z3-verified win (from the evolve log's eval events) to the
    role that authored the winning formula in that run's log."""
    wins = Counter()
    detail = []
    for r in evolve_rows:
        if r.get("event") != "eval" or not r.get("verified"):
            continue
        log = r.get("log")
        rows = _load_jsonl(log) if log and os.path.exists(log) else []
        role, score = winning_role(rows) if rows else (None, None)
        if role:
            wins[role] += 1
        detail.append({"step": r.get("step"), "phase": r.get("phase"),
                       "target": r.get("target"), "role": role, "score": score})
    return wins, detail


# ------------------------------------------------ 2. revision acceptance by role
def revision_acceptance_by_role(run_logs):
    tally = defaultdict(lambda: [0, 0])   # role -> [accepted, total]
    for rows in run_logs.values():
        for r in rows:
            if r.get("event") == "revision":
                tally[r["role"]][1] += 1
                if r.get("accepted"):
                    tally[r["role"]][0] += 1
    return {role: {"accepted": a, "total": t, "rate": (a / t if t else 0.0)}
            for role, (a, t) in tally.items()}


# ------------------------------ 3. critique patterns that precede accepted revisions
def _words(text):
    return [w for w in re.findall(r"[a-z]+", (text or "").lower())
            if len(w) > 2 and w not in _STOP]


def critique_patterns_before_accepted(run_logs):
    """For each accepted revision, look at the critiques that agent received the
    SAME cycle and tally the critic roles and salient words that preceded a keep."""
    critic_roles = Counter()
    words = Counter()
    n_accepted = 0
    for rows in run_logs.values():
        crits = defaultdict(list)            # (cycle, target) -> [critique rows]
        for r in rows:
            if r.get("event") == "critique":
                crits[(r["cycle"], r["target"])].append(r)
        for r in rows:
            if r.get("event") == "revision" and r.get("accepted"):
                n_accepted += 1
                for c in crits.get((r["cycle"], r["agent"]), []):
                    critic_roles[c.get("critic_role", "?")] += 1
                    words.update(_words(c.get("text", "")))
    return {"n_accepted_revisions": n_accepted,
            "critic_roles": dict(critic_roles.most_common()),
            "top_words": dict(words.most_common(10))}


# --------------------------------------------- 4. flavor evolution diff
def flavor_evolution(evolve_rows):
    """Baseline vs evolved genome, plus the specific instruction change that
    correlated with each rise in verified-count (the ACCEPTs)."""
    baseline = next((r["genome"] for r in evolve_rows
                     if r.get("event") == "baseline_genome"), {})
    final = next((r["genome"] for r in evolve_rows
                  if r.get("event") == "final"), baseline)

    by_step = defaultdict(dict)
    for r in evolve_rows:
        s = r.get("step")
        if r.get("event") == "mutation":
            by_step[s]["mutation"] = r
        elif r.get("event") == "decision":
            by_step[s]["decision"] = r

    correlated = []   # instruction changes that raised the verified-count
    prev_verified = next((r["verified_count"] for r in evolve_rows
                          if r.get("event") == "fitness" and r.get("phase") == "baseline"), 0)
    for s in sorted(k for k in by_step if k is not None):
        dec = by_step[s].get("decision", {})
        mut = by_step[s].get("mutation", {})
        if dec.get("decision") != "ACCEPT":
            continue
        cand_verified = (dec.get("cand_fitness") or [prev_verified])[0]
        delta = cand_verified - prev_verified
        if delta > 0:
            correlated.append({
                "step": s, "role": mut.get("role"),
                "verified_delta": delta,
                "before": mut.get("before"), "after": mut.get("after"),
            })
            prev_verified = cand_verified

    diff = {}
    for role in sorted(set(baseline) | set(final)):
        b, f = baseline.get(role), final.get(role)
        diff[role] = {"changed": b != f, "baseline": b, "evolved": f}
    return {"diff": diff, "correlated_with_verified_gain": correlated}


# ============================================================================
# EXPLANATORY layer (#5 upgrade) — WHY a candidate won or lost.
# Descriptive sections above say WHAT happened; these say WHY: which specific
# critiques moved a candidate's Elo, and which role/model contributed what. The
# causal chain logged by the colony is
#     critiques received  ->  accepted revision (score up)  ->  rank  ->  Elo delta
# so a positive per-cycle Elo delta is attributed to the critiques that agent
# received THAT cycle (the ones that drove its accepted, score-raising revision).
# ============================================================================
def explain_elo_attribution(run_logs):
    """Attribute Elo movement to roles/models and to the critiques that caused it.

    Returns a stable-shaped dict:
      elo_by_role        : proposer role -> {model, net_elo, appearances}
      critic_credit      : critic role  -> {model, elo_credited, critiques, decisive_revisions}
      decisive_critiques : the individual critiques credited with an Elo-raising,
                           revision-backed win (sorted deterministically)."""
    elo_by_role = defaultdict(lambda: {"model": None, "net_elo": 0.0, "appearances": 0})
    critic_credit = defaultdict(lambda: {"model": None, "elo_credited": 0.0,
                                         "critiques": 0, "decisive_revisions": 0})
    decisive = []
    for path, rows in run_logs.items():
        tag = os.path.basename(path)
        elos = defaultdict(list)              # cycle -> [elo rows]
        crit_by_target = defaultdict(list)    # (cycle, target_agent) -> [critique rows]
        rev_by_agent = {}                     # (cycle, agent) -> revision row
        for r in rows:
            ev = r.get("event")
            if ev == "elo":
                elos[r["cycle"]].append(r)
            elif ev == "critique":
                crit_by_target[(r["cycle"], r["target"])].append(r)
            elif ev == "revision":
                rev_by_agent[(r["cycle"], r["agent"])] = r

        for cycle, erows in elos.items():
            for er in erows:
                role, model, delta = er["role"], er.get("model"), er.get("delta", 0.0)
                rec = elo_by_role[role]
                rec["model"] = model
                rec["net_elo"] += delta
                rec["appearances"] += 1
                if delta <= 0:                # only a RISE has critiques to credit
                    continue
                crits = crit_by_target.get((cycle, er["agent"]), [])
                rev = rev_by_agent.get((cycle, er["agent"]))
                rev_gain = (rev["after_score"] - rev["before_score"]) \
                    if (rev and rev.get("accepted")) else 0.0
                share = delta / len(crits) if crits else 0.0
                for c in crits:
                    cr = critic_credit[c.get("critic_role", "?")]
                    cr["model"] = c.get("model")
                    cr["elo_credited"] += share
                    cr["critiques"] += 1
                    if rev_gain > 0:
                        cr["decisive_revisions"] += 1
                        decisive.append({
                            "run": tag, "cycle": cycle,
                            "winner_role": role, "winner_model": model,
                            "critic_role": c.get("critic_role", "?"),
                            "critic_model": c.get("model"),
                            "elo_delta": round(delta, 1),
                            "revision_gain": round(rev_gain, 2),
                            "critique": (c.get("text", "") or "")[:80],
                        })

    elo_by_role = {r: {"model": d["model"], "net_elo": round(d["net_elo"], 1),
                       "appearances": d["appearances"]}
                   for r, d in elo_by_role.items()}
    critic_credit = {r: {"model": d["model"], "elo_credited": round(d["elo_credited"], 2),
                         "critiques": d["critiques"],
                         "decisive_revisions": d["decisive_revisions"]}
                     for r, d in critic_credit.items()}
    decisive.sort(key=lambda x: (-x["elo_delta"], x["run"], x["cycle"],
                                 x["critic_role"], x["critique"]))
    return {"elo_by_role": elo_by_role, "critic_credit": critic_credit,
            "decisive_critiques": decisive[:20]}


def win_explanations(run_logs):
    """Per inner run: who WON (highest net Elo) and on which model, alongside the
    highest-scoring author. The score-leader is who reached the top formula; the
    Elo-leader is who won the most head-to-head rankings over the run."""
    out = []
    for path, rows in run_logs.items():
        net = defaultdict(float)
        model_of = {}
        for r in rows:
            if r.get("event") == "elo":
                net[r["role"]] += r.get("delta", 0.0)
                model_of[r["role"]] = r.get("model")
        if not net:
            continue
        top_role = max(net, key=lambda k: (net[k], k))
        score_role, score = winning_role(rows)
        out.append({"run": os.path.basename(path),
                    "top_elo_role": top_role, "top_elo_model": model_of.get(top_role),
                    "net_elo": round(net[top_role], 1),
                    "top_score_role": score_role, "top_score": score})
    out.sort(key=lambda x: x["run"])
    return out


# ------------------------------------------------------------------- top-level
def analyze(run_dir="runs", evolve_log="evolve_log.jsonl"):
    evolve_rows = _load_jsonl(evolve_log) if os.path.exists(evolve_log) else []
    run_logs = load_run_logs(run_dir, evolve_log)
    wins, win_detail = verified_wins_by_role(evolve_rows, run_dir)
    return {
        "run_dir": run_dir,
        "n_run_logs": len(run_logs),
        "verified_wins_by_role": dict(wins.most_common()),
        "verified_win_detail": win_detail,
        "revision_acceptance_by_role": revision_acceptance_by_role(run_logs),
        "critique_to_revision": critique_patterns_before_accepted(run_logs),
        "flavor_evolution": flavor_evolution(evolve_rows),
        "explanatory": {
            **explain_elo_attribution(run_logs),
            "win_explanations": win_explanations(run_logs),
        },
    }


def render(report) -> str:
    L = ["===== AGORA INTERPRETABILITY =====",
         f"run logs analyzed : {report['n_run_logs']}  (dir: {report['run_dir']})", ""]

    L.append("1) VERIFIED WINS BY ROLE  (who authored the Z3-proven formula)")
    wins = report["verified_wins_by_role"]
    if wins:
        for role, n in wins.items():
            L.append(f"     {role:22} {n}")
    else:
        L.append("     (none verified yet — expected for MOCK runs; real agents earn these)")

    L.append("\n2) REVISION ACCEPTANCE BY ROLE  (did critiques actually help?)")
    for role, s in sorted(report["revision_acceptance_by_role"].items(),
                          key=lambda kv: -kv[1]["rate"]):
        L.append(f"     {role:22} {s['rate']*100:5.0f}%   ({s['accepted']}/{s['total']})")

    L.append("\n3) CRITIQUE PATTERNS -> ACCEPTED REVISIONS")
    c = report["critique_to_revision"]
    L.append(f"     accepted revisions      : {c['n_accepted_revisions']}")
    L.append(f"     critic roles preceding  : {c['critic_roles']}")
    L.append(f"     salient words preceding : {list(c['top_words'])[:8]}")

    L.append("\n4) FLAVOR EVOLUTION (evolved vs baseline)")
    fe = report["flavor_evolution"]
    changed = [r for r, d in fe["diff"].items() if d["changed"]]
    L.append(f"     roles whose flavor changed : {changed or '(none)'}")
    if fe["correlated_with_verified_gain"]:
        L.append("     instruction changes that RAISED verified-count:")
        for c in fe["correlated_with_verified_gain"]:
            L.append(f"       step {c['step']} [{c['role']}] +{c['verified_delta']} verified")
            L.append(f"         - before: {c['before']}")
            L.append(f"         + after : {c['after']}")
    else:
        L.append("     (no mutation raised the verified-count — gate accepted nothing)")

    L.append("\n5) EXPLANATORY: WHY candidates won or lost  (Elo attribution)")
    ex = report.get("explanatory", {})
    L.append("   net Elo by proposer role (role -> model: net Elo over the run):")
    for role, d in sorted(ex.get("elo_by_role", {}).items(),
                          key=lambda kv: -kv[1]["net_elo"]):
        L.append(f"     {role:22} {d['net_elo']:+7.1f}   via {d['model']}")
    L.append("   critic credit (whose critiques moved Elo): "
             "role -> Elo credited / decisive revisions:")
    cc = ex.get("critic_credit", {})
    if cc:
        for role, d in sorted(cc.items(), key=lambda kv: -kv[1]["elo_credited"]):
            L.append(f"     {role:22} {d['elo_credited']:+7.2f}   "
                     f"({d['decisive_revisions']} decisive / {d['critiques']} critiques) "
                     f"via {d['model']}")
    else:
        L.append("     (no Elo-raising, revision-backed critiques observed)")
    dec = ex.get("decisive_critiques", [])
    if dec:
        L.append("   decisive critiques (a critique -> accepted revision -> Elo gain):")
        for c in dec[:5]:
            L.append(f"     [{c['run']} c{c['cycle']}] {c['critic_role']} ({c['critic_model']}) "
                     f"moved {c['winner_role']} +{c['elo_delta']} Elo "
                     f"(rev +{c['revision_gain']}): \"{c['critique']}\"")
    for w in ex.get("win_explanations", []):
        L.append(f"   [{w['run']}] Elo-winner {w['top_elo_role']} ({w['top_elo_model']}, "
                 f"net {w['net_elo']:+.1f}); top score by {w['top_score_role']} "
                 f"({w['top_score']})")
    return "\n".join(L)


def main(argv=None):
    p = argparse.ArgumentParser(description="agora #5: behavioral interpretability")
    p.add_argument("--run-dir", default="runs")
    p.add_argument("--evolve-log", default="evolve_log.jsonl")
    p.add_argument("--json", action="store_true", help="emit the raw report as JSON")
    args = p.parse_args(argv)
    report = analyze(args.run_dir, args.evolve_log)
    print(json.dumps(report, indent=2) if args.json else render(report))


if __name__ == "__main__":
    main()
