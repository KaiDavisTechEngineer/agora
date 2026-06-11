# Verifier-gated self-improvement on real models: what 12 runs established

*Condensed record of the agora real-model engagement (Runs 1–12, ~$6.21, ~1,700 API
calls). Full per-run data: `RESULTS.md`. State snapshot: `HANDOFF.md`.*

## Thesis

agora's load-bearing idea is that self-improvement is only safe to build on a fitness
signal that **verifies** rather than judges. This engagement tested that idea end-to-end
on real models — and it held: across 12 runs the Z3 gate issued **zero false
certificates**, accepted exactly **one** strategy mutation (which was later proven
causal for a verified discovery), and rejected everything else — including, decisively,
the cases where rejecting was the intelligent thing to do.

Along the way, single-variable experiments turned three plausible-sounding failure
narratives into a precise **bottleneck ladder**: what looked like "the model can't do
it" was first an output-*formatting* problem (Run 2: strict-JSON prompt → 35 parse
failures → 0), then a *reasoning* problem (Run 4: Haiku→Sonnet swap, nothing else →
majority3 verified at optimum), then an output-*budget* problem (Run 6: 600→2000
tokens, nothing else → parity4 verified at optimum). Verified discovery was pushed
through 5-input parity, where one genuine wall remains: Sonnet finds *correct* parity5
formulas but cannot *minimize* them (Runs 8–9).

## The three single-variable experiments (the genome trilogy)

Run 7 produced the engagement's central artifact: the first gate-accepted mutation — a
rewritten `constructor` instruction that improved Haiku's Oracle fitness on parity4
(62.5 → 81.25). Three controlled experiments then mapped exactly what that evolved
genome is:

1. **It is causal (Run 11).** Haiku running the evolved genome verified `majority3` at
   optimum parsimony — something stock Haiku never did. The falsifier: an identical
   run (same model, budget, seed, target) with stock flavors reproduced the historical
   87.5 plateau exactly. One variable, one conclusion: *the accepted mutation, and
   nothing else, caused the verified win* — on a target it was never trained on.
2. **It is locally optimal, and the gate defends it (Run 10).** Four further real
   mutations each *degraded* fitness — every one lost the verified win — and the
   verified-count-first gate rejected all four. The audit trail reads `ACCEPT,
   REJECT ×4`: one earned improvement, defended.
3. **It does not transfer (Run 12).** The same flavor ported to Sonnet on parity5 made
   output *worse* on exactly the dimension its words demand (75 ops vs 51, still
   verified). And by the gate's own ordering, `(1, 100.0) < (1, 101.0)` — the gate that
   accepted this flavor for Haiku would reject porting it to Sonnet.

Together: **self-improvement here is real, causal, and contextual.** What the gate
certifies is "better *for this colony*" — and because every adoption requires a fitness
re-pass in its deployment context (invariant I4), the architecture itself prevents the
one mistake these results invite: assuming an evolved strategy generalizes.

## Final reconciliation

- **Spend:** $6.2146 total (Haiku $2.5405 + Sonnet $3.6741; reconciles exactly against
  per-run global trackers). Original $5.00 envelope exceeded by $1.2146 under explicit
  user authorization; every run stayed ≤ its per-run cap and the pre-call budget guard
  never had to fire.
- **Outcomes:** 7 runs ended with a Z3-verified best, across 4 targets
  (`and3`, `majority3`, `parity4`, `parity5`); 1 gate-accepted mutation, fully
  characterized by the trilogy above; 3 bottlenecks diagnosed and 2 of them removed.
- **Invariants I1–I4: held on all 12 runs.** The gate was never weakened or bypassed;
  the cap machinery was never altered; the mutation surface never escaped its
  allowlist; nothing persisted without re-passing the gate.
- **Test suite:** 50 → 126, green throughout; every behavior change landed with tests
  before the run that depended on it.
