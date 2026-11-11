"""Offline MCP parameter bounds, shared by validation and the adapter boundary."""
import json
import math
import re

NAME_PATTERN = r'^(?!.*__)[A-Za-z0-9][A-Za-z0-9_-]{0,63}(?![\s\S])'
_SECRET = re.compile(r'password|secret|token|authorization|api[_-]?key|cookie|credential', re.I)


def valid_args(value):
    """JSON only; <=2 KiB canonical UTF-8, 32 keys total, depth 6, 128 values.

    Credentials belong to Hermes, never persistent pulse definitions. This is a
    conservative key-name guard, NOT a detector for secrets hidden in values.
    """
    keys = nodes = 0
    def walk(node, depth):
        nonlocal keys, nodes
        nodes += 1
        if depth > 6 or nodes > 128:
            return False
        if isinstance(node, dict):
            keys += len(node)
            return keys <= 32 and all(isinstance(k, str) and not _SECRET.search(k)
                                      and walk(v, depth + 1) for k, v in node.items())
        if isinstance(node, list):
            return all(walk(v, depth + 1) for v in node)
        if node is None or type(node) in (str, bool, int):
            return True
        return type(node) is float and math.isfinite(node)
    try:
        return (isinstance(value, dict) and walk(value, 0)
                and len(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=False, allow_nan=False).encode('utf-8')) <= 2048)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return False
