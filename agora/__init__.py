"""agora — a co-scientist agent society with bounded cost and a swappable Oracle."""
from .config import Config
from .colony import Colony
from .oracles import (Oracle, RotaryOracle, DrugRepurposingOracle,
                      FormulaSynthesisOracle, ORACLES,
                      DIFFICULTY, BENCHMARKS, difficulty_of, targets_at,
                      default_target, benchmark)
from .agent import Agent
from .roles import (Role, ROLE_REGISTRY, BASE_ROSTER, QUANT_ROSTER, FORMAL_ROSTER,
                    PROPOSER, CRITIC, VALIDATOR, get_role, kind_of, assign_roles)
from .cost import CostTracker, SpendCapExceeded

__all__ = ["Config", "Colony", "Oracle", "RotaryOracle", "DrugRepurposingOracle",
           "FormulaSynthesisOracle", "ORACLES",
           "DIFFICULTY", "BENCHMARKS", "difficulty_of", "targets_at",
           "default_target", "benchmark", "Agent", "Role", "ROLE_REGISTRY",
           "BASE_ROSTER", "QUANT_ROSTER", "FORMAL_ROSTER",
           "PROPOSER", "CRITIC", "VALIDATOR", "get_role", "kind_of", "assign_roles",
           "CostTracker", "SpendCapExceeded"]
__version__ = "1.2.1"
