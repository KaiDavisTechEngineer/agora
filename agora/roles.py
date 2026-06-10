"""
Role registry.

A role has a KIND that determines how the colony uses it:
  - proposer  : generates candidates each cycle (and revises them); also critiques peers
  - critic    : does NOT generate; only critiques proposers' candidates
  - validator : does NOT generate or critique; runs a per-cycle AUDIT pass over the
                leading candidate (e.g., leakage / novelty / too-good-to-be-true checks)

The default roster is the three base proposers (back-compatible). The quant roster
is a 12-role lineup designed for the strategy-research Oracle; its roles are
oracle-agnostic in MECHANICS (kind routing) even though their flavors talk quant —
they are ready to plug in once the backtest Oracle exists.
"""
from __future__ import annotations
from dataclasses import dataclass

PROPOSER, CRITIC, VALIDATOR = "proposer", "critic", "validator"


@dataclass(frozen=True)
class Role:
    name: str
    kind: str
    flavor: str            # appended to the Oracle's system prompt
    strength: float = 0.6  # mock local-search aggressiveness (proposers only)


def _r(name, kind, flavor, strength=0.6):
    return Role(name, kind, flavor, strength)

# --- base roles: oracle-agnostic, used by the default roster --------------------
_BASE = [
    _r("explorer",  PROPOSER, "Take a bold, unconventional swing far from the obvious.", 1.0),
    _r("optimizer", PROPOSER, "Make a small, careful refinement to the best known candidate.", 0.25),
    _r("skeptic",   PROPOSER, "Prioritize safety and reliability over peak performance.", 0.5),
    _r("critic",    CRITIC,   "Find the single strongest, most concrete reason this candidate fails."),
    _r("auditor",   VALIDATOR,"Audit the leading candidate for hidden risk, leakage, or "
                              "results that look too good to be true."),
]

# --- quant strategy-research roster (12 roles) ----------------------------------
_QUANT = [
    # proposers (7)
    _r("trend_hunter",        PROPOSER, "Propose momentum / streak-following strategy specs.", 0.8),
    _r("reversion_analyst",   PROPOSER, "Propose contrarian / mean-reversion strategy specs.", 0.8),
    _r("market_structure",    PROPOSER, "Propose edges from market mechanics: line movement, "
                                        "closing-line value, correlated picks.", 0.6),
    _r("feature_engineer",    PROPOSER, "Propose new predictive signals/features to feed strategies.", 0.7),
    _r("regime_conditioner",  PROPOSER, "Propose strategies gated on regime (sport, season, volatility).", 0.6),
    _r("ablation_designer",   PROPOSER, "Propose minimal variants that isolate what actually drives an edge.", 0.3),
    _r("portfolio_synth",     PROPOSER, "Propose how surviving strategies combine into a "
                                        "correlation-aware book.", 0.4),
    # critics (4)
    _r("overfitting_skeptic", CRITIC,   "Attack parameter count and curve-fitting to history."),
    _r("leakage_auditor",     CRITIC,   "Flag look-ahead bias, data unavailable at decision time, "
                                        "train/test contamination — and whether this edge is already "
                                        "captured by an existing strategy (novelty)."),
    _r("risk_of_ruin",        CRITIC,   "Attack bankroll survivability, drawdown, and sample-size sufficiency."),
    _r("vig_realist",         CRITIC,   "Attack whether the edge survives real vig, limits, and line movement."),
    # validator (1)
    _r("backtest_referee",    VALIDATOR,"Audit the leading strategy's backtest for the cleanest, "
                                        "most honest reading of its metrics."),
]

# --- formal-discovery roster (#1: Z3-verified Boolean-formula synthesis) --------
_FORMAL = [
    _r("constructor",         PROPOSER, "Build a candidate formula that matches the target spec.", 0.8),
    _r("minimizer",           PROPOSER, "Take a correct formula and make it smaller.", 0.3),
    _r("generalizer",         PROPOSER, "Find a structurally different formula for the same target.", 0.9),
    _r("counterexample_hunter", CRITIC, "Name the exact inputs where this formula disagrees with the target."),
    _r("triviality_skeptic",  CRITIC,   "Flag bloated or needlessly complex formulas; demand minimality."),
    _r("proof_referee",       VALIDATOR,"Formally verify the leading formula against the spec; report the verdict."),
]

ROLE_REGISTRY: dict[str, Role] = {r.name: r for r in (_BASE + _QUANT + _FORMAL)}

BASE_ROSTER = ["explorer", "optimizer", "skeptic"]
QUANT_ROSTER = [r.name for r in _QUANT]      # 12 roles
FORMAL_ROSTER = [r.name for r in _FORMAL]    # 6 roles (scale by duplicating proposers)


def get_role(name: str) -> Role:
    if name not in ROLE_REGISTRY:
        raise KeyError(f"unknown role '{name}'. Known: {sorted(ROLE_REGISTRY)}")
    return ROLE_REGISTRY[name]


def kind_of(name: str) -> str:
    return get_role(name).kind


def assign_roles(n: int, roster: list[str] | None = None) -> list[str]:
    """Map n agents onto roles. Default = base proposers, round-robin (back-compatible)."""
    pool = roster if roster else BASE_ROSTER
    return [pool[i % len(pool)] for i in range(n)]
