"""Optional public Desktop notification door; SQLite/poll is authoritative."""

def broadcast(event, payload):
    from hermes_cli.plugin_events import broadcast_plugin_event
    broadcast_plugin_event('pulse-rings', event, payload)


def emit(event, payload):
    try:
        broadcast(event, payload)
    except Exception:
        # Standalone agent processes and disconnected gateways are normal.
        pass
