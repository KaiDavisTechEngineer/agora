# HANDOFF — agora real-run engagement state

Snapshot for whoever (or whichever session) picks this up. Full narrative in
`RESULTS.md` (Runs 1–7) and `SESSION_SUMMARY.md` (build phases 0–5). Suite: **124
tests green**, tree clean at commit `2ec1e23`.

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

**Cumulative: $3.6529 / $5.00 (73%); $1.3471 remaining.**
Standing rules (also in memory `agora-spend-authorization`): $5.00 total envelope,
runs pre-approved within it; default per-run cap $3.50, but **fit-don't-skip** — the
next run's cap must be **$1.34**. Per-run `--cap` + `halt_before_overspend` machinery
unchanged. **The authorized sequence is complete** — further runs are proposals only
(see RESULTS.md Run 8 § for the three candidates: minimization probe, evolution
battery, or stop).

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
