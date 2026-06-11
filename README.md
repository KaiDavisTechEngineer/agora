# agora

A co-scientist **agent society**: a population of role-playing agents that propose
candidates, critique each other, revise, and get scored by a swappable **Oracle** —
looping until they converge, hit a budget, or you stop them. Built cost-first
(bounded critique + a hard spend cap) so it scales from 3 agents to 100 without
surprises.

Phase-0 domain is **rotary engine tuning** (a free, deterministic "dyno"). Swap the
Oracle and the same loop studies anything — a synthetic **drug-repurposing** oracle
is included to prove it.

```
generate ─▶ debate (bounded) ─▶ revise ─▶ validate (Oracle) ─▶ rank (Elo) ─▶ remember ─┐
   ▲                                                                                    │
   └────────────────────────────  next cycle (memory-driven)  ◀───────────────────────┘
```

## Quickstart

```bash
# $0, no API key — watch the loop climb toward the optimum
python -m agora.run

# more agents, more cycles
python -m agora.run --agents 15 --cycles 30

# different domain, same loop
python -m agora.run --oracle repurposing --agents 10

# frontier #1 — VERIFIED discovery: agents synthesize a Boolean formula,
# Z3 proves it equivalent to the target spec, score rewards correctness then minimality
python -m agora.run --oracle formula --roster formal --agents 6 --cycles 14

# real Claude, with a $1 hard ceiling so a bug can't cost more
export ANTHROPIC_API_KEY=sk-...
python -m agora.run --real --cap 1.00 --agents 5

# halt a running colony at any time, gracefully:
touch STOP
```

Run the tests: `python -m pytest -q`  (17 tests)
Forecast cost for any size: `python cost_projection.py`

## Observing a live run (candidate-level)

Every cycle logs each agent's **proposal**, the **critiques** it received, and its
**revision** (before/after + accepted?) to `run_log.jsonl`. Read it like a code review:

```bash
python -m agora.inspect_run --cycle 5     # full proposal->critique->revision triples
python -m agora.inspect_run --signals     # reasoning-quality metrics across all cycles
```

The `--signals` view computes what separates real reasoning from churn:
- **revision acceptance %** — high means critiques are informative (agents revise upward)
- **detonation-cliff hits** — should trend to ~0; skeptics should basically never grenade
- **avg score by role** — confirms explorer/optimizer/skeptic actually behave differently

At 50–100 agents this log gets large; pass `--quiet-log` (or set `log_candidates=False`)
to keep only cycle-level summaries.

## How it works (one cycle)

1. **Generate** — each agent proposes a candidate. (Sonnet)
2. **Debate** — each agent critiques **only K peers**. This is the cost lever: K
   peers → cost grows **O(N)**, not O(N²). (Haiku)
3. **Revise** *(Phase 1)* — each agent rewrites its candidate using the critiques it
   received; the revision is kept only if the Oracle says it's at least as good. (Sonnet)
4. **Validate** — the Oracle scores every candidate. Free in the toy; this is where a
   real predictor/database would plug in.
5. **Rank** — Elo updates on adjacent finishers (O(N)). Reputation emerges.
6. **Remember** — global best updates; top tunes seed a shared "council" pool that all
   agents read; each agent keeps a **compressed, bounded** memory (last few unique
   lessons), so input tokens stay ~constant.

### Roles & role-kinds
Agents are assigned roles from a **registry** (`agora/roles.py`). Each role has a
*kind* that determines how the colony uses it:
- **proposer** — generates candidates each cycle (and revises them); also critiques peers
- **critic** — never generates; only critiques proposers' candidates
- **validator** — never generates or critiques; runs a per-cycle **audit** over the
  leading candidate (the seat for a leakage / novelty / too-good-to-be-true check)

The default roster is three base proposers (`explorer`, `optimizer`, `skeptic`). A
12-role **quant roster** ships ready for the strategy-research Oracle:

```bash
python -m agora.run --roster quant --agents 12 --cycles 10
```

7 proposers + 4 critics (incl. **leakage_auditor**) + 1 validator (backtest_referee).
Define your own with `Config(roster=[...])` using any registry role names. The loop
reads kinds at runtime, so adding roles never touches it.

## Swapping domains
Implement the `Oracle` ABC in `agora/oracles.py`:
`random_candidate`, `mutate`, `normalize`, `score`, `system_prompt`,
`critique_prompt`, `revise_prompt`. The colony depends on nothing else. The included
`DrugRepurposingOracle` is a **synthetic stand-in** — it marks exactly where DrugBank /
ChEMBL data and a binding-affinity/toxicity predictor would replace `score()`.

### Verifiable oracles (the real frontier)
The dividing line between *groundbreaking* and *plausible-sounding nonsense* is the
Oracle. When it **judges** or **approximates**, agents eventually game it (you can see
this with the rotary objective). When it **verifies**, a positive result is true by
construction. `FormulaSynthesisOracle` is the first such Oracle: agents propose a
Boolean formula AST, `verify()` asks **Z3** whether it is equivalent to the target spec
over *all* inputs (a formal certificate enumeration can't scale to), and `score()`
climbs by truth-table correctness, then rewards minimality once correct. You cannot
fool the checker — which is exactly what makes it safe to later layer self-improvement
(#6) and interpretability (#5) on top. Needs `z3-solver` (falls back to complete
enumeration for small specs if Z3 is absent).

## Safety & autonomy
- **Hard spend cap** — every call is metered; the run aborts the instant it crosses
  `--cap`. The cap spans resumed runs.
- **Stop file** — `touch STOP` halts gracefully after the current cycle.
- **Convergence** — stops automatically after `--patience` cycles with no improvement.
- **Resume** — state is saved atomically every cycle (`colony_state.json`); rerun to
  continue exactly where it left off. `--fresh` starts over.
- **Run log** — one JSON event per line in `run_log.jsonl`; best-score curve in
  `best_curve.csv`.

## Cost at scale (bounded vs naive, 100 cycles, revision on)

| agents | bounded / run | naive all-to-all / run |
|-------:|--------------:|-----------------------:|
| 3      | ~$10          | ~$9                    |
| 15     | ~$50          | ~$99                   |
| 50     | ~$165         | ~$855                  |
| 100    | ~$330         | ~$3,210                |

Batch API (−50%) + prompt caching roughly halve the bounded column. The lesson:
cost is set by the **critique topology**, not the agent count. Keep `k_peers` small.

## The integrated loop (`python -m agora.integrate`)

A single integrated run wires the four frontiers together behind **one shared spend cap**:

```
per-role models ─▶ hard verifiable target ─▶ trickle self-improvement ─▶ explanatory trace
     (P2)                 (P1)                   (P3, gate-bounded)            (P4)
```

1. **P2 — per-role models.** Each role-kind (proposer / critic / validator) can run its
   own model, e.g. `--proposer-model claude-fable-5`. Per-model spend is attributed
   individually but feeds the **single** global cap. The Z3 Oracle stays the only real
   gate — which model proposed a candidate never affects whether it verifies.
2. **P1 — a hard target.** `--difficulty {1,2,3}` selects a larger Z3-decidable target
   (k=3 → k=5: `majority3` … `parity4` … `majority5`/`parity5`).
3. **P3 — trickle self-improvement.** ONE cheap, gate-bounded step adjusts strategy
   params and persists them to a genome store (`genome.json`). The mutation surface is
   an explicit allowlist; a mutation that tries to touch the gate, cap, or score is
   rejected **before** the gate and recorded in the audit trail. Every accepted change
   re-passes the same Z3 gate before it persists.
4. **P4 — explanatory trace.** The run's logs are read back to attribute **why** a
   candidate won or lost — which critiques (and which role/model) moved its Elo.

```bash
# free, mocked, $0 — exercises all four frontiers under one $5 cap
python -m agora.integrate --difficulty 2

# assign a stronger proposer; halt BEFORE any call that would cross the cap
python -m agora.integrate --difficulty 3 --proposer-model claude-fable-5 --cap 5.00

# real Claude — SPENDS MONEY. Always capped. Ask before running.
python -m agora.integrate --real --difficulty 2 --cap 1.00
```

The whole flow is covered by one mocked, `$0`, fixed-seed end-to-end test
(`tests/test_integrate.py`) asserting gate integrity, the spend cap (halt *before* the
offending call), per-role routing + cost attribution, bounded self-improvement
(benign change persists only post-gate; reward-hacks rejected + audited), genome
persistence/resume, the explanatory trace, a joint-invariant block, and determinism.

## What 12 real-model runs established (engagement summary)

*Condensed record of the real-model engagement (Runs 1–12, ~$6.21, ~1,700 API calls).
Full per-run data: `RESULTS.md`. State snapshot: `HANDOFF.md`.*

### Thesis

agora's load-bearing idea is that self-improvement is only safe to build on a fitness
signal that **verifies** rather than judges. The engagement tested that idea end-to-end
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

### The three single-variable experiments (the genome trilogy)

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

### Final reconciliation

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

## Roadmap (where this goes next)
- **Real-model run** — flip `--real`, watch Sonnet agents reason about the dyno.
- **Smarter memory** — periodic LLM summarization of lessons (hook is in place).
- **Novelty / anti-leakage agent** — a skeptic that flags "is this already known?"
  before a candidate counts as a discovery (critical for the repurposing domain).
- **Real Oracle** — wire `score()` to a binding-affinity/toxicity predictor + the
  known-interaction graph.
- **Async execution** — run agents concurrently for wall-clock speed at 50–100.

## Layout
```
agora/
  config.py      # one Config dataclass, model strings, prices
  cost.py        # CostTracker + the hard cap
  oracles.py     # Oracle ABC + RotaryOracle + DrugRepurposingOracle
  llm.py         # AnthropicClient (real) + MockClient ($0 plumbing)
  agent.py       # role, Elo, compressed memory
  colony.py      # the loop + persistence + stop conditions
  reporting.py   # JSONL log + CSV curve
  roles.py       # role registry: kinds (proposer/critic/validator) + quant roster
  run.py         # colony CLI
  inspect_run.py # read candidate logs / reasoning signals
  evolve.py      # #6 verifier-gated self-improvement + trickle + genome store
  interpret.py   # #5 behavioral + explanatory interpretability
  integrate.py   # the combined P2->P1->P3->P4 loop
tests/           # test_agora / evolve / trickle / interpret / integrate + phase1-4
cost_projection.py
```
```
Status: frontiers #1 (Z3-verified synthesis, k=3..k=5 + difficulty knob), #2 (per-role
models), #6 (verifier-gated self-improvement: allowlisted + audited trickle/genome),
and #5 (explanatory interpretability) — integrated into one gate-bounded loop. Tested
(110+), mock-verified end-to-end with resume, convergence, stop-file, per-model
accounting, and a single global spend cap all exercised. $0 in mock.
```
