"""
Forecast API cost before you launch a colony.

Reproduces the bounded (O(N)) vs naive all-to-all (O(N^2)) cost curves so you
can see exactly what a given size will spend. Run:  python cost_projection.py

Assumptions (edit to taste): Sonnet generate+revise, Haiku critique.
  generate/revise: ~2000 in / 400 out tokens   (Sonnet 4.6: $3/$15 per MTok)
  critique:        ~1500 in / 300 out tokens   (Haiku 4.5:  $1/$5  per MTok)
Per-call cost: gen/revise ≈ $0.012, critique ≈ $0.003.
"""
GEN = 2000 / 1e6 * 3 + 400 / 1e6 * 15     # ≈ $0.012  (Sonnet)
CRIT = 1500 / 1e6 * 1 + 300 / 1e6 * 5     # ≈ $0.003  (Haiku)


def per_cycle(n, k, revision=True, naive=False):
    gen = n * GEN
    rev = n * GEN if revision else 0.0
    crit = (n * (n - 1) if naive else n * k) * CRIT
    return gen + rev + crit


def table(sizes=(3, 15, 50, 100), k=3, cycles=100):
    print(f"per-call: generate/revise=${GEN:.4f}  critique=${CRIT:.4f}")
    print(f"k_peers={k}  cycles={cycles}  (revision ON)\n")
    print(f"{'agents':>7} | {'bounded/cycle':>14} | {'bounded/run':>12} | "
          f"{'naive/cycle':>12} | {'naive/run':>11}")
    print("-" * 70)
    for n in sizes:
        bc = per_cycle(n, k, naive=False)
        nc = per_cycle(n, k, naive=True)
        print(f"{n:>7} | {bc:>13.3f}$ | {bc*cycles:>11.2f}$ | "
              f"{nc:>11.3f}$ | {nc*cycles:>10.2f}$")
    print("\nLevers that stack on the BOUNDED column:")
    print("  - Batch API:  -50%   (autonomous loop = perfect fit)")
    print("  - Prompt caching the shared system prompt: further cut on input side")
    print("  - Together they can roughly halve the bounded/run figures.")
    print("\nTakeaway: cost is set by the critique topology (bounded vs naive),")
    print("not by agent count alone. Keep k_peers small and growth stays linear.")


if __name__ == "__main__":
    table()
