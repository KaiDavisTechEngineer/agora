"""Metering + the hard spend cap. Every model call goes through charge()."""
from __future__ import annotations
from .config import PRICES


class SpendCapExceeded(Exception):
    """Raised the instant cumulative spend crosses the cap. Halts the run."""


def _blank_model_row() -> dict:
    return {"usd": 0.0, "calls": 0, "in_tok": 0, "out_tok": 0}


class CostTracker:
    def __init__(self, cap_usd: float, starting_usd: float = 0.0,
                 starting_calls: int = 0, starting_in: int = 0, starting_out: int = 0,
                 starting_by_model: dict | None = None):
        self.cap = cap_usd
        self.usd = starting_usd          # may be > 0 when resuming a prior run
        self.calls = starting_calls
        self.in_tok = starting_in
        self.out_tok = starting_out
        # per-model breakdown: model -> {usd, calls, in_tok, out_tok}. This is purely
        # ATTRIBUTION — the cap below is still a single GLOBAL budget over the total.
        self.by_model: dict[str, dict] = {}
        for m, row in (starting_by_model or {}).items():
            self.by_model[m] = {**_blank_model_row(), **row}

    def charge(self, model: str, in_tok: int, out_tok: int) -> None:
        pin, pout = PRICES[model]
        delta = in_tok / 1e6 * pin + out_tok / 1e6 * pout
        self.usd += delta
        self.calls += 1
        self.in_tok += in_tok
        self.out_tok += out_tok
        row = self.by_model.setdefault(model, _blank_model_row())
        row["usd"] += delta
        row["calls"] += 1
        row["in_tok"] += in_tok
        row["out_tok"] += out_tok
        if self.usd >= self.cap:          # single global ceiling across ALL models
            raise SpendCapExceeded(
                f"Spend cap ${self.cap:.2f} reached (spent ${self.usd:.4f} "
                f"over {self.calls} calls)."
            )

    def as_dict(self) -> dict:
        return {"usd": self.usd, "calls": self.calls,
                "in_tok": self.in_tok, "out_tok": self.out_tok,
                "by_model": self.by_model}

    def summary(self) -> str:
        return (f"${self.usd:.4f} | {self.calls} calls | "
                f"{self.in_tok:,} in / {self.out_tok:,} out tok")
