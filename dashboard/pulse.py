"""Compatibility imports for old smoke scripts; implementation lives in pulse_rings.

The dashboard host imports this file outside the plugin package. Load only this
plugin's adjacent package under a path-unique namespace, never alter sys.path or
Hermes modules. No polling, profile resolution or storage I/O at import time.
"""
import hashlib
import importlib.util
from pathlib import Path
import sys
import urllib.error
import urllib.request

_root = Path(__file__).resolve().parents[1] / 'pulse_rings'
_name = '_pulse_rings_' + hashlib.sha256(str(_root).encode()).hexdigest()[:12]
if _name not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_name, _root / '__init__.py', submodule_search_locations=[str(_root)])
    assert _spec is not None and _spec.loader is not None
    _package = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _package  # Registers only our path-unique package so Python relative imports work; no core override.
    _spec.loader.exec_module(_package)
_engine = __import__(_name + '.engine', fromlist=['Engine'])
_discord = __import__(_name + '.sources.discord', fromlist=['DiscordSource'])
_icons = __import__(_name + '.icons', fromlist=['IconCache'])
_net = __import__(_name + '.net', fromlist=['Net'])
_authoring = __import__(_name + '.authoring', fromlist=['catalog'])
_mcp_access = __import__(_name + '.mcp_access', fromlist=['bind_context'])
bind_mcp_context = _mcp_access.bind_context
_background = __import__(_name + '.background', fromlist=['bind_context'])
bind_background_context = _background.bind_context
ensure_collection = _background.ensure
# === Session pulses ===
_sessions = __import__(_name + '.sessions', fromlist=['bind_context'])
bind_session_context = _sessions.bind_context
catalog = _authoring.catalog
ValidationError = _authoring.ValidationError
Pulse = Engine = _engine.Engine
movement = _engine.movement
parse_invite = _discord.parse_invite
normalize_invite = _discord.normalize_invite
discord_get = _discord.discord_get
DiscordError = _discord.DiscordError
discord_icon_get = _icons.discord_icon_get
image_type = _icons.image_type
GUILD_RE = _icons.GUILD_RE
ICON_RE = _icons.ICON_RE
ICON_LIMIT = _icons.ICON_LIMIT
NoRedirect = _net.NoRedirect
