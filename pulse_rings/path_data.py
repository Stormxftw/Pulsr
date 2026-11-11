"""Strict SVG path-data parser, not an SVG/XML sanitizer.

Only the SVG path commands and finite numeric arguments are accepted. Command
arity, initial moveto, arc flags/radii and comma placement are checked as well.
"""
import math
import re

_NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
_ARITY = {'m': 2, 'l': 2, 'h': 1, 'v': 1, 'c': 6, 's': 4, 'q': 4, 't': 2, 'a': 7}
_COMMANDS = 'MmLlHhVvCcSsQqTtAaZz'


def valid_path(path):
    if not isinstance(path, str) or not path or len(path) > 256 * 1024:
        return False
    i, command, count, previous_number = 0, None, 0, False
    def complete():
        return command == 'z' or (command in _ARITY and count > 0 and count % _ARITY[command] == 0)
    while i < len(path):
        while i < len(path) and path[i] in ' \t\r\n':
            i += 1
        comma = i < len(path) and path[i] == ','
        if comma:
            if not previous_number:
                return False
            i += 1
            while i < len(path) and path[i] in ' \t\r\n':
                i += 1
            if i == len(path) or path[i] in _COMMANDS:
                return False
        if i == len(path):
            break
        if path[i] in _COMMANDS:
            if command is None:
                if path[i] not in 'Mm':
                    return False
            elif not complete():
                return False
            command, count, previous_number = path[i].lower(), 0, False
            i += 1
            continue
        if command not in _ARITY:
            return False
        index = count % _ARITY[command]
        if command == 'a' and index in (3, 4):
            # SVG allows compact flags, e.g. a1 1 0 011 2.
            if path[i] not in '01':
                return False
            value, i = float(path[i]), i + 1
        else:
            match = _NUMBER.match(path, i)
            if not match:
                return False
            value, i = float(match.group()), match.end()
        if not math.isfinite(value) or (command == 'a' and index in (0, 1) and value < 0):
            return False
        count += 1
        previous_number = True
    return complete()
