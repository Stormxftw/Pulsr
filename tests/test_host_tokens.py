"""The Desktop renderer must only depend on theme tokens the real Hermes host defines.

Regression: the plugin read ``var(--ui-bg)`` without a fallback. Hermes Desktop never
defines ``--ui-bg`` (it has ``--ui-bg-editor``, ``--ui-bg-elevated``, ...), so every colour
derived from it was invalid at computed-value time and the builder lost its field borders,
fills and selected states in the real host. The preview harness defined ``--ui-bg`` itself,
which hid the bug. Both directions are pinned here.
"""

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JS = ROOT / "desktop" / "plugin.js"
HARNESS_HTML = ROOT / "preview" / "index.html"

# Tokens defined by Hermes Desktop's global stylesheet / theme runtime
# (apps/desktop/src/styles.css plus the theme-applied status colours).
HOST_TOKENS = frozenset(
    """
    accent accent-secondary base bg-card bg-chrome bg-editor bg-elevated bg-input
    bg-primary bg-quaternary bg-quinary bg-secondary bg-sidebar bg-tertiary blue cyan
    green orange purple red yellow warm stroke-primary stroke-secondary stroke-tertiary
    stroke-quaternary text-primary text-secondary text-tertiary text-quaternary
    surface-background widget-surface-background editor-surface-background
    control-active-background control-hover-background row-active-background
    row-hover-background selection-background success warning danger
    """.split()
)

# Tokens the host does not always define; the plugin may only use these with a fallback.
OPTIONAL_TOKENS = frozenset({"success", "warning", "danger", "bg-elevated"})

_VAR = re.compile(r"var\(\s*--ui-([a-z0-9-]+)\s*([,)])")


def _uses(text):
    return [(m.group(1), m.group(2) == ",") for m in _VAR.finditer(text)]


def test_plugin_only_reads_host_defined_tokens():
    unknown = sorted({name for name, _ in _uses(PLUGIN_JS.read_text(encoding="utf-8")) if name not in HOST_TOKENS})
    assert unknown == [], f"plugin reads theme tokens Hermes does not define: {unknown}"


def test_optional_tokens_always_have_a_fallback():
    bare = sorted({name for name, has_fallback in _uses(PLUGIN_JS.read_text(encoding="utf-8"))
                   if name in OPTIONAL_TOKENS and not has_fallback})
    assert bare == [], f"optional host tokens used without a fallback: {bare}"


def test_harness_does_not_invent_host_tokens():
    defined = set(re.findall(r"--ui-([a-z0-9-]+)\s*:", HARNESS_HTML.read_text(encoding="utf-8")))
    invented = sorted(defined - HOST_TOKENS)
    assert invented == [], f"preview harness defines tokens the real host lacks: {invented}"


def test_token_list_matches_real_host_stylesheet_when_available():
    source = os.environ.get("HERMES_SOURCE")
    css = Path(source) / "apps" / "desktop" / "src" / "styles.css" if source else None
    if not css or not css.is_file():
        pytest.skip("set HERMES_SOURCE to a Hermes checkout to cross-check the host stylesheet")
    host = set(re.findall(r"--ui-([a-z0-9-]+)\s*:", css.read_text(encoding="utf-8")))
    required = {name for name, has_fallback in _uses(PLUGIN_JS.read_text(encoding="utf-8")) if not has_fallback}
    missing = sorted(required - host - OPTIONAL_TOKENS)
    assert missing == [], f"plugin requires tokens absent from {css}: {missing}"
