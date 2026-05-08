"""
Slash-command parser.

Port of src/utils/slashCommandParsing.ts. Parses `/name args...` style input
into a `(name, args)` tuple, or returns None if the input isn't a valid slash
command.

Source behavior this mirrors:
  - Leading/trailing whitespace is trimmed before evaluation.
  - Must start with a single `/` followed by at least one non-whitespace char.
  - The name is everything up to the first whitespace; args are the rest, also
    trimmed.
  - Empty input ("" or "/"), or input not starting with `/`, returns None.
  - MCP-style colon-separated names ("/mcp:foo") are preserved verbatim — the
    parser does NOT split on `:`. Registry lookup handles those.
"""

from __future__ import annotations

import re


# Matches optional leading whitespace, a single '/', then a non-empty name
# that contains no whitespace. `re.DOTALL` is unnecessary — we match only the
# prefix; args follow after.
_SLASH_COMMAND_RE = re.compile(r"^\s*/(\S+)(?:\s+(.*))?\s*$", re.DOTALL)


def parse_slash_command(input_str: str) -> tuple[str, str] | None:
    """
    Parse a `/command args` string.

    Returns (name, args) where:
      - name is lowercased for case-insensitive registry matching (source does
        this inside findCommand, but doing it here keeps the type of `name`
        always normalized).
      - args is the trimmed remainder, possibly "".

    Returns None if the input is not a slash command.
    """
    if not isinstance(input_str, str) or not input_str.strip():
        return None
    m = _SLASH_COMMAND_RE.match(input_str)
    if not m:
        return None
    name = (m.group(1) or "").strip()
    if not name:
        return None
    args = (m.group(2) or "").strip()
    return name.lower(), args


def is_slash_command(input_str: str) -> bool:
    """Cheap check — doesn't fully parse. Matches source's isCommandInput."""
    if not isinstance(input_str, str):
        return False
    return input_str.lstrip().startswith("/")
