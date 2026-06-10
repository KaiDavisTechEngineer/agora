"""
Two interchangeable clients behind one interface.

AnthropicClient -> real Claude (needs ANTHROPIC_API_KEY).
MockClient      -> a $0 stand-in that proves the PLUMBING (loop, ranking, cost
                   accounting, topology, stop conditions). It does memory-driven
                   local search via the Oracle's mutate(), so the best-score curve
                   actually climbs — letting you watch the machine work before you
                   spend anything. It is NOT a model of Claude's reasoning.
"""
from __future__ import annotations
import os, json, re, random
from dataclasses import dataclass


@dataclass
class LLMReply:
    text: str
    in_tok: int
    out_tok: int


class AnthropicClient:
    def __init__(self):
        from anthropic import Anthropic  # imported lazily so mock mode needs no SDK
        self.c = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def complete(self, model, system, user, max_tokens=600) -> LLMReply:
        r = self.c.messages.create(
            model=model, max_tokens=max_tokens,
            system=system, messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return LLMReply(text, r.usage.input_tokens, r.usage.output_tokens)


class MockClient:
    """Holds a reference to the oracle (it is a test harness, allowed to)."""
    def __init__(self, oracle, rng: random.Random):
        self.oracle = oracle
        self.rng = rng

    def complete(self, model, system, user, max_tokens=600) -> LLMReply:
        from .roles import ROLE_REGISTRY
        role = _tag(user, "ROLE")
        low = user.lower()
        r = ROLE_REGISTRY.get(role)
        strength = r.strength if r else 0.6

        # Order matters: revision prompts also contain the word "critiques",
        # so match the revision markers FIRST, then audit, then the critique task.
        if "revise to" in low or "revise toward" in low:
            seed = _first_json(user)
            cand = self.oracle.mutate(seed, self.rng, 0.4) if seed \
                else self.oracle.random_candidate(self.rng)
        elif "audit it" in low or "audit the" in low:
            text = "No look-ahead/leakage flags; margin looks plausible but verify on held-out data."
            return LLMReply(text, len(system + user) // 4, len(text) // 4)
        elif "critique" in low or "disagrees" in low or "input rows where" in low:
            text = "Watch detonation/toxicity margin; tighten if aggressive."
            return LLMReply(text, len(system + user) // 4, len(text) // 4)
        else:
            best = _json_tag(user, "BEST_KNOWN")
            if best and self.rng.random() > 0.15:
                cand = self.oracle.mutate(best, self.rng, strength)
            else:
                cand = self.oracle.random_candidate(self.rng)

        text = json.dumps(self.oracle.normalize(cand))
        return LLMReply(text, len(system + user) // 4, len(text) // 4)


def make_client(cfg, oracle, rng):
    return MockClient(oracle, rng) if cfg.use_mock else AnthropicClient()


def _tag(text, key):
    m = re.search(rf"{key}=([a-zA-Z_]+)", text)
    return m.group(1) if m else ""


def _json_tag(text, key):
    m = re.search(rf"{key}=(\{{.*?\}})", text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _first_json(text):
    """First standalone JSON object in the text (balanced-brace scan; handles nesting)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None
