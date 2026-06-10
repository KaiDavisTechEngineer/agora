"""
Oracles = the swappable "ground truth" the colony optimizes against.

The colony depends ONLY on the Oracle ABC, so swapping domains
(rotary tuning -> drug repurposing -> anything) changes nothing in the loop.

A real wet-lab Oracle would replace score()/random_candidate() with calls to
databases (DrugBank, ChEMBL) and predictors (docking, binding affinity). The
DrugRepurposingOracle below is a SYNTHETIC stand-in that marks exactly where
that real data plugs in — it proves the architecture is domain-agnostic without
pretending to do real science.
"""
from __future__ import annotations
import json, random
from abc import ABC, abstractmethod


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


class Oracle(ABC):
    name: str = "oracle"

    @abstractmethod
    def random_candidate(self, rng: random.Random) -> dict: ...

    @abstractmethod
    def mutate(self, candidate: dict, rng: random.Random, strength: float) -> dict:
        """Local search step used by the mock client and by 'optimizer' agents."""

    @abstractmethod
    def normalize(self, candidate: dict) -> dict:
        """Coerce a possibly-messy (LLM-authored) candidate into valid ranges."""

    @abstractmethod
    def score(self, candidate: dict) -> float:
        """Higher is better. Deterministic."""

    @abstractmethod
    def system_prompt(self, flavor: str) -> str: ...

    @abstractmethod
    def critique_prompt(self, candidate: dict) -> str: ...

    @abstractmethod
    def revise_prompt(self, candidate: dict, critiques: list[str]) -> str: ...

    def verify(self, candidate: dict):
        """Formal certificate for verifiable oracles. None => this oracle only
        JUDGES/APPROXIMATES (no un-gameable ground truth). Verifiable oracles
        (e.g. FormulaSynthesisOracle) override this to return a real bool."""
        return None

    def optimum_estimate(self, samples: int = 200_000, seed: int = 0) -> float:
        rng = random.Random(seed)
        best = -1e9
        for _ in range(samples):
            best = max(best, self.score(self.random_candidate(rng)))
        return round(best, 2)


# ===========================================================================
# ROTARY ENGINE TUNE ORACLE  (Phase 0 domain)
# ===========================================================================
PORT_FLOW = {"stock": 0,  "street": 15, "bridge": 35, "peripheral": 55}
PORT_HEAT = {"stock": 0,  "street": 3,  "bridge": 8,  "peripheral": 15}
PORT_IDLE = {"stock": 0,  "street": -2, "bridge": -8, "peripheral": -18}
SEAL_STRENGTH = {"stock": 8, "ceramic": 12, "steel": 18}
SEAL_FRICTION = {"stock": 0, "ceramic": 2,  "steel": 4}
PORTS = list(PORT_FLOW)
SEALS = list(SEAL_STRENGTH)


class RotaryOracle(Oracle):
    name = "rotary"

    def random_candidate(self, rng):
        return {"afr": rng.uniform(10, 15), "timing": rng.uniform(5, 35),
                "boost": rng.uniform(0, 20), "port": rng.choice(PORTS),
                "seal": rng.choice(SEALS)}

    def mutate(self, c, rng, strength):
        c = self.normalize(c)
        return {
            "afr":    c["afr"]    + rng.uniform(-1, 1) * strength,
            "timing": c["timing"] + rng.uniform(-5, 5) * strength,
            "boost":  c["boost"]  + rng.uniform(-4, 4) * strength,
            "port":   rng.choice(PORTS) if rng.random() < 0.25 * strength else c["port"],
            "seal":   rng.choice(SEALS) if rng.random() < 0.25 * strength else c["seal"],
        }

    def normalize(self, t):
        t = t or {}
        return {
            "afr":    round(clamp(float(t.get("afr", 12.5)), 10.0, 15.0), 2),
            "timing": round(clamp(float(t.get("timing", 20)), 5.0, 35.0), 1),
            "boost":  round(clamp(float(t.get("boost", 6)), 0.0, 20.0), 1),
            "port":   t.get("port") if t.get("port") in PORTS else "street",
            "seal":   t.get("seal") if t.get("seal") in SEALS else "ceramic",
        }

    def score(self, t):
        t = self.normalize(t)
        afr, timing, boost, port, seal = t["afr"], t["timing"], t["boost"], t["port"], t["seal"]
        power = 100.0 + boost * 8.0 + PORT_FLOW[port] + PORT_IDLE[port]
        power += -0.08 * (timing - 27) ** 2 + 25      # timing sweet spot ~27
        power += -3.0 * (afr - 12.3) ** 2 + 20        # AFR sweet spot ~12.3 (rich)
        power -= SEAL_FRICTION[seal]
        risk = (afr - 11.5) * 4 + boost * 1.5 + (timing - 20) * 1.2
        if risk > 25:
            return round(power * 0.2 - 50.0, 2)        # detonation cliff: grenaded engine
        power -= max(0.0, risk) * 1.5
        power -= PORT_HEAT[port] * (1 + boost / 10)
        load = boost + PORT_FLOW[port] / 10
        power -= max(0.0, load - SEAL_STRENGTH[seal]) * 6.0
        return round(power, 2)

    def system_prompt(self, flavor):
        base = ("You are a rotary (Wankel) engine tuner. Propose ONE tune as STRICT JSON "
                "with keys: afr (10-15), timing (5-35 deg BTDC), boost (0-20 psi), "
                "port (stock|street|bridge|peripheral), seal (stock|ceramic|steel). "
                "Rotaries like to run rich. Reply with JSON only, no prose.")
        return base + " " + flavor

    def critique_prompt(self, c):
        return (f"As a reliability skeptic, critique this rotary tune for detonation and "
                f"apex-seal risk in 1-2 sentences: {json.dumps(self.normalize(c))}")

    def revise_prompt(self, c, critiques):
        joined = " | ".join(critiques) if critiques else "none"
        return (f"Your tune was {json.dumps(self.normalize(c))}. Peer critiques: {joined}. "
                f"Revise to a SAFER, higher-power tune. Reply with JSON only.")


# ===========================================================================
# DRUG REPURPOSING ORACLE  (synthetic — proves the loop is domain-agnostic)
# ===========================================================================
# A candidate is {drug, target, mechanism}. In a real system:
#   - valid (drug,target) pairs come from DrugBank / ChEMBL
#   - score() comes from a binding-affinity / docking predictor + toxicity model
#   - novelty is checked against the known-interaction graph (don't "discover" knowns)
# Here we fake a small interaction surface so the SAME colony code runs unchanged.
DRUGS   = ["metformin", "aspirin", "sirolimus", "thalidomide", "minocycline", "valproate"]
TARGETS = ["AMPK", "COX2", "mTOR", "TNF", "MMP9", "HDAC"]
MECHS   = ["inhibit", "agonize", "modulate"]
# hidden synthetic "truth": a few high-affinity, low-tox combos
_TRUTH = {("sirolimus", "mTOR", "inhibit"): 95, ("metformin", "AMPK", "agonize"): 88,
          ("minocycline", "MMP9", "inhibit"): 84, ("valproate", "HDAC", "inhibit"): 80}
_TOX = {"thalidomide": 30, "valproate": 12, "sirolimus": 8}  # toxicity proxy penalty


class DrugRepurposingOracle(Oracle):
    name = "repurposing"

    def random_candidate(self, rng):
        return {"drug": rng.choice(DRUGS), "target": rng.choice(TARGETS),
                "mechanism": rng.choice(MECHS)}

    def mutate(self, c, rng, strength):
        c = self.normalize(c)
        out = dict(c)
        if rng.random() < 0.5 * strength + 0.2:
            out["drug"] = rng.choice(DRUGS)
        if rng.random() < 0.5 * strength + 0.2:
            out["target"] = rng.choice(TARGETS)
        if rng.random() < 0.3 * strength:
            out["mechanism"] = rng.choice(MECHS)
        return out

    def normalize(self, c):
        c = c or {}
        return {"drug": c.get("drug") if c.get("drug") in DRUGS else DRUGS[0],
                "target": c.get("target") if c.get("target") in TARGETS else TARGETS[0],
                "mechanism": c.get("mechanism") if c.get("mechanism") in MECHS else MECHS[0]}

    def score(self, c):
        c = self.normalize(c)
        key = (c["drug"], c["target"], c["mechanism"])
        base = _TRUTH.get(key, 20 + (hash(key) % 25))   # known winners vs faint synthetic signal
        return round(base - _TOX.get(c["drug"], 0), 2)

    def system_prompt(self, flavor):
        base = ("You are a computational pharmacologist proposing drug-repurposing "
                "hypotheses. Propose ONE as STRICT JSON with keys: drug, target, mechanism "
                "(inhibit|agonize|modulate). Favor low-toxicity drugs. JSON only.")
        return base + " " + flavor

    def critique_prompt(self, c):
        return f"Critique this repurposing hypothesis for toxicity/plausibility in 1-2 sentences: {json.dumps(self.normalize(c))}"

    def revise_prompt(self, c, critiques):
        joined = " | ".join(critiques) if critiques else "none"
        return (f"Your hypothesis was {json.dumps(self.normalize(c))}. Critiques: {joined}. "
                f"Revise toward a stronger, lower-toxicity candidate. JSON only.")


# ===========================================================================
# FORMULA SYNTHESIS ORACLE  (Z3-VERIFIED — frontier #1: machine-checked discovery)
# ===========================================================================
# Candidate = a Boolean formula as a nested AST. The colony searches for a formula
# equivalent to a target spec. Z3 PROVES equivalence over ALL inputs (the formal
# certificate enumeration can't scale to); the score climbs by truth-table
# correctness, then rewards minimality once correct. A "verified" result is true by
# construction — you cannot fool the checker. This is the seam the self-improvement
# (#6) and interpretability (#5) layers plug into.
_OPS = {"and", "or", "not"}


def _vars(k):
    return [chr(ord("a") + i) for i in range(k)]


def _eval_ast(ast, env):
    if "var" in ast:
        return bool(env.get(ast["var"], False))
    if "const" in ast:
        return bool(ast["const"])
    op, args = ast["op"], ast["args"]
    vals = [_eval_ast(a, env) for a in args]
    if op == "not":
        return not vals[0]
    if op == "and":
        return all(vals)
    return any(vals)               # "or"


def _ast_size(ast):
    if "var" in ast or "const" in ast:
        return 0                   # leaves are free; we count operators
    return 1 + sum(_ast_size(a) for a in ast["args"])


# A reusable "a XOR b" gadget, expressed in and/or/not (the only ops we allow).
def _xor(a, b):
    return {"op": "or", "args": [
        {"op": "and", "args": [a, {"op": "not", "args": [b]}]},
        {"op": "and", "args": [{"op": "not", "args": [a]}, b]}]}


# named target specs: (k vars, truth-table fn, a minimal reference formula).
# The reference is the yardstick for optimum_estimate() and the "minimal beats
# bloated" test — every reference below is fully correct AND as small as we know how.
_TARGETS = {
    "majority3": (3, lambda e: (e["a"] + e["b"] + e["c"]) >= 2,
                  {"op": "or", "args": [
                      {"op": "and", "args": [{"var": "a"}, {"var": "b"}]},
                      {"op": "and", "args": [{"var": "a"}, {"var": "c"}]},
                      {"op": "and", "args": [{"var": "b"}, {"var": "c"}]}]}),  # ref size 5
    "mux":       (3, lambda e: (e["b"] if e["a"] else e["c"]),
                  {"op": "or", "args": [
                      {"op": "and", "args": [{"var": "a"}, {"var": "b"}]},
                      {"op": "and", "args": [{"op": "not", "args": [{"var": "a"}]}, {"var": "c"}]}]}),  # ref size 4
    "and3":      (3, lambda e: e["a"] and e["b"] and e["c"],
                  {"op": "and", "args": [{"var": "a"}, {"var": "b"}, {"var": "c"}]}),  # ref size 1
    "parity3":   (3, lambda e: (e["a"] + e["b"] + e["c"]) % 2 == 1,
                  _xor(_xor({"var": "a"}, {"var": "b"}), {"var": "c"})),  # ref size 15
}


class FormulaSynthesisOracle(Oracle):
    name = "formula"

    def __init__(self, target="majority3", max_ops=20):
        self.k, self._fn, self._ref = _TARGETS[target]
        self.vars = _vars(self.k)
        self.max_ops = max_ops
        # precompute the target truth table over 2^k assignments
        self.table = []
        for bits in range(2 ** self.k):
            env = {v: bool((bits >> i) & 1) for i, v in enumerate(self.vars)}
            self.table.append((env, bool(self._fn(env))))

    # ---- candidate generation -------------------------------------------------
    def _rand_ast(self, rng, depth=0):
        if depth >= 2 or (depth > 0 and rng.random() < 0.45):
            return {"var": rng.choice(self.vars)}
        op = rng.choice(["and", "or", "not"])
        if op == "not":
            return {"op": "not", "args": [self._rand_ast(rng, depth + 1)]}
        return {"op": op, "args": [self._rand_ast(rng, depth + 1),
                                   self._rand_ast(rng, depth + 1)]}

    def random_candidate(self, rng):
        return self._rand_ast(rng)

    def mutate(self, c, rng, strength):
        c = self.normalize(c)
        if rng.random() < 0.3 + 0.5 * strength:        # regrow a subtree
            return self._rand_ast(rng)
        if "var" in c:                                  # tweak a leaf
            return {"var": rng.choice(self.vars)} if rng.random() < 0.5 \
                else {"op": "not", "args": [c]}
        if rng.random() < 0.4 and c.get("op") in ("and", "or"):
            return {"op": "or" if c["op"] == "and" else "and", "args": c["args"]}
        i = rng.randrange(len(c["args"]))
        c = {"op": c["op"], "args": list(c["args"])}
        c["args"][i] = self.mutate(c["args"][i], rng, strength)
        return c

    # ---- validation -----------------------------------------------------------
    def normalize(self, c):
        return self._coerce(c, 0)

    def _coerce(self, c, depth):
        # depth cap keeps a pathological LLM AST from blowing the stack while still
        # admitting legitimately deep formulas (parity3's reference is ~6 deep).
        if not isinstance(c, dict) or depth > 12:
            return {"var": self.vars[0]}
        if "var" in c:
            return {"var": c["var"] if c["var"] in self.vars else self.vars[0]}
        if "const" in c:
            return {"const": bool(c["const"])}
        op = c.get("op")
        if op not in _OPS or "args" not in c or not isinstance(c["args"], list) or not c["args"]:
            return {"var": self.vars[0]}
        args = [self._coerce(a, depth + 1) for a in c["args"]]
        if op == "not":
            return {"op": "not", "args": [args[0]]}
        return {"op": op, "args": args[:4]}

    # ---- scoring (gradient) + Z3 verification (certificate) -------------------
    def score(self, c):
        ast = self.normalize(c)
        correct = sum(1 for env, want in self.table if _eval_ast(ast, env) == want)
        frac = correct / len(self.table)
        base = frac * 100.0
        if frac == 1.0:                                 # correct -> reward minimality
            base += max(0, self.max_ops - _ast_size(ast))
        return round(base, 2)

    def verify(self, c) -> bool:
        """Formal certificate via Z3: is the formula equivalent to the spec for ALL inputs?"""
        ast = self.normalize(c)
        try:
            import z3
        except ImportError:                              # fall back to complete enumeration
            return all(_eval_ast(ast, env) == want for env, want in self.table)
        zv = {v: z3.Bool(v) for v in self.vars}
        def to_z3(a):
            if "var" in a:
                return zv[a["var"]]
            if "const" in a:
                return z3.BoolVal(bool(a["const"]))
            xs = [to_z3(x) for x in a["args"]]
            return z3.Not(xs[0]) if a["op"] == "not" else (z3.And(*xs) if a["op"] == "and" else z3.Or(*xs))
        spec = z3.Or(*[z3.And(*[zv[v] if val else z3.Not(zv[v]) for v, val in env.items()])
                       for env, want in self.table if want])
        s = z3.Solver()
        s.add(to_z3(ast) != spec)                        # seek a disagreeing input
        return s.check() == z3.unsat                     # none exists => provably equivalent

    def optimum_estimate(self, samples=0, seed=0):
        return round(100.0 + max(0, self.max_ops - _ast_size(self._ref)), 2)

    def target_spec_text(self):
        rows = [f"{''.join('1' if env[v] else '0' for v in self.vars)}->{1 if want else 0}"
                for env, want in self.table]
        return f"Target truth table ({','.join(self.vars)} -> out): " + ", ".join(rows)

    def system_prompt(self, flavor):
        base = (f"You are a logic synthesizer. Variables: {', '.join(self.vars)}. "
                f"Propose a Boolean formula as STRICT JSON AST using nodes "
                f'{{"op":"and|or|not","args":[...]}} and {{"var":"a"}}. '
                f"{self.target_spec_text()} "
                f"Your formula must output exactly this for every input row, "
                f"then be as SMALL as possible. JSON only.")
        return base + " " + flavor

    def critique_prompt(self, c):
        return (f"{self.target_spec_text()} For this formula, name the exact input rows where "
                f"it DISAGREES with the target, and say whether it is minimal: "
                f"{json.dumps(self.normalize(c))}")

    def revise_prompt(self, c, critiques):
        joined = " | ".join(critiques) if critiques else "none"
        return (f"{self.target_spec_text()} Your formula was {json.dumps(self.normalize(c))}. "
                f"Critiques: {joined}. Revise to match the target on MORE rows and be smaller. "
                f"JSON only.")


ORACLES = {"rotary": RotaryOracle, "repurposing": DrugRepurposingOracle,
           "formula": FormulaSynthesisOracle}
