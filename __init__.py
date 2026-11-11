"""Pulsr: agent drafts, human decisions; scoped MCP compatibility shim."""
from pathlib import Path


def register(ctx):
    from .pulse_rings.engine import Engine
    # Dashboard uses a path-unique package. Bind both plugin-owned namespaces;
    # no core/global dispatch override and no credentials or live config reads.
    if callable(getattr(ctx, 'call_mcp', None)):
        from .pulse_rings.mcp_access import bind_context
        from .dashboard.pulse import bind_mcp_context
        bind_context(ctx)
        bind_mcp_context(ctx)
        # One path-unique collector namespace shared with the dashboard backend.
        # Registration is synchronous; no running asyncio loop is assumed.
        from .dashboard.pulse import bind_background_context
        bind_background_context(ctx)
    # === Session pulses ===
    from .dashboard.pulse import bind_session_context
    bind_session_context(ctx)
    from .pulse_rings.hooks import register_hooks
    from .pulse_rings.authoring import RunContexts, register_tools, rings_command
    contexts = RunContexts(ctx)
    register_hooks(ctx, context_observer=contexts.observe)
    register_tools(ctx, contexts, Engine)
    ctx.register_command('rings', handler=rings_command(Engine, approver_ids=ctx.get_config('approver_ids', [])),
                         description='List/show pulses; human-only approve/reject drafts',
                         args_hint='[list|show <id>|approve <id>|reject <id>]')
    ctx.register_skill('authoring', Path(__file__).parent / 'skills' / 'authoring' / 'SKILL.md')
    ctx.register_skill('pulse-notes', Path(__file__).parent / 'skills' / 'pulse-notes' / 'SKILL.md')
