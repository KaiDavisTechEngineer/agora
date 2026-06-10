"""Run logging: a JSONL event stream, a CSV curve for charting, a summary."""
from __future__ import annotations
import json, csv, os


class Reporter:
    def __init__(self, cfg):
        self.cfg = cfg
        self.curve_rows: list[tuple[int, float]] = []
        # truncate the JSONL log at the start of a fresh (non-resumed) run
        if not (cfg.resume and os.path.exists(cfg.state_file)):
            open(cfg.log_file, "w").close()

    def event(self, kind: str, **data) -> None:
        with open(self.cfg.log_file, "a") as f:
            f.write(json.dumps({"event": kind, **data}) + "\n")

    def cycle(self, n: int, best: float, top: float, cost_summary: str) -> None:
        self.curve_rows.append((n, best))
        self.event("cycle", cycle=n, best=best, top=top, cost=cost_summary)

    # ---- candidate-level observability (the "read it like a code review" layer) ----
    # `model` is the model that did the work (Phase 2 routing) — recorded so the
    # interpretability layer (#5) can attribute "which role/model contributed what".
    def proposal(self, cycle, agent_id, role, candidate, score, model=None) -> None:
        if self.cfg.log_candidates:
            self.event("proposal", cycle=cycle, agent=agent_id, role=role,
                       candidate=candidate, score=score, model=model)

    def critique(self, cycle, critic_id, critic_role, target_id, text, model=None) -> None:
        if self.cfg.log_candidates:
            self.event("critique", cycle=cycle, critic=critic_id, critic_role=critic_role,
                       target=target_id, text=text, model=model)

    def revision(self, cycle, agent_id, role, before, before_score,
                 after, after_score, accepted, model=None) -> None:
        if self.cfg.log_candidates:
            self.event("revision", cycle=cycle, agent=agent_id, role=role,
                       before=before, before_score=before_score,
                       after=after, after_score=after_score, accepted=accepted,
                       model=model)

    def audit(self, cycle, agent_id, role, candidate, text, model=None) -> None:
        if self.cfg.log_candidates:
            self.event("audit", cycle=cycle, auditor=agent_id, role=role,
                       candidate=candidate, text=text, model=model)

    def elo(self, cycle, agent_id, role, model, score, rank,
            elo_before, elo_after, delta) -> None:
        """Per-cycle Elo movement for a proposer — the explanatory layer (#5) ties a
        positive delta back to the critiques that produced the accepted revision."""
        if self.cfg.log_candidates:
            self.event("elo", cycle=cycle, agent=agent_id, role=role, model=model,
                       score=score, rank=rank, elo_before=elo_before,
                       elo_after=elo_after, delta=delta)

    def write_curve(self) -> None:
        with open(self.cfg.curve_file, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["cycle", "best_score"])
            w.writerows(self.curve_rows)

    def finalize(self, summary: dict) -> None:
        self.write_curve()
        self.event("final", **summary)
