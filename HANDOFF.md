# HANDOFF — agora real-run engagement state

Snapshot for whoever (or whichever session) picks this up. Full narrative in
`RESULTS.md` (Runs 1–12), README § "What 12 real-model runs established" (summary),
and `SESSION_SUMMARY.md` (build phases 0–5). Suite: **126 tests green**.

**Remote (public):** https://github.com/KaiDavisTechEngineer/agora — `origin/main`
tracks local `main`; push after committing so the backup stays current.

## Run status

| Run | Config | Outcome | Spend |
|---|---|---|---:|
| 1 | Haiku ×3, majority3 | no win; 35 parse-fallbacks (formatting bottleneck) | $0.2253 |
| 2 | + JSON prompt fix | no win; fallbacks 0; plateau 87.5 (reasoning) | $0.1463 |
| 3 | Haiku, and3 | **verified ✅** (first real Z3 certificate) | $0.1389 |
| 4 | Sonnet proposer, majority3 | **verified ✅** at optimum parsimony (4 ops, 116.0) | $0.2803 |
| 5 | Sonnet, parity4 @600 tok | no win; 90% truncated (emission bottleneck) | $0.5850 |
| 6 | Sonnet, parity4 @2000 tok | **verified ✅** at optimum (108.0); falsifier confirmed emission | $0.7331 |
| **7** | **Haiku, parity4 @2000 tok** | no win (reasoning-bound, mean out 209 tok) — **but FIRST ACCEPTED MUTATION** 🧬 | $0.2600 |
| **8** | **parity5 (k=5), Sonnet prop. @2000, cap $2.63** | **verified ✅ both evals** — 51 ops vs 36-op ref: correct but not minimal; minimality is the new frontier | $1.2840 |
| 9 | parity5 minimization probe: seed_best=51-op, Sonnet @2000, 6 cycles | **gap does NOT close** — flat 101.0, 0 improvements; agents copy the seed by cycle 4. Minimization at k=5 = Sonnet reasoning wall | $0.8467 |
| 10 | evolution battery: evolve(steps=4), Haiku ×3 @2000, majority3+parity4, from Run-7 genome (no extra steering — per Run 9 data), cap $2.00 | **evolved genome GENERALIZED: Haiku verified majority3 at optimum** ✅ (stock Haiku never did); all 4 mutations degraded fitness and were gate-rejected — local optimum, gate defends | $1.0191 |
| 11 | falsifier: stock Haiku @2000, majority3 (exact Run-10-baseline mirror, genome the only variable) | **87.5, NOT verified** → budget confound eliminated; **Run 10 headline airtight: the evolved genome caused the verified win** | $0.0723 |
| 12 | flavor-transfer test: Run-7 genome on Sonnet, parity5 (exact Run-8 mirror, genome the only variable) | **NEGATIVE transfer** — still verified, but 75 ops / 100.0 vs stock 51 ops / 101.0; the gate's own ordering would reject the port. Evolved strategies are model-contextual | $0.6236 |

**ENGAGEMENT COMPLETE.** Final: **$6.2146 total over 12 runs** (Haiku $2.5405 + Sonnet
$3.6741; original $5.00 envelope exceeded by $1.2146 under explicit authorization).
**7 runs ended with a Z3-verified best (3, 4, 6, 8, 9-seed, 10, 12) across 4 distinct
targets; 1 gate-accepted mutation — proven causal for Haiku (Run 11 A/B),
local-optimal under further mutation (Run 10), and negative-transfer to Sonnet
(Run 12): self-improvement is real but contextual, and the gate is what keeps it
honest.** I1–I4 held on all 12 runs; zero false certificates in ~1,700 real calls.
Full reconciliation: RESULTS.md § Run 12. No runs in flight; no background processes.
Committed snapshot of the accepted genome: `genome_run7_first_accept.json`.

**Run 7 detail (the milestone):** the trickle step accepted its mutation for the first
time in seven runs. A Sonnet-authored rewrite of the `constructor` flavor improved
Oracle fitness `(0, 62.5) → (0, 81.25)` — the **mutated-genome eval climbed 75.0 → 81.25**
(cycles 1→2, then held) vs the baseline genome's 62.5 plateau. Accepted via strict
`is_improvement`, persisted with an `ACCEPT` audit entry and history record.

**Genome snapshot locations** (first real evolved genome):
- `/tmp/agora_keep/genome_run7_first_accept.json` (volatile — /tmp is cleaned on reboot/periodically)
- **durable copy committed in-repo: `genome_run7_first_accept.json`** (root, commit `2ec1e23`)
- live copy also still at `/tmp/agora_real/genome.json` until Run 8 wipes the workdir

## Spend

**Cumulative through Run 9: $4.4996** (vs the original $5.00 envelope: 90%).
**Authorization update (2026-06-11):** user directed "money is not the constraint —
raise the cap as needed under the fit rule" and explicitly authorized Runs 9 + 10;
Run 10 (cap $2.00) will exceed the original envelope with that authorization on
record. Cap machinery (`--cap` + `halt_before_overspend`) and I1–I4 unchanged;
cumulative tracked and reported against both the original envelope and actuals.

## Invariants I1–I4 — status: all held, every run

- **I1 (gate):** never weakened. 3 true Z3 certificates (Runs 3/4/6); every near-miss
  (87.5, 81.25) correctly rejected; nothing falsely certified, ever.
- **I2 (cap):** every run ≤ its per-run cap; per-model breakdowns reconcile exactly to
  the single global tracker; the pre-call guard has never had to fire.
- **I3 (mutation surface):** only allowlisted `flavor` mutations proposed/accepted;
  reward-hack vetting untouched; `proposer_max_tokens` (Run 6's knob) is post-gate
  plumbing only.
- **I4 (re-pass the gate):** exercised on BOTH sides now — six gate-rejections
  (Runs 1–6) and one genuine gate-passed accept (Run 7).

## Exact next steps

> **Status update: steps 1–2 are DONE** (Run 8 launched, verified, documented,
> committed). Remaining: step 3 — proposals only — and the optional $0 follow-ups.
> Kept below for the record of what was queued at handoff time.

1. ~~**Launch Run 8**~~ *(done — verified ✅, see RESULTS.md)*:
   ```bash
   cd ~/Downloads/agora && rm -rf /tmp/agora_real && mkdir -p /tmp/agora_real
   python3 -m agora.integrate --real --difficulty 3 --target parity5 --cap 2.63 \
     --proposer-model  claude-sonnet-4-6 \
     --critic-model    claude-haiku-4-5-20251001 \
     --validator-model claude-haiku-4-5-20251001 \
     --proposer-max-tokens 2000 \
     --genome /tmp/agora_real/genome.json --out-dir /tmp/agora_real/runs \
     --evolve-log /tmp/agora_real/evolve_log.jsonl
   ```
   Expect ~$0.8–1.5; parity5 reference = 36 ops (~430 JSON tokens, fits 2000).
   Runtime note: at 2000-token budgets an eval takes ~4–5 min and `evolve_log.jsonl`
   is silent between evals — **that is not a hang** (see RESULTS.md Run 7 note); check
   `runs/*.jsonl` mtimes for liveness.
2. **Document as Run 8** in RESULTS.md (same discipline: verified/best vs Run 6's
   108-at-optimum, parse fallbacks, mean output tokens, spend reconciliation, I1–I4),
   scoped commit. Task #26 in the session task list tracks this.
3. **Then stop and report** — that exhausts the recommended sequence; further runs
   (e.g. a genome-evolution battery run exercising more accepts, est ~$1+) are
   **proposals only** unless the user authorizes.
4. Optional $0 follow-ups flagged along the way: explicit SDK `timeout=` + per-call
   heartbeat for long-budget runs; force-add policy decision for evolved genomes.

## Background shells / process state (as of this handoff)

- **No background processes running:** `pgrep` shows no `agora.integrate`, no waiter
  loops, no monitors. All ten background tasks from this engagement completed.
- **Outputs persisted to disk:** harness task logs in
  `/private/tmp/claude-501/-Users-kaidavis/850399b4-…/tasks/*.output`; run artifacts in
  `/tmp/agora_real/` (Run 7's stdout.log, evolve_log.jsonl, runs/, genome.json) and
  `/tmp/agora_keep/`. **All of these are under /tmp and volatile** (macOS cleans on
  reboot / ~3-day idle). Everything load-bearing is already durable in-repo:
  RESULTS.md, the committed genome snapshot, and git history.
