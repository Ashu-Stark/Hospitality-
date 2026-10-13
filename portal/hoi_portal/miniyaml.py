"""A tiny reader for the YAML subset used by the portal's config files (no PyYAML on the deployed portal).

Supported: `#` comments, block mappings by indentation (`key: value` / `key:` + nested block), block lists
(`- scalar`), inline lists (`[1, 2, [3, 4]]`, nested), and scalars: integers, floats, true/false, null/~,
"double" or 'single' quoted strings and plain strings. Not supported (raises ValueError): inline mappings `{...}`,
anchors, multi-line strings, tabs. tests/test_traffic_model.py checks that it reads traffic.yaml exactly like PyYAML.
"""

from __future__ import annotations

import re
from pathlib import Path

_INT = re.compile(r"^[-+]?\d+$")
_FLOAT = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")


def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def _split_top(s: str) -> list[str]:
    parts, depth, quote, cur = [], 0, None, ""
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def scalar(s: str):
    s = s.strip()
    if s.startswith("{"):
        raise ValueError("inline mappings are not supported")
    if s.startswith("["):
        if not s.endswith("]"):
            raise ValueError(f"unclosed list: {s}")
        return [scalar(p) for p in _split_top(s[1:-1])]
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", ""):
        return None
    if _INT.match(s):
        return int(s)
    if _FLOAT.match(s):
        return float(s)
    return s


def loads(text: str):
    lines = []
    for raw in text.splitlines():
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ValueError("tabs are not allowed for indentation")
        line = _strip_comment(raw)
        if line.strip():
            lines.append((len(line) - len(line.lstrip(" ")), line.strip()))

    def block(i: int, indent: int):
        if i < len(lines) and lines[i][1].startswith("- "):
            out = []
            while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
                out.append(scalar(lines[i][1][2:]))
                i += 1
            return out, i
        out: dict = {}
        while i < len(lines) and lines[i][0] == indent:
            content = lines[i][1]
            key, sep, rest = content.partition(":")
            if not sep:
                raise ValueError(f"expected 'key: value': {content}")
            key = scalar(key)
            i += 1
            if rest.strip():
                out[key] = scalar(rest)
            elif i < len(lines) and lines[i][0] > indent:
                out[key], i = block(i, lines[i][0])
            else:
                out[key] = None
        return out, i

    if not lines:
        return None
    data, i = block(0, lines[0][0])
    if i != len(lines):
        raise ValueError(f"unexpected indentation near: {lines[i][1]}")
    return data


def load(path: Path):
    return loads(Path(path).read_text(encoding="utf-8"))
