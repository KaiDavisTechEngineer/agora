"""Metering + the hard spend cap. Every model call goes through charge()."""
from __future__ import annotations
from .config import PRICES


class SpendCapExceeded(Exception):
    """Raised the instant cumulative spend crosses the cap. Halts the run."""


class CostTracker:
    def __init__(self, cap_usd: float, starting_usd: float = 0.0,
                 starting_calls: int = 0, starting_in: int = 0, starting_out: int = 0):
        self.cap = cap_usd
        self.usd = starting_usd          # may be > 0 when resuming a prior run
        self.calls = starting_calls
        self.in_tok = starting_in
        self.out_tok = starting_out

    def charge(self, model: str, in_tok: int, out_tok: int) -> None:
        pin, pout = PRICES[model]
        self.usd += in_tok / 1e6 * pin + out_tok / 1e6 * pout
        self.calls += 1
        self.in_tok += in_tok
        self.out_tok += out_tok
        if self.usd >= self.cap:
            raise SpendCapExceeded(
                f"Spend cap ${self.cap:.2f} reached (spent ${self.usd:.4f} "
                f"over {self.calls} calls)."
            )

    def as_dict(self) -> dict:
        return {"usd": self.usd, "calls": self.calls,
                "in_tok": self.in_tok, "out_tok": self.out_tok}

    def summary(self) -> str:
        return (f"${self.usd:.4f} | {self.calls} calls | "
                f"{self.in_tok:,} in / {self.out_tok:,} out tok")
