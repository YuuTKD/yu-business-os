"""Minimal, dependency-free YAML-subset parser for registry/governance configs.

Why this exists
---------------
Phase A must run with **zero new third-party dependencies and zero network
access** (see YU_BUSINESS_OS_2 governance policies). PyYAML is not guaranteed to
be installed in every environment, so the registry loaders do::

    try:
        import yaml            # real PyYAML if available
        _load = yaml.safe_load
    except ImportError:
        from ._yaml_min import safe_load as _load

This module implements just enough of YAML to parse the registry files, which
are authored in a deliberately regular block style.

Supported
    * block mappings            ``key: value`` / ``key:`` + nested block
    * block sequences           ``- item``
    * sequences of mappings      ``- key: value`` (+ sibling keys indented)
    * scalars                    bare / single- / double-quoted strings,
                                 integers, floats, booleans, null
    * ``#`` inline comments (must be preceded by whitespace or start of line)

NOT supported (intentionally — the config files never use these)
    * flow style ``[a, b]`` / ``{a: b}``
    * anchors / aliases / tags
    * multi-document streams
    * block scalars ``|`` / ``>``

The parser is intentionally strict-but-small. If it meets a construct it does
not understand it raises ``YamlMinError`` rather than guessing, so a malformed
config surfaces as INVALID_CONFIG instead of silently wrong data.
"""

from __future__ import annotations

from typing import Any, List, Tuple

__all__ = ["safe_load", "YamlMinError"]


class YamlMinError(ValueError):
    """Raised when the input is outside the supported YAML subset."""


def _strip_inline_comment(raw: str) -> str:
    """Remove a trailing ``# ...`` comment, respecting quotes."""
    in_single = False
    in_double = False
    for i, ch in enumerate(raw):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            # YAML requires whitespace before an inline comment.
            if i == 0 or raw[i - 1] in (" ", "\t"):
                return raw[:i]
    return raw


def _tokenize(text: str) -> List[Tuple[int, str]]:
    """Return ``(indent, content)`` for each significant line."""
    tokens: List[Tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        # Normalise tabs to avoid ambiguous indentation.
        if "\t" in line[: len(line) - len(line.lstrip("\t "))]:
            raise YamlMinError(f"tab indentation is not supported (line {lineno})")
        stripped = _strip_inline_comment(line).rstrip()
        if not stripped.strip():
            continue
        if stripped.lstrip().startswith("---") or stripped.lstrip().startswith("..."):
            # Document markers are ignored (single-document only).
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        tokens.append((indent, stripped.lstrip(" ")))
    return tokens


def _parse_scalar(text: str) -> Any:
    s = text.strip()
    if s == "":
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    # Empty flow collections are the only flow forms we accept.
    if s == "[]":
        return []
    if s == "{}":
        return {}
    low = s.lower()
    if low in ("null", "~", "none"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    # int
    try:
        if s.lstrip("-+").isdigit():
            return int(s)
    except ValueError:
        pass
    # float
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_block(tokens: List[Tuple[int, str]], start: int, indent: int) -> Tuple[Any, int]:
    """Parse the block whose lines are indented at exactly ``indent``.

    Returns ``(value, next_index)``.
    """
    if start >= len(tokens):
        return None, start

    first_indent, first_content = tokens[start]
    if first_indent != indent:
        raise YamlMinError(
            f"unexpected indent {first_indent}, expected {indent}: {first_content!r}"
        )

    if first_content.startswith("- ") or first_content == "-":
        return _parse_sequence(tokens, start, indent)
    return _parse_mapping(tokens, start, indent)


def _parse_sequence(tokens, start, indent):
    seq: List[Any] = []
    i = start
    while i < len(tokens):
        ind, content = tokens[i]
        if ind < indent:
            break
        if ind != indent or not (content.startswith("- ") or content == "-"):
            if ind > indent:
                raise YamlMinError(f"bad sequence nesting near {content!r}")
            break
        item_text = content[1:].lstrip(" ") if content != "-" else ""
        item_indent = indent + (len(content) - len(content.lstrip("- ")))
        if item_indent <= indent:
            item_indent = indent + 2

        if item_text == "":
            # Value lives on the following, more-indented lines.
            value, i = _parse_block(tokens, i + 1, tokens[i + 1][0]) if i + 1 < len(tokens) else (None, i + 1)
            seq.append(value)
            continue

        if _looks_like_mapping_entry(item_text):
            # Build a synthetic mapping: first key on this line, siblings on the
            # following lines that are indented past the dash.
            synthetic: List[Tuple[int, str]] = [(item_indent, item_text)]
            j = i + 1
            while j < len(tokens) and tokens[j][0] >= item_indent and not _is_sequence_item_at(tokens[j], indent):
                synthetic.append(tokens[j])
                j += 1
            value, _ = _parse_mapping(synthetic, 0, item_indent)
            seq.append(value)
            i = j
        else:
            seq.append(_parse_scalar(item_text))
            i += 1
    return seq, i


def _is_sequence_item_at(token, indent) -> bool:
    ind, content = token
    return ind == indent and (content.startswith("- ") or content == "-")


def _looks_like_mapping_entry(text: str) -> bool:
    """True if ``text`` is ``key:`` or ``key: value`` (not a bare scalar)."""
    in_single = in_double = False
    for i, ch in enumerate(text):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ":" and not in_single and not in_double:
            if i + 1 == len(text) or text[i + 1] == " ":
                return True
    return False


def _split_key_value(text: str) -> Tuple[str, str]:
    in_single = in_double = False
    for i, ch in enumerate(text):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ":" and not in_single and not in_double:
            if i + 1 == len(text) or text[i + 1] == " ":
                key = text[:i].strip()
                if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
                    key = key[1:-1]
                return key, text[i + 1 :].strip()
    raise YamlMinError(f"not a mapping entry: {text!r}")


def _parse_mapping(tokens, start, indent):
    mapping: dict = {}
    i = start
    while i < len(tokens):
        ind, content = tokens[i]
        if ind < indent:
            break
        if ind > indent:
            raise YamlMinError(f"unexpected deeper indent near {content!r}")
        if content.startswith("- ") or content == "-":
            raise YamlMinError(f"sequence item where mapping expected: {content!r}")
        key, inline = _split_key_value(content)
        if inline != "":
            mapping[key] = _parse_scalar(inline)
            i += 1
            continue
        # Nested block or empty value.
        if i + 1 < len(tokens) and tokens[i + 1][0] > indent:
            child_indent = tokens[i + 1][0]
            value, i = _parse_block(tokens, i + 1, child_indent)
            mapping[key] = value
        else:
            mapping[key] = None
            i += 1
    return mapping, i


def safe_load(text: str) -> Any:
    """Parse a YAML-subset document and return Python data (or ``None``)."""
    if text is None:
        return None
    tokens = _tokenize(text)
    if not tokens:
        return None
    value, _ = _parse_block(tokens, 0, tokens[0][0])
    return value
