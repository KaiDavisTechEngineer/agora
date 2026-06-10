# agora — multi-phase build session summary

A self-contained record of a 5-phase implementation session on the `agora` repo
(a multi-agent "colony" research system). Written so another model can analyze the
work without the original transcript. Repo: local git, branch `main`.

---

## 0. System under test (one-paragraph mental model)

`agora` is a domain-agnostic loop (`colony.py`) over an `Oracle` ABC. One cycle:
**generate** (proposers propose candidates) → **debate** (each critiquer reviews K
peers — bounded, O(N)) → **revise** (kept only if `score(revised) ≥ score(original)`)
→ **validate + rank** (Oracle scores; Elo on adjacent finishers) → **audit**
(validators review the leader) → **remember** (global best, shared pool, bounded
memory). Roles have **kinds**: `proposer` / `critic` / `validator`. Everything that
climbs a fitness signal climbs an **un-gameable** one because the load-bearing Oracle
*verifies* (Z3) rather than judges.

Four entrypoints: `python -m agora.{run | evolve | interpret | integrate}`.

### Hard invariants (correctness requirements, not preferences)
- **I1** Oracle/verifier gate is sacrosanct — never weakened, bypassed, or routed around.
- **I2** Never raise/remove the hard global spend cap programmatically.
- **I3** The self-improvement meta-loop tunes ONLY strategy params downstream of the
  gate; never edits the gate, verifier, scoring path, or spend cap; never touches weights.
- **I4** Every mutation the meta-loop proposes must re-pass the same Oracle gate before
  it persists.

### Operating rules honored
- Python 3.9+ compatible only (repo convention: `from __future__ import annotations`).
- Before any paid model call: stop, estimate, wait for approval. **No paid call was
  ever made** — all tests/runs use `MockClient` ($0). Total spend incurred ≈ **$0**.
- Each phase: extend tests → run FULL suite → green → commit. Diffs scoped per phase.

---

## 1. Phase 0 — Orientation (no code)

Findings reported back:
- **Spend cap (I2) enforced at** `cost.py::CostTracker.charge()` (raises
  `SpendCapExceeded` when `usd >= cap`); every model call routes through it.
  Flagged: `charge()` raises *after* recording the spend (relevant to Phase 5b).
- **Verifier gate (I1) at** `oracles.py::FormulaSynthesisOracle.verify()` (Z3 proves
  equivalence over all inputs, enumeration fallback if z3 absent). The self-improvement
  gate is `evolve.py::is_improvement()` over `(verified_count, total_score)`, where
  `verified_count` derives from `verify()`.
- **Frontier state:** #1 had 4 targets, all k=3. #5 was *descriptive* only (no Elo
  attribution, no model dimension). #6 already had `genome.json` persistence + a
  `trickle` mode + the strict gate, but **no explicit allowlist** and history recorded
  accepts only.
- **Contradictions flagged & adapted to:** Phase 3 genome layer already existed (extend,
  don't duplicate); Phase 5(a) "never ranked/scored" reinterpreted at the gate level
  (wrong candidates are still *scored* for gradient, but never *verified/persisted*);
  Phase 5(b) "halt before the offending call" required new behavior since `charge()`
  raised after; README test-count drift fixed as touched.

Starting point: **50 tests passing**, Python 3.9.6, z3-solver 4.16.0 present.

---

## 2. Phase 1 — Harder verifiable targets (#1) — commit `f08d142`

- New k≥4 targets: **`parity4`** (k=4), **`parity5`**, **`majority5`** (k=5).
- Reference formulas built **programmatically** (`_xor_fold` for parity, `_threshold_ref`
  for majority) so a reference cannot be silently wrong; they respect `normalize()`'s
  ≤4-arg / depth-12 caps (verified byte-stable through `normalize`).
- **Difficulty knob:** `oracles.DIFFICULTY` (1=k3, 2=k4, 3=k5) + `difficulty_of` /
  `targets_at` / `default_target`; `Config.difficulty`; `run.py --difficulty {1,2,3}`
  selects the target when `--target` is omitted. Backward-compatible (d1 → `majority3`).
- Per-target `max_ops` headroom so parsimony stays a live objective; original four
  targets keep `max_ops=20` (scores unchanged).
- **`oracles.BENCHMARKS`**: per-target known-correct (Z3 accepts) + known-incorrect
  (Z3 rejects) pairs, with a `benchmark(target)` lookup.
- Tests +19 → **69**. The Oracle accepts known-correct and rejects known-incorrect
  (and near-miss) at the new difficulty; benchmark verdicts; difficulty selection;
  normalize-stability; a mock colony runs end-to-end on a k=5 target.

Files: `agora/oracles.py`, `config.py`, `run.py`, `__init__.py`, `CLAUDE.md`,
`tests/test_phase1_targets.py`.

---

## 3. Phase 2 — Per-role model selection — commit `82e7dc9`

- Each role-**kind** can be assigned its own model, chosen by *kind of work*:
  proposer → generate+revise, critic → critique, validator → audit.
- `Config.role_models` (`{kind: model}`, partial dicts allowed) +
  `config.resolve_role_models()` with validation: unknown kind or unpriced model →
  `ValueError`. **Default reproduces the historical two-tier behavior exactly**
  (proposer→`gen_model` Sonnet, critic/validator→`grunt_model` Haiku).
- Added **`claude-fable-5` ($10/$50 per 1M)** to `config.PRICES` — pricing taken from
  the authoritative model reference (not guessed).
- `CostTracker` gained a per-model breakdown (`by_model`) feeding the **single** global
  cap (I2); persisted/resumed with colony state.
- Colony routes each call to the resolving role-kind model; `run.py` gains
  `--proposer-model / --critic-model / --validator-model`.
- **Validator independence (I1):** `verify()` takes only the candidate — no model
  parameter — so which model proposed a candidate cannot affect the verdict.
- Tests +13 → **82**: config parse (default/valid/invalid kind/unpriced), Fable-5
  pricing, per-model attribution vs mocked calls, default-reproduces-two-tier, single
  global-cap halt, gate/validator independence.

Files: `agora/config.py`, `cost.py`, `colony.py`, `run.py`, `CLAUDE.md`,
`tests/test_phase2_models.py`.

---

## 4. Phase 3 — Bounded self-improvement: allowlist + audit (#6) — commit `5a62544`

- Mutations became **structured + vettable**: `{"kind":"flavor","role":…,"value":…}`
  or `{"kind":"param","name":…,"value":…}`.
- `evolve.vet_mutation()` is **default-deny**: only a flavor on a proposer role or a
  param in `STRATEGY_PARAM_ALLOWLIST` (`k_peers`, `survivor_frac`, `memory_keep`,
  `shared_keep` — all strictly downstream of the gate) is admitted. Naming any
  `SACROSANCT_TARGET` (gate, verifier, score, spend cap, models/weights) is flagged a
  **REWARD-HACK and rejected BEFORE the Oracle gate is reached** (I3 = defense in depth).
- Admitted mutations still **re-pass the same verifier gate** before persisting (I4).
- `genome.json` extended with evolved post-gate `params` (re-filtered to the allowlist
  on load, so a tampered file can't smuggle a forbidden knob) and an `audit` trail
  recording **accepted AND rejected** mutations (what / when / why). Applied params
  reach the inner colony via `Config` (allowlist re-checked at apply time).
- `trickle()` and `evolve()` both route propose → vet → apply → re-gate → persist, with
  a pluggable `propose_mutation` for testing. Default flavor behavior unchanged (mock
  stays flavor-blind → gate accepts nothing).
- Tests +22 → **104**: a reward-hack (cap/score/verify/gate-as-kind) is caught,
  **never evaluated** (no `trickle_cand` eval event — proves the gate wasn't reached),
  genome untouched, recorded in audit with a REWARD-HACK reason; benign mutation
  persists only post-gate; audit accumulates both outcomes; params reach the colony;
  tampered-file param dropped on load; genome+params+audit round-trips deterministically.

Files: `agora/evolve.py`, `CLAUDE.md`, `tests/test_phase3_genome_guard.py`.

---

## 5. Phase 4 — Explanatory interpretability (#5) — commit `56e5017`

- Causal chain the colony logs: **critiques received → accepted score-raising revision
  → rank → Elo delta**.
- Colony now emits a per-cycle **`elo`** event (role, **model**, score, rank,
  before/after, delta) and a **`model`** field on every proposal/critique/revision/audit
  event (additive — no existing event key removed).
- `interpret.explain_elo_attribution()`: net Elo per **proposer role + model**; **critic
  credit** (which critic role/model's critiques moved Elo, decisive-revision count); and
  the individual **decisive critiques** (critique → revision gain → Elo gain).
  `win_explanations()`: per inner run, the Elo-winner (role+model) vs the top-score
  author. Surfaced through `analyze()`/`render()`; descriptive sections kept.
- Attribution keyed by run **basename** (not path) → byte-stable across two independent
  same-seed `evolve` runs.
- Tests +6 → **110**: colony emits elo+model signals; explanatory output has a stable
  asserted shape on a fixed seed (every proposer role attributed with model + net Elo,
  approximate Elo zero-sum, full causal record on decisive critiques); deterministic
  across same-seed runs; explicitly names the critic role/model that moved a proposer's
  Elo; render includes the section; empty logs handled.

Files: `agora/colony.py`, `reporting.py`, `interpret.py`, `CLAUDE.md`,
`tests/test_phase4_explanatory.py`.

---

## 6. Phase 5 — Integration — commit `537718b`

Single `agora.integrate` run wires **P2 → P1 → P3 → P4** under one shared cap:
per-role models → a hard difficulty target → ONE gate-bounded trickle self-improvement
step (persisting to the genome store) → an explanatory trace read back from the logs.

Enabling change for the spend-cap invariant (Phase 0 flag):
- `CostTracker.remaining()` / `would_exceed()` + opt-in `Config.halt_before_overspend`.
  All colony paid calls now funnel through `Colony._complete()`, which (when enabled)
  refuses a call whose worst-case projected cost (estimated input + `max_tokens` output)
  would cross the cap — **halting BEFORE the offending call, never changing the cap
  value** (I2). Default off, so every existing path/test is byte-identical.
- `role_models` + `halt_before_overspend` threaded through `trickle()` / `evolve()`.
- `integrated_run()` orchestrates and returns a structured, path-independent result.

ONE mocked, $0, fixed-seed end-to-end test (`tests/test_integrate.py`) asserts:
- **(a) gate integrity** — a wrong candidate (`{"var":"a"}`) is Oracle-rejected; no eval
  certifies a verified win; genome stays baseline.
- **(b) spend cap** — total spend ≤ cap, and with the guard on, a would-exceed run halts
  before the offending call so `usd < cap` (never reaches it); per-model sum reconciles.
- **(c) per-role routing** — only the 3 configured models billed, each with calls;
  proposal/critique/audit events carry exactly the configured model; per-model totals
  reconcile to the single global total.
- **(d) bounded self-improvement** — reward-hack (`spend_cap_usd`) rejected
  (`reject_disallowed`), never evaluated, audited with REWARD-HACK; benign flavor
  mutation persists only after the gate passes (forced via `is_improvement`).
- **(e) genome persistence** — a persisted post-gate param (`k_peers=2`) round-trips
  deterministically and a resumed run's inner colony picks it up (`start.k_peers == 2`).
- **(f) explanatory trace** — names Elo-moving critics + contributing role/model; stable
  shape on the fixed seed; proposer Elo attributed to the proposer model.
- **(g) joint invariants** — within the same run: cap respected AND every persisted
  accept is gate-logged AND persisted params ⊆ allowlist AND no eval bypassed the gate.
- **(h) determinism** — same seed ⇒ byte-stable canonical result across two runs.
- Plus a CLI smoke test.

README documents the integrated flow. Tests +1 net → **111**.

Files: `agora/cost.py`, `config.py`, `colony.py`, `evolve.py`, `integrate.py`,
`README.md`, `CLAUDE.md`, `tests/test_integrate.py`.

---

## 7. Final state

- **Tests: 50 → 111**, all green. Full suite run and green before every commit.
- **Commits (newest first):**
  - `537718b` Phase 5: integrate the four frontiers into one gate-bounded loop
  - `56e5017` Phase 4: explanatory interpretability — attribute WHY candidates won/lost
  - `5a62544` Phase 3: bounded mutation surface (allowlist + audit) for self-improvement
  - `82e7dc9` Phase 2: per-role-kind model selection + per-model cost accounting
  - `f08d142` Phase 1: harder Z3-verifiable targets (k=4/k=5) + difficulty knob + benchmarks
  - (pre-existing) `3dff33a`, `05e00da`, … original frontiers #1/#5/#6 + trickle.
- **Spend: ~$0** (all mock). No `--real` run launched.

### Integrated run command (the exact path that exercises all four frontiers)
```bash
python -m agora.integrate --difficulty 2 --cap 5.00
# or with an explicit per-role model:
python -m agora.integrate --difficulty 3 --proposer-model claude-fable-5 --cap 5.00
```
Run the suite: `python3 -m pytest -q`  (111 tests, $0).

---

## 8. Notes / open questions worth a reviewer's eye

1. **Phase 5(b) "halt before the offending call" is conservative.** The pre-call guard
   estimates input tokens as `len(system+user)//4` (mirrors the mock) and uses
   `max_tokens` as the output upper bound — so for real runs it may halt slightly early.
   It is opt-in (`halt_before_overspend`, default off) to keep `charge()`-after-record
   semantics for all existing paths/tests, including one that asserts `usd >= cap` after
   a mid-battery halt. Worth deciding whether the integrated default (on) should become
   the global default.
2. **Phase 5(a) interpretation.** "Never ranked, scored, or persisted" was implemented at
   the gate level: wrong candidates are still scored/ranked inside a colony (that's the
   gradient that lets the loop climb), but never pass `verify()` and never persist as a
   verified discovery. If the intent was literally "never scored," the gradient would
   need to change — deliberately not done.
3. **Mock is flavor-blind by design** (`MockClient` local-searches via `oracle.mutate`),
   so in mock the gate correctly accepts nothing and self-improvement shows no gain. Real
   agents read the flavor — that's where the genome would actually evolve. All "accept"
   tests force the gate via `monkeypatch`/injected mutations; none fakes a Z3 proof.
4. **Determinism caveat:** `Date.now()`/`random` are not used in the scored path; mock
   token sizing is `len//4`. Explanatory attribution is keyed by run basename so it's
   path-independent. Elo per-event rounding to 0.1 introduces a tiny (<5.0 total) drift
   from exact zero-sum — asserted as a bound, not equality.
5. **Not changed (scope discipline):** model weights are never touched; the meta-loop's
   mutable surface is strictly the allowlist (flavors + 4 colony knobs); no drive-by
   refactors beyond what each phase required.
