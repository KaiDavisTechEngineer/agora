# RESULTS — first real-model integrated run

**Command (option a — Haiku in all three colony roles; Sonnet only for the meta flavor-rewrite):**
```bash
python -m agora.integrate --real --difficulty 1 --cap 0.50 \
  --proposer-model  claude-haiku-4-5-20251001 \
  --critic-model    claude-haiku-4-5-20251001 \
  --validator-model claude-haiku-4-5-20251001 \
  --genome /tmp/agora_real/genome.json --out-dir /tmp/agora_real/runs \
  --evolve-log /tmp/agora_real/evolve_log.jsonl
```
Target `majority3` (difficulty 1). FORMAL roster (3 proposers / 2 critics / 1 validator),
`k_peers=3`, `inner_cycles=4`, `halt_before_overspend=ON`. Exit code 0.

---

## 1. Did the Oracle certify a verified win?

**No.** Z3 certified nothing this run (`verified: False` on both evaluations).

- Best candidate (both current and mutated genome): `(b AND (a OR c))`
  ```json
  {"op": "and", "args": [{"var": "b"}, {"op": "or", "args": [{"var": "a"}, {"var": "c"}]}]}
  ```
- Score **87.5 / 100** — correct on 7 of 8 truth-table rows, **wrong on row `a=1,b=0,c=1`**
  (majority = 1, but `b AND …` = 0). Because it is not exactly correct on every row, Z3
  rejects it (`verify → False`). The gate behaved correctly: a not-quite-right formula is
  **not** certified. Real Haiku got close on an easy target but never nailed all 8 rows in
  4 cycles.

**Gate integrity (I1):** no candidate was ever falsely certified — every `eval` event
records `verified: False`, and nothing unverified was persisted as a discovery.

---

## 2. Trickle self-improvement outcome

**Rejected** — `decision: reject`, `reason: "no verifier-gated improvement"`,
`accepted=False`. The real Haiku rewrote the `constructor` flavor into a sharper
minimization instruction, the mutated genome was **evaluated under the same Z3 gate**
(I4), tied the current genome on fitness `(verified=0, score=87.5)`, and so was **not**
persisted. The genome stayed at baseline; rotation advanced `0 → 1`.

Audit trail (`genome.json` → `audit`, 1 entry, 0 accepted):
```json
{
  "when": 0, "phase": "trickle", "decision": "reject", "target": "majority3",
  "role": "constructor",
  "mutation": {
    "kind": "flavor", "role": "constructor",
    "value": "Role: constructor. Synthesize the **smallest** Boolean formula (fewest
              operators/literals) that is **exactly correct on every single row** of the
              truth table—verify each row explicitly and ruthlessly minimize size before
              outputting."
  },
  "reason": "no verifier-gated improvement",
  "cur_fitness": [0, 87.5], "cand_fitness": [0, 87.5]
}
```
This is the self-improvement loop working as designed: a plausible flavor rewrite that
does not move the **verified** fitness is gated out, not accepted on vibes.

---

## 3. Explanatory attribution (which critic moved which proposer's Elo)

First run of the explanatory layer over **real** agent reasoning (mock critiques were
canned; these are genuine Haiku analyses).

**Net Elo by proposer role (all via `claude-haiku-4-5-20251001`):**
| proposer | net Elo | model |
|---|---|---|
| **minimizer** | **+36.3** (Elo winner) | haiku |
| generalizer | −10.3 | haiku |
| constructor | −26.1 | haiku |

**Critic credit — whose critiques moved Elo (decisive revisions / critiques):**
| critic role | Elo credited | decisive | via |
|---|---|---|---|
| counterexample_hunter | +24.98 | 7 / 15 | haiku |
| triviality_skeptic | +24.98 | 7 / 15 | haiku |
| generalizer (as critic) | +21.43 | 7 / 9 | haiku |
| constructor (as critic) | +18.82 | 4 / 12 | haiku |
| minimizer (as critic) | +9.70 | 3 / 9 | haiku |

**Reading:** the `counterexample_hunter` and `triviality_skeptic` critics were the
biggest Elo movers — each credited with 7 decisive critiques that drove an accepted,
score-raising revision. Their critiques most often lifted **`minimizer`**, the run's
Elo winner (e.g. at cycle 2, critiques from counterexample_hunter / triviality_skeptic /
constructor each moved `minimizer` +12.8 Elo on a +12.5 revision gain). Revision
acceptance was **100% (8/8)** for every proposer — real critiques consistently produced
upward revisions, which the mock can't exhibit.

Win explanations: in both inner runs the **Elo-winner was `minimizer`** while the
**top single score (87.5) was authored by `constructor`** — i.e. minimizer won the most
head-to-head rankings, constructor reached the best formula.

---

## 4. Spend, per-model breakdown, reconciliation against the cap

| | calls | spend |
|---|---:|---:|
| `claude-haiku-4-5-20251001` (3 colony roles) | 152 | $0.2243 |
| `claude-sonnet-4-6` (meta flavor-rewrite) | 1 | $0.0010 |
| **total** | **153** | **$0.2253** |

- **Reconciliation:** `0.2243 + 0.0010 = 0.2253` = global total ✓ (per-model sums match
  the single global tracker exactly).
- **Against the cap:** **$0.2253 / $0.50 = 45% used.** The cap never bound; `halt_before_overspend`
  was ON but never tripped (worst-case projected cost stayed under $0.50 throughout).
- Token usage: 19,367 in / 17,652 out (current eval) — output tokens dominated cost
  because Haiku wrapped many replies in verbose markdown analysis (see §5).
- Stage breakdown: current-genome eval $0.1076 (76 calls) → +$0.1167 for the mutated-genome
  eval (76 calls) + the 1 Sonnet mutation call → $0.2253 cumulative.

The 1 Sonnet call is the disclosed meta-mutation (option a), not a colony role.

---

## 5. Parse failures / degraded events

The Stage 1 resilience fixes were **load-bearing on the very first real run**:

| event | current eval | candidate eval | total |
|---|---:|---:|---:|
| `parse_fallback` | 16 | 19 | **35** |
| `api_error` | 0 | 0 | **0** |

- **35 parse fallbacks, 0 API errors, 0 crashes.** Real Haiku frequently ignored the
  "JSON only" instruction and returned markdown analysis (e.g. ``"# Analysis of Formula
  `a` …"``) for `generate`/`revise` replies. `_parse_candidate` extracted JSON when an
  object was embedded, and otherwise fell back to the Oracle default `{"var":"a"}` —
  **gracefully, and now visibly** (the `parse_fallback` events are exactly the
  observability added in Stage 1). Of ~24 proposal/revision parse opportunities per eval,
  roughly two-thirds were prose-wrapped; the run still climbed to 87.5 on the replies that
  did parse.
- **Had Stage 1 not landed:** these 35 degradations would have been *silent* (logged as
  ordinary default proposals), and any genuine API failure would have crashed the whole
  integrated run instead of being contained. None of that happened — the run completed
  cleanly.

**Follow-up worth considering (not done here — out of scope):** Haiku's low strict-JSON
compliance suggests the formula prompt could benefit from a structured-output constraint
or a firmer "respond with a single JSON object and nothing else" instruction. That is a
prompt/quality change, not a correctness fix, and would touch the generate/revise prompt
path — flagged for your call, deliberately left alone.

---

## 6. Invariant check on the real run

- **I1 (gate sacrosanct):** no candidate falsely certified; the 87.5 near-miss was correctly
  rejected by Z3; nothing unverified persisted.
- **I2 (spend cap):** $0.2253 ≤ $0.50; per-model sums reconcile to the single global total;
  the pre-call guard was armed and never had to fire.
- **I3 (bounded mutation):** the only mutation was a `flavor` on a proposer role (allowlisted,
  post-gate); nothing touched the gate/cap/score.
- **I4 (re-pass the gate):** the mutated genome was evaluated under the same Z3 gate, failed
  to improve verified fitness, and was rejected — not persisted.

**Total real spend this run: $0.2253.** Artifacts: `/tmp/agora_real/{stdout.log,
genome.json, evolve_log.jsonl, runs/}`.

---

# Run 2 — after tightening proposer-path JSON prompting

**Only change between runs:** the committed proposer-path structured-output fix
(commit `910c37c`) — stronger "JSON only, no markdown, no prose, start with `{`"
instruction + schema example on `system_prompt`/`revise_prompt`, plus a guarded `{`
assistant-prefill on the two proposer calls (Haiku supports prefill). **Identical**
command, models, `--cap 0.50`, `seed=7`, fresh `/tmp/agora_real`. Exit 0. Nothing else
changed — the comparison against Run 1 is the point.

## Headline comparison

| metric | Run 1 | Run 2 | delta |
|---|---:|---:|---|
| **`parse_fallback` events** | **35** | **0** | **−35 → 0** (target was < 5) |
| `api_error` events | 0 | 0 | — |
| Z3-verified win | none | **none** | unchanged |
| best score (majority3) | 87.5 (7/8 rows) | 87.5 (7/8 rows) | unchanged |
| total spend | $0.2253 | **$0.1463** | −35% |
| total calls | 153 | 153 | — |
| output tokens / call | ~232 | ~125 | roughly halved |

## What the fix did — and did not — accomplish

- **Did:** the JSON-compliance bottleneck is **eliminated.** Real Haiku now returns a
  bare formula AST instead of markdown analysis, so **parse_fallback dropped 35 → 0**:
  the colony searched on **100% of its budget** instead of ~⅔. The prefill (`{`) plus
  the explicit no-markdown framing also cut output tokens ~in half, so the run was
  **cheaper** ($0.1463 vs $0.2253) despite a slightly longer system prompt.
- **Did not:** **still no Z3-verified win.** With clean JSON on every proposal, Haiku
  *still* plateaus at **87.5 (7 of 8 rows)** on `majority3` — both evaluations' best
  formulas are valid 7/8 near-misses (`(a∧c)∨(b∧c)` and `(b∧(a∨c))`), each dropping one
  pairwise-AND term of the true majority `(a∧b)∨(a∧c)∨(b∧c)`. Z3 correctly rejects both.
  **The bottleneck has moved from output *formatting* (now solved) to Haiku's *reasoning
  depth*** — it reliably composes a 7/8 formula but not the full 8/8 majority.

## Self-improvement, explainability, spend (Run 2)

- **Trickle mutation:** rejected again — `constructor` flavor rewrite, evaluated under
  the same Z3 gate, tied fitness `(0, 87.5)`, not persisted (audit: 1 reject, 0 accepted;
  genome stayed baseline; rotation 0 → 1).
- **Explanatory:** `generalizer` was the Elo winner (+91.2 net) via Haiku; revision
  acceptance 100% / 100% / 88% across proposers. (Note: with 0 parse-fallbacks the
  proposals are all real formulas, and this seed produced 0 *decisive* critiques —
  Elo moved via head-to-head ranking rather than score-raising revisions; the
  attribution shape is intact.)
- **Spend reconciliation:** Haiku $0.1455 / 152 calls + Sonnet $0.0008 / 1 call (meta
  flavor-rewrite) = **$0.1463 = global total** ✓; **$0.1463 / $0.50 = 29% of cap**;
  guard armed, never fired. Tokens: 50,080 in / 19,142 out (cumulative).

## Invariants (Run 2)

- **I1:** no false certification; both 87.5 near-misses correctly Z3-rejected.
- **I2:** $0.1463 ≤ $0.50; per-model sums reconcile; guard never had to fire.
- **I3:** only mutation was an allowlisted post-gate `flavor`; gate/cap/score untouched.
- **I4:** mutated genome re-passed the same gate, failed to improve, not persisted.

## Conclusion — stopping here (per instruction)

Run 2 meets the stop condition you set: **no verified win AND parse fallbacks under ~5
(in fact 0).** The structured-output change did its job — it removed the formatting
bottleneck cleanly and cheaply — but a verified `majority3` solution did **not** emerge,
because the limiting factor is now Haiku's reasoning, not its output format.

**The next move (a Sonnet proposer for one run) is your call, not mine.** I am not
proceeding to it. **Total real spend across both runs: $0.2253 + $0.1463 = $0.3716.**
