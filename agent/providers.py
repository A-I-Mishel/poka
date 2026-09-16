"""Provider tier table: cascade order and construction entry points.

Boundary: config.py constructs provider clients (model, temperature,
native timeouts) and fixes cascade ORDER (config.TIER_GETTERS);
this alias keeps `agent.TIER_AGENT_GETTERS` importers working.
Selection, cooldown, and fallback live in agent.cascade; invocation
in agent.executor; error translation in agent.cascade.
"""

# Single source of truth: config.TIER_GETTERS fixes cascade order;
# this alias keeps `agent.TIER_AGENT_GETTERS` importers working.
from config import TIER_GETTERS as TIER_AGENT_GETTERS

__all__ = ["TIER_AGENT_GETTERS"]
