"""Native plugin entrypoint; importing the manifest package has no side effects."""

def register(ctx):
    if not hasattr(ctx, "register_subagent_extension"):
        raise RuntimeError("resumable-delegation requires Hermes' subagent extension API")
    from .policy import RetainedDelegation
    ctx.register_subagent_extension(RetainedDelegation(ctx))
    from .routing import RetainedRouting
    ctx.register_delegation_provider(RetainedRouting(ctx))
