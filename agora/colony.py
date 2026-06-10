"""
The colony loop. Depends only on the Oracle ABC, so it is domain-agnostic.

One cycle:
  1. GENERATE  - each agent proposes a candidate              (gen model)
  2. DEBATE    - each agent critiques K peers  [BOUNDED -> O(N)]   (grunt model)
  3. REVISE    - each agent rewrites its candidate using the      (gen model)
                 critiques it received                  [Phase 1]
  4. VALIDATE  - the Oracle scores every candidate         [free]
  5. RANK      - Elo updated on adjacent finishers   [O(N), not O(N^2)]
  6. REMEMBER  - update global best; high-Elo tunes seed the shared
                 council pool; agents store compressed lessons   [Phase 1/2]

Stops gracefully on ANY of: spend cap, cycle ceiling, convergence (patience),
or an external STOP file. State is saved every cycle so runs resume.
"""
from __future__ import annotations
import os, json, re, random

from .config import Config
from .cost import CostTracker, SpendCapExceeded
from .oracles import ORACLES, Oracle
from .agent import Agent, assign_roles, update_elo
from .roles import PROPOSER, CRITIC, VALIDATOR
from .llm import make_client
from .reporting import Reporter


def _parse_candidate(text: str, oracle: Oracle) -> dict:
    text = re.sub(r"```(json)?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return oracle.normalize(json.loads(m.group(0))) if m else oracle.normalize({})
    except (json.JSONDecodeError, ValueError):
        return oracle.normalize({})


class Colony:
    def __init__(self, cfg: Config, oracle_name: str = "rotary",
                 cost_tracker: CostTracker | None = None):
        self.cfg = cfg
        self.oracle: Oracle = ORACLES[oracle_name](**cfg.oracle_kwargs)
        self.oracle_name = oracle_name
        self.rng = random.Random(cfg.seed)

        self.agents: list[Agent] = []
        self.shared: list[str] = []          # council insight pool
        self.global_best: dict | None = None
        self.global_best_score: float = -1e9
        self.history: list[float] = []
        self.start_cycle = 1
        starting = {"usd": 0.0, "calls": 0, "in_tok": 0, "out_tok": 0}

        if cfg.resume and os.path.exists(cfg.state_file):
            starting = self._load_state()
        else:
            roles = assign_roles(cfg.n_agents, cfg.roster)
            self.agents = [Agent(id=i, role=roles[i]) for i in range(cfg.n_agents)]
        # apply the evolvable genome: role -> flavor override (no-op if empty)
        for a in self.agents:
            a.flavor_override = cfg.flavor_overrides.get(a.role)

        # A shared CostTracker (passed in) makes the spend cap a single GLOBAL budget
        # across many colony runs — exactly what the #6 meta-loop needs. When absent,
        # each colony meters itself (and can resume a prior balance from disk).
        self.cost = cost_tracker or CostTracker(
            cfg.spend_cap_usd, starting["usd"], starting["calls"],
            starting["in_tok"], starting["out_tok"])
        self.client = make_client(cfg, self.oracle, self.rng)
        self.reporter = Reporter(cfg)

    # ------------------------------------------------------------------ loop
    def run(self) -> dict:
        cfg = self.cfg
        opt = self.oracle.optimum_estimate()
        self.reporter.event("start", oracle=self.oracle_name, n_agents=cfg.n_agents,
                            k_peers=cfg.k_peers, cap=cfg.spend_cap_usd,
                            model="MOCK" if cfg.use_mock else cfg.gen_model, optimum=opt)
        self._say(f"[agora] oracle={self.oracle_name} agents={cfg.n_agents} "
                  f"k_peers={cfg.k_peers} cap=${cfg.spend_cap_usd:.2f} "
                  f"model={'MOCK' if cfg.use_mock else cfg.gen_model}")
        self._say(f"        optimum ≈ {opt}  (resuming at cycle {self.start_cycle})\n")

        stop_reason = "cycle_ceiling"
        since_improved = 0
        try:
            for cycle in range(self.start_cycle, cfg.n_cycles + 1):
                if os.path.exists(cfg.stop_file):
                    stop_reason = "stop_file"
                    self._say(f"[agora] {cfg.stop_file} detected — halting after cycle {cycle-1}.")
                    break

                improved = self._cycle(cycle)
                since_improved = 0 if improved else since_improved + 1

                self._save_state(cycle)
                self.reporter.cycle(cycle, round(self.global_best_score, 2),
                                    round(self.history[-1] if self.history else 0, 2),
                                    self.cost.summary())
                self._say(f"cycle {cycle:3d} | best={self.global_best_score:7.1f} | "
                          f"{self.cost.summary()}")

                if since_improved >= cfg.patience:
                    stop_reason = "converged"
                    self._say(f"[agora] no improvement for {cfg.patience} cycles — converged.")
                    break
        except SpendCapExceeded as e:
            stop_reason = "spend_cap"
            self._say(f"\n[agora] HALTED: {e}")

        # the formal certificate: for verifiable oracles, is the best PROVEN correct?
        verified = self.oracle.verify(self.global_best) if self.global_best is not None else None
        summary = {
            "oracle": self.oracle_name, "stop_reason": stop_reason,
            "best": self.global_best, "best_score": round(self.global_best_score, 2),
            "verified": verified,
            "optimum_estimate": opt, "gap": round(opt - self.global_best_score, 2),
            "cycles_run": len(self.history), "cost": self.cost.as_dict(),
            "elo_leaderboard": sorted(
                [(a.id, a.role, round(a.elo, 1)) for a in self.agents],
                key=lambda x: -x[2]),
        }
        self.reporter.finalize(summary)
        self._print_summary(summary)
        return summary

    # --------------------------------------------------------------- a cycle
    def _cycle(self, cycle: int) -> bool:
        cfg = self.cfg
        proposers  = [a for a in self.agents if a.kind == PROPOSER]
        critiquers = [a for a in self.agents if a.kind in (PROPOSER, CRITIC)]
        validators = [a for a in self.agents if a.kind == VALIDATOR]
        if not proposers:
            raise ValueError("roster has no proposer roles — nobody can generate candidates.")

        # 1) GENERATE — proposers only
        proposals: dict[int, dict] = {}
        for a in proposers:
            sys = self.oracle.system_prompt(a.flavor)
            r = self.client.complete(cfg.gen_model, sys, a.context(self.global_best, self.shared))
            self.cost.charge(cfg.gen_model, r.in_tok, r.out_tok)
            cand = _parse_candidate(r.text, self.oracle)
            a.last_candidate = cand
            proposals[a.id] = cand
            self.reporter.proposal(cycle, a.id, a.role, cand, self.oracle.score(cand))

        # 2) DEBATE — bounded: each critiquer reviews K proposer-candidates (never its own)
        received: dict[int, list[str]] = {aid: [] for aid in proposals}
        for a in critiquers:
            targets = [pid for pid in proposals if pid != a.id]
            if not targets:
                continue
            for pid in self.rng.sample(targets, k=min(cfg.k_peers, len(targets))):
                msg = self.oracle.critique_prompt(proposals[pid])
                sys = "You are a rigorous critic. " + a.flavor
                r = self.client.complete(cfg.grunt_model, sys, msg, max_tokens=160)
                self.cost.charge(cfg.grunt_model, r.in_tok, r.out_tok)
                received[pid].append(r.text.strip())
                self.reporter.critique(cycle, a.id, a.role, pid, r.text.strip())

        # 3) REVISE (Phase 1) — proposers rewrite using the critiques they received
        if cfg.enable_revision:
            for a in proposers:
                crits = received.get(a.id, [])
                if not crits:
                    continue
                msg = self.oracle.revise_prompt(proposals[a.id], crits)
                r = self.client.complete(cfg.gen_model, self.oracle.system_prompt(a.flavor), msg)
                self.cost.charge(cfg.gen_model, r.in_tok, r.out_tok)
                revised = _parse_candidate(r.text, self.oracle)
                original = proposals[a.id]
                before_score = self.oracle.score(original)
                after_score = self.oracle.score(revised)
                accepted = after_score >= before_score
                if accepted:                       # keep only if at least as good
                    proposals[a.id] = revised
                    a.last_candidate = revised
                self.reporter.revision(cycle, a.id, a.role, original, before_score,
                                       revised, after_score, accepted)

        # 4) VALIDATE + 5) RANK  (proposer candidates only)
        scored = sorted(((self.oracle.score(t), aid, t) for aid, t in proposals.items()),
                        reverse=True)
        by_id = {a.id: a for a in self.agents}
        for i in range(len(scored) - 1):
            update_elo(by_id[scored[i][1]], by_id[scored[i + 1][1]])

        top_score, _, top_tune = scored[0]

        # 5b) AUDIT — validators each review the leading candidate (no score change yet;
        #     this is where a leakage/novelty gate becomes a scored dimension later)
        for a in validators:
            msg = (f"{a.flavor}\nLeading candidate: {json.dumps(top_tune)} "
                   f"(score {top_score}). Audit it in 1-2 sentences.")
            r = self.client.complete(cfg.grunt_model, "You are an auditor.", msg, max_tokens=160)
            self.cost.charge(cfg.grunt_model, r.in_tok, r.out_tok)
            self.reporter.audit(cycle, a.id, a.role, top_tune, r.text.strip())

        # 6) REMEMBER — global best + shared pool + compressed memory
        improved = top_score > self.global_best_score + cfg.min_improvement
        if top_score > self.global_best_score:
            self.global_best_score, self.global_best = top_score, top_tune
        self.history.append(self.global_best_score)

        cutoff = max(1, int(len(scored) * cfg.survivor_frac))
        survivors = scored[:cutoff]
        for s, aid, t in survivors:
            note = f"score {s}: {json.dumps(t)}"
            if note not in self.shared:
                self.shared.append(note)
        self.shared = self.shared[-cfg.shared_keep:]

        for s, aid, t in scored:
            kept = "kept" if (s, aid, t) in survivors else "cut"
            by_id[aid].remember(f"{kept} -> {s}: {json.dumps(t)}", cfg.memory_keep)
        return improved

    # ------------------------------------------------------------ persistence
    def _save_state(self, next_cycle_done: int) -> None:
        state = {
            "oracle": self.oracle_name,
            "next_cycle": next_cycle_done + 1,
            "agents": [a.to_dict() for a in self.agents],
            "shared": self.shared,
            "global_best": self.global_best,
            "global_best_score": self.global_best_score,
            "history": self.history,
            "cost": self.cost.as_dict(),
        }
        tmp = self.cfg.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, self.cfg.state_file)   # atomic — safe if killed mid-write

    def _load_state(self) -> dict:
        with open(self.cfg.state_file) as f:
            s = json.load(f)
        self.agents = [Agent.from_dict(d) for d in s["agents"]]
        self.shared = s.get("shared", [])
        self.global_best = s.get("global_best")
        self.global_best_score = s.get("global_best_score", -1e9)
        self.history = s.get("history", [])
        self.start_cycle = s.get("next_cycle", 1)
        return s.get("cost", {"usd": 0.0, "calls": 0, "in_tok": 0, "out_tok": 0})

    # --------------------------------------------------------------- printing
    def _say(self, msg: str) -> None:
        """stdout, unless quiet (the meta-loop runs many inner colonies silently)."""
        if not self.cfg.quiet:
            print(msg)

    def _print_summary(self, s: dict) -> None:
        if self.cfg.quiet:
            return
        print("\n=== RESULT ===")
        print(f"stop reason : {s['stop_reason']}")
        print(f"best        : {s['best']} -> {s['best_score']} (optimum ≈ {s['optimum_estimate']})")
        if s.get("verified") is not None:
            print(f"verified    : {s['verified']}   (Z3 formal certificate)")
        print(f"gap         : {s['gap']}")
        print(f"cycles      : {s['cycles_run']}")
        print(f"spend       : ${s['cost']['usd']:.4f} over {s['cost']['calls']} calls")
        print(f"elo board   : {s['elo_leaderboard']}")
