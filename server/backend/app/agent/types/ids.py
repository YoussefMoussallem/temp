"""
Branded types for session and agent IDs.

Port of src/types/ids.ts. Python uses NewType to mimic TS branded types.
NewType doesn't enforce at runtime but provides static type-checker safety.
"""

from __future__ import annotations

import re
from typing import NewType

# A session ID uniquely identifies a session.
SessionId = NewType("SessionId", str)

# An agent ID uniquely identifies a subagent within a session.
# When present, indicates the context is a subagent (not the main session).
AgentId = NewType("AgentId", str)


def as_session_id(id: str) -> SessionId:
    """Cast a raw string to SessionId. Use sparingly."""
    return SessionId(id)


def as_agent_id(id: str) -> AgentId:
    """Cast a raw string to AgentId. Use sparingly."""
    return AgentId(id)


_AGENT_ID_PATTERN = re.compile(r"^a(?:.+-)?[0-9a-f]{16}$")


def to_agent_id(s: str) -> AgentId | None:
    """
    Validate and brand a string as AgentId.

    Matches the format produced by create_agent_id(): `a` + optional `<label>-` + 16 hex chars.
    Returns None if the string doesn't match (e.g. teammate names, team-addressing).
    """
    return AgentId(s) if _AGENT_ID_PATTERN.match(s) else None
