"""Optional per-child selection through Hermes' upstream delegation backend API."""
from collections.abc import Mapping
from agent.delegation_provider import DelegationProvider, DelegationRouteError
from . import difficulty


class RetainedRouting(DelegationProvider):
    def __init__(self, ctx, *, name="per-task"):
        self.ctx = ctx
        self._name = name

    @property
    def name(self):
        return self._name

    @property
    def display_name(self):
        return "Per-task routing" if self.name == "per-task" else "Per-task routing (legacy: resumable)"

    @property
    def summary(self):
        return "Choose models and providers per task, with optional difficulty routes."

    def settings(self, config):
        # Keep saved backend pins and earlier profile configuration usable.
        # An explicit canonical block, including {}, takes precedence.
        backends = config.get("backends") if isinstance(config, Mapping) else None
        if not isinstance(backends, Mapping):
            return {}
        selected = backends.get("per-task") if "per-task" in backends else backends.get("resumable")
        return selected if isinstance(selected, Mapping) else {}

    def is_available(self):
        return self.ctx.get_config("enabled", True) is True

    def task_parameters(self, config):
        return {
            **difficulty.parameters(self.settings(config)),
            "child_model": {"type": "string", "description":
                "Optional model for this new child. Keeps the configured provider/endpoint unless child_provider is supplied."},
            "child_provider": {"type": "string", "description":
                "Optional configured provider name; requires child_model. Use a specific name, not auto. "
                "Hermes resolves its current credentials and transport from this profile."},
        }

    def description(self, config):
        return ("Set tasks[].child_model and optionally child_provider to choose a route per child. "
                "An invalid route refuses that task; valid siblings still run.")

    def route_task(self, task, config):
        # Match upstream's default strategy when no selector is supplied. Speed
        # tier is an explicit backend decision, not an arbitrary config passthrough.
        route = difficulty.route_for(task, config, self.settings(config))
        pins = {}
        for field, target in (("child_model", "model"), ("child_provider", "provider")):
            if field in task:
                value = task[field]
                if not isinstance(value, str) or not value.strip():
                    raise DelegationRouteError(f"{field} must be a non-empty string.")
                pins[target] = value.strip()
        if "provider" in pins:
            if "model" not in pins or pins["provider"].lower() == "auto":
                raise DelegationRouteError("child_provider requires child_model and a named provider other than auto.")
            # A different provider must not inherit the default endpoint, secrets,
            # transport, request overrides or fallback chain.
            for key in ("base_url", "api_key", "api_mode", "request_overrides", "command", "args"):
                route.pop(key, None)
            route["fallback_providers"] = []
        return {**route, **pins}
