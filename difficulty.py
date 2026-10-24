"""Optional difficulty choices; configuration stays in the routing backend."""
from copy import deepcopy
from agent.delegation_provider import DelegationRouteError

LEVELS = ("easy", "medium", "hard")
ROUTE_KEYS = frozenset({
    "model", "provider", "base_url", "api_key", "api_mode", "request_overrides",
    "fallback_providers", "reasoning_effort",
})


def parameters(settings):
    routes = settings.get("difficulty_routes")
    choices = [level for level in LEVELS if isinstance(routes, dict) and isinstance(routes.get(level), dict)]
    return {"difficulty": {"type": "string", "enum": choices, "description":
        "Choose by judgment needed, not length: easy for clear procedures; medium for bounded investigation; "
        "hard for ambiguity, costly mistakes, visual work or difficult synthesis. Omit for the default route. "
        "Children may reassess their own subtasks. child_model/child_provider override this choice."}} if choices else {}


def route_for(task, config, settings):
    routes = settings.get("difficulty_routes") or {}
    if not isinstance(routes, dict):
        raise DelegationRouteError("per-task difficulty_routes must be a mapping.")
    route = deepcopy({k: v for k, v in config.items() if k != "service_tier"})
    level = task.get("difficulty")
    if level is None:
        return route
    if not isinstance(level, str) or level not in LEVELS:
        raise DelegationRouteError("difficulty must be easy, medium, or hard.")
    if level not in routes:
        raise DelegationRouteError(f"No configured difficulty route for {level!r}.")
    selected = routes[level]
    if not isinstance(selected, dict):
        raise DelegationRouteError(f"difficulty_routes.{level} must be a mapping.")
    unknown = set(selected) - ROUTE_KEYS
    if unknown:
        raise DelegationRouteError(f"Unsupported delegation route settings: {', '.join(sorted(unknown))}.")
    route.update(deepcopy(selected))
    route["label"] = level
    return route
