"""Central configuration. One Config object flows through the whole run."""
from __future__ import annotations
from dataclasses import dataclass, field

# Current Anthropic list prices, USD per 1M tokens: (input, output)
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8":           (5.00, 25.00),
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-haiku-4-5-20251001": (1.00,  5.00),
}

GEN_MODEL   = "claude-sonnet-4-6"           # generate / revise -> real reasoning
GRUNT_MODEL = "claude-haiku-4-5-20251001"   # critique / summarize -> cheap


@dataclass
class Config:
    # --- society ---
    n_agents: int = 3            # 3 -> 15 -> 50 -> 100. Loop code never changes.
    k_peers: int = 3             # BOUNDED critique. Keep small (3-5) so cost stays O(N).
    survivor_frac: float = 0.4   # top fraction that seeds shared memory
    roster: list[str] | None = None  # explicit role lineup; None = base proposers round-robin

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
