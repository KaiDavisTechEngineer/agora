# agora — architecture & conventions

`agora` is a multi-agent **colony** research system: a population of role-playing
agents that propose candidates, critique each other under a bounded budget, revise,
and get scored by a **swappable Oracle** — looping until they converge, hit a spend
cap, or are stopped. It is built around one load-bearing idea:

> **The dividing line between real discovery and plausible nonsense is the Oracle.**
> When the Oracle *judges* or *approximates*, smart agents eventually game it. When
> it *verifies*, a positive result is true by construction. So the verifier is built
> first, and everything that climbs a fitness signal climbs an un-gameable one.

That principle dictates the build order and the three frontiers below.

## Build order (the three frontiers)

1. **#1 Verifiable discovery** (`oracles.py::FormulaSynthesisOracle`) — Boolean-formula
   synthesis where Z3 *proves* equivalence to a target. The formal certificate.
2. **#6 Verifier-gated self-improvement** (`evolve.py`) — a meta-loop that evolves the
   agents' own proposer strategies; fitness = count of Z3-verified discoveries, so it
   cannot be reward-hacked. Built second, on top of #1.
3. **#5 Interpretability** (`interpret.py`) — reads the logs to explain *which* evolved
   strategies produced the verified wins. Built third.
4. **Integration** (`integrate.py`) — runs #6 on #1, then #5 on the result.

## Module map

| Module | Responsibility |
|---|---|
| `oracles.py` | `Oracle` ABC + implementations (`FormulaSynthesisOracle` is the verifiable one; `RotaryOracle`/`DrugRepurposingOracle` are non-verifiable demos proving domain-agnosticism). `ORACLES` registry. |
| `colony.py` | The domain-agnostic loop. Depends **only** on the `Oracle` ABC. |
| `roles.py` | Role registry with **kinds** (`proposer`/`critic`/`validator`) and named rosters (`BASE`, `QUANT`, `FORMAL`). |
| `agent.py` | `Agent` = role + Elo + bounded compressed memory + optional flavor override. `update_elo`. |
| `cost.py` | `CostTracker` (meters every model call) + `SpendCapExceeded`. Shareable across runs. |
| `llm.py` | `MockClient` ($0, drives the loop via the oracle) and lazy `AnthropicClient`. `make_client`. |
| `config.py` | One `Config` dataclass holding every knob. Model price table + tier constants. |
| `reporting.py` | JSONL event log + CSV best-score curve. |
| `inspect_run.py` | Inspector CLI: `--cycle` (proposal→critique→revision triples) and `--signals`. |
| `evolve.py` | #6 meta-loop + `agora.evolve` CLI. |
| `interpret.py` | #5 attribution/diff + `agora.interpret` CLI. |
| `integrate.py` | The single combined flow + `agora.integrate` CLI. |
| `run.py` | The colony CLI: `python -m agora.run`. |

## The colony loop (`colony.py`)

One cycle, all driven off role **kinds** read at runtime (adding a role never touches
the loop):

1. **GENERATE** — `proposer`s each propose a candidate dict. *(Sonnet tier)*
2. **DEBATE** — each critiquer (`proposer`+`critic`) reviews only **K** peers, so cost
   is **O(N)**, never O(N²). *(Haiku tier)*
3. **REVISE** — `proposer`s rewrite from the critiques they received; the revision is
   **kept only if `score(revised) >= score(original)`**.
4. **VALIDATE** — the Oracle scores every candidate; `validator`s audit the leader.
5. **RANK** — Elo updated on **adjacent finishers** (proposers only) → O(N).
6. **REMEMBER** — update global best; top candidates seed the shared **council** pool;
   each agent keeps a **compressed, bounded** memory.

State is saved **atomically every cycle** (`os.replace` of a tmp file) so runs resume.
Stops on **any** of: spend cap, cycle ceiling, convergence (patience), or a `STOP` file.

## The Oracle contract (`oracles.py`)

The colony depends on the `Oracle` ABC exclusively. Implement:
`random_candidate`, `mutate`, `normalize` (must **never crash** on malformed/LLM input),
`score` (higher better, deterministic), `system_prompt(flavor)`, `critique_prompt`,
`revise_prompt`, `optimum_estimate`, and optionally `verify` (default returns `None`;
verifiable oracles return a real `bool`).

`FormulaSynthesisOracle` specifics:
- Candidate = nested AST: `{"op":"and|or|not","args":[...]}` and `{"var":"a"}`.
- Targets (truth tables over k vars), grouped by a **difficulty** knob (`oracles.DIFFICULTY`,
  `--difficulty {1,2,3}`): **d1 (k=3)** `majority3`, `mux`, `and3`, `parity3`; **d2 (k=4)**
  `parity4`; **d3 (k=5)** `majority5`, `parity5`. `--difficulty` selects the target when
  `--target` is omitted (d1 → `majority3`, the historic default). k≥4 references are built
  programmatically (`_xor_fold`/`_threshold_ref`) so they can't be silently wrong, and given
  parsimony headroom (per-target `max_ops`; the original four stay at 20). `oracles.BENCHMARKS`
  is a small battery of known-verifiable correct/incorrect answers per target.
- `score` = fraction of truth-table rows correct × 100; once **fully** correct, adds a
  parsimony bonus `max_ops - formula_size` so minimality is rewarded.
- `verify` = **Z3** proves equivalence (`assert formula != spec; unsat ⇒ equivalent`),
  with **complete-enumeration fallback** if z3 is absent.
- **The target is told to the agents**: the full truth table is embedded in the system,
  critique, *and* revise prompts (`target_spec_text()`). Hiding it would make agents
  synthesize blind — a deliberately avoided bug.

## #6 self-improvement (`evolve.py`)

Evolves the **genome** = `{proposer_role: flavor}`. Fitness over a battery of targets =
`(verified_count, total_score)`. A mutation is kept **only if fitness strictly improves**
(`is_improvement` = strict lexicographic `>`). Because `verified_count` counts Z3 proofs,
fitness is un-gameable. **One shared `CostTracker`** threads through every inner run, so
the cap is a single global budget; crossing it halts the battery mid-stream.

> In **mock**, `MockClient` is flavor-blind (it local-searches via `oracle.mutate`), so
> mutating flavors never changes fitness and the gate **correctly accepts nothing** —
> that is the gate working. Real agents read the flavor; that is where the genome evolves.

**Trickle mode** (`evolve.trickle`, `python -m agora.evolve --trickle`) is a gentle,
*accumulating* entry point: exactly **one** attempt per invocation. It loads the
persisted genome from `genome.json`, rotates to **one** target (rotation index lives
in `genome.json`), evaluates the current genome and one mutated variant on just that
target, keeps the mutation only on a **strict verifier-gated improvement** (the same
gate), then saves `genome.json`. Defaults are tiny and cheap — 1 attempt, small inner
cycles, real API, a `$0.50` hard cap — so improvements drip in over many cheap runs
without ever weakening the gate. The full meta-loop is unchanged; pass `genome_path=`
to `evolve()` to make it accumulate too. `genome.json` is git-ignored generated state
(force-add it to snapshot an evolved genome).

**Bounded mutation surface (I3/I4, enforced in code).** Every mutation is a structured,
*vettable* object — `{"kind":"flavor","role":…,"value":…}` or `{"kind":"param","name":…,
"value":…}`. `evolve.vet_mutation()` is **default-deny**: only a flavor on a proposer
role or a param in `STRATEGY_PARAM_ALLOWLIST` (`k_peers`, `survivor_frac`, `memory_keep`,
`shared_keep` — all strictly downstream of the gate) is admitted; anything naming a
`SACROSANCT_TARGET` (the gate, verifier, score, spend cap, models/weights) is flagged a
**REWARD-HACK and rejected *before* the Oracle gate is ever reached**. An admitted
mutation must still **re-pass the same gate** (`is_improvement` on Z3-verified fitness)
to persist (I4). `genome.json` now also stores evolved post-gate `params` (re-filtered
to the allowlist on load, so a tampered file can't smuggle a forbidden knob) and an
`audit` trail recording **accepted *and* rejected** mutations (what / when / why).

## #5 interpretability (`interpret.py`)

Behavioral (from logs, not model internals): verified wins attributed by authoring role;
revision-acceptance rate by role; critic roles/words that precede accepted revisions; and
a baseline-vs-evolved flavor diff correlating each instruction change with a rise in
verified-count.

## Cost, tiers, clients

- **Hard spend cap**: `CostTracker.charge()` meters every call and raises
  `SpendCapExceeded` the instant cumulative spend crosses the cap. Pass one instance to
  many colonies for a single global budget. It also keeps a per-model breakdown
  (`as_dict()["by_model"]`) — pure attribution; the cap stays a single global total.
- **Two tiers** (default): `gen_model` (Sonnet) for generate/revise; `grunt_model`
  (Haiku) for critique/audit. Prices live in `config.PRICES` (incl. `claude-fable-5`).
- **Per-role-kind models (#2)**: `Config.role_models` (`{proposer|critic|validator: model}`)
  + `config.resolve_role_models()` assign a model per kind of WORK — proposers
  generate/revise, critics critique, validators audit. Default = the two tiers above,
  byte-identical to before. CLI: `--proposer-model/--critic-model/--validator-model`.
  The model a kind uses is **orthogonal to the Z3 gate** — which model proposed a
  candidate never affects whether the Oracle verifies it (no self-grading).
- **Clients**: `MockClient` needs no API key and costs $0 of real money (it still meters
  synthetic tokens so budget plumbing is exercised). `AnthropicClient` lazily imports the
  `anthropic` SDK and is selected by `Config.use_mock=False` (`--real`).

## Running

```bash
# free, no API key — all plumbing is exercised in mock
python -m agora.run --oracle formula --target majority3 --roster formal
python -m agora.evolve --steps 4 --cap 5.00            # mock meta-loop
python -m agora.interpret --run-dir runs --evolve-log evolve_log.jsonl
python -m agora.integrate --steps 3 --cap 5.00         # #1 -> #6 -> #5
python -m agora.inspect_run --cycle 5 ; python -m agora.inspect_run --signals
touch STOP                                              # halt a running colony gracefully

# REAL Claude — SPENDS MONEY. Always capped. Ask before running.
python -m agora.run --real --oracle formula --roster formal --cap 1.00
python -m agora.evolve --real --cap 5.00 --steps 4
python -m agora.evolve --trickle          # one cheap accumulating attempt (real, $0.50 cap)
python -m agora.evolve --trickle --mock   # dry-run the trickle attempt for free
```

## Conventions

- **Python 3.9+**. Every module starts with `from __future__ import annotations` so
  `X | None` / `list[str]` annotations work on 3.9.
- **pytest**; run `python -m pytest -q` from the repo root.
- The colony imports **nothing domain-specific** — only the `Oracle` ABC. New domains =
  new `Oracle` subclass + registry entry; the loop is untouched.
- New roles are added to `roles.py` with a `kind`; the loop routes on kind at runtime.
- `normalize()` must be **total** (never raise) — it is the firewall against malformed
  LLM output.
- Run artifacts (`run_log.jsonl`, `colony_state.json`, `best_curve.csv`, `runs/`,
  `evolve_log.jsonl`, `STOP`) are generated and git-ignored.
- **Never spend real money without explicit confirmation.** All real runs are capped.
