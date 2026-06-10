"""An agent = a role + a reputation (Elo) + a compressed memory."""
from __future__ import annotations
import json
from dataclasses import dataclass, field

from .roles import assign_roles, get_role, kind_of, BASE_ROSTER  # noqa: F401 (re-exported)

ROLES = BASE_ROSTER


@dataclass
class Agent:
    id: int
    role: str
    elo: float = 1000.0
    memory: list[str] = field(default_factory=list)   # short lessons, bounded
    last_candidate: dict | None = None
    flavor_override: str | None = None                # set by the #6 meta-loop's genome

    @property
    def kind(self) -> str:
        return kind_of(self.role)

    @property
    def flavor(self) -> str:
        # an evolved override wins over the role's baseline flavor (the genome)
        return self.flavor_override if self.flavor_override else get_role(self.role).flavor

    def remember(self, lesson: str, keep: int) -> None:
        """Phase 1 memory compression: append, dedupe, keep only the last `keep`."""
        if lesson not in self.memory:
            self.memory.append(lesson)
        # keep most-recent unique lessons only -> input tokens stay ~constant
        self.memory = self.memory[-keep:]

    def context(self, global_best: dict | None, shared: list[str]) -> str:
        gb = json.dumps(global_best) if global_best else "{}"
        mine = " ; ".join(self.memory[-4:]) or "none yet"
        pool = " ; ".join(shared[-4:]) or "none yet"
        return (f"ROLE={self.role}\nBEST_KNOWN={gb}\n"
                f"Council insights: {pool}\nMy lessons: {mine}")

    def to_dict(self) -> dict:
        return {"id": self.id, "role": self.role, "elo": round(self.elo, 1),
                "memory": self.memory}

    @classmethod
    def from_dict(cls, d) -> "Agent":
        return cls(id=d["id"], role=d["role"], elo=d["elo"], memory=list(d.get("memory", [])))


def update_elo(winner: Agent, loser: Agent, k: float = 24.0) -> None:
    exp_w = 1 / (1 + 10 ** ((loser.elo - winner.elo) / 400))
    winner.elo += k * (1 - exp_w)
    loser.elo -= k * (1 - exp_w)
