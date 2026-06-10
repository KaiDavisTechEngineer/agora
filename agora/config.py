"""Central configuration. One Config object flows through the whole run."""
from __future__ import annotations
from dataclasses import dataclass, field

# Current Anthropic list prices, USD per 1M tokens: (input, output)
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5":            (10.00, 50.00),
    "claude-opus-4-8":           (5.00, 25.00),
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-haiku-4-5-20251001": (1.00,  5.00),
}

GEN_MODEL   = "claude-sonnet-4-6"           # generate / revise -> real reasoning
GRUNT_MODEL = "claude-haiku-4-5-20251001"   # critique / summarize -> cheap

# The three role-KINDS that can each be assigned their own model (Phase 2).
ROLE_KINDS = ("proposer", "critic", "validator")


@dataclass
class Config:
    # --- society ---
    n_agents: int = 3            # 3 -> 15 -> 50 -> 100. Loop code never changes.
    k_peers: int = 3             # BOUNDED critique. Keep small (3-5) so cost stays O(N).
    survivor_frac: float = 0.4   # top fraction that seeds shared memory
    roster: list[str] | None = None  # explicit role lineup; None = base proposers round-robin

    # --- per-role-kind model selection (#2) ---
    # role-kind -> model id. None = single-model behaviour derived from the gen/grunt
    # tiers (proposer=gen_model, critic/validator=grunt_model) — see resolve_role_models.
    # A partial dict is allowed; unset kinds fall back to that default.
    role_models: dict | None = None

    # --- difficulty (frontier #1: how hard a verifiable target to attempt) ---
    difficulty: int = 1          # 1=k3 (easy) .. 3=k5 (hard); selects formula targets

    # --- pluggability (used by the self-improvement meta-loop, #6) ---
    oracle_kwargs: dict = field(default_factory=dict)     # passed to the Oracle constructor
    flavor_overrides: dict = field(default_factory=dict)  # role_name -> flavor; the evolvable "genome"
    quiet: bool = False                                   # mute stdout (inner meta-loop runs)

    # --- loop length & stopping (any condition halts gracefully) ---
    n_cycles: int = 12           # hard ceiling on cycles
    patience: int = 5            # stop if best score hasn't improved for this many cycles
    min_improvement: float = 0.5 # what counts as "improved"
    spend_cap_usd: float = 5.00  # HARD $ cap — run aborts the instant it is crossed
    halt_before_overspend: bool = False  # if set, refuse a call whose worst-case cost
                                         # would cross the cap (halt BEFORE the call);
                                         # the cap value itself is never changed (I2)
    stop_file: str = "STOP"      # `touch STOP` next to the run to halt after the current cycle

    # --- behaviour ---
    use_mock: bool = True        # True = no API key, no cost. False = real Claude.
    enable_revision: bool = True # Phase 1: agents revise their tune after reading critiques
    memory_keep: int = 6         # compressed memory: keep this many lessons per agent
    shared_keep: int = 8         # size of the shared "council" insight pool
    seed: int | None = 7         # RNG seed for reproducible mock runs (None = random)

    # --- persistence / reporting ---
    state_file: str = "colony_state.json"  # saved each cycle; enables resume
    resume: bool = True                    # pick up where a prior run left off
    log_file: str = "run_log.jsonl"        # one JSON event per line
    curve_file: str = "best_curve.csv"     # cycle,best_score for charting
    log_candidates: bool = True            # per-agent proposal/critique/revision events
                                           # (the observability layer; mute at 100 agents)

    gen_model: str = GEN_MODEL
    grunt_model: str = GRUNT_MODEL


def resolve_role_models(cfg: "Config") -> dict:
    """Map each role-KIND to the model that does its work.

    The DEFAULT reproduces the historical single-/two-tier behaviour EXACTLY:
      proposer  -> gen_model   (generate + revise — real reasoning)
      critic    -> grunt_model (critique — cheap)
      validator -> grunt_model (audit — cheap)
    `cfg.role_models` overrides per kind (partial dicts allowed). Every model the
    colony bills must be priced, so an unknown kind or an unpriced model is a config
    error (ValueError) — caught at construction, never silently mischarged.

    The model a role-kind uses is ORTHOGONAL to the Z3 verifier gate: which model
    proposed or audited a candidate never changes whether the Oracle verifies it.
    """
    base = {"proposer": cfg.gen_model, "critic": cfg.grunt_model,
            "validator": cfg.grunt_model}
    for kind, model in (cfg.role_models or {}).items():
        if kind not in base:
            raise ValueError(
                f"unknown role-kind '{kind}' in role_models; expected one of {ROLE_KINDS}")
        if model not in PRICES:
            raise ValueError(
                f"model '{model}' for role-kind '{kind}' has no price entry; "
                f"known: {sorted(PRICES)}")
        base[kind] = model
    return base
