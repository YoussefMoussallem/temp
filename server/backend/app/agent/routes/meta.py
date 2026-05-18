"""Metadata + stub endpoints under /agent.

  GET  /agent/skills        — discoverable skills (for the /skills slash UI)
  GET  /agent/models        — available LiteLLM models
  GET  /agent/commands      — canonical command registry (typeahead + dispatch)
  POST /agent/compact       — 501 stub (Phase 3)
  POST /agent/context       — 501 stub (Phase 3)
  GET  /agent/usage         — 501 stub (Phase 5)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["agent"])


def _not_implemented():
    raise HTTPException(
        status_code=501,
        detail="Endpoint not yet implemented in current phase.",
    )


@router.post("/compact")
async def compact():
    """Compact endpoint — Phase 3."""
    _not_implemented()


@router.post("/context")
async def context():
    """Context stats endpoint — Phase 3."""
    _not_implemented()


@router.get("/usage")
async def usage():
    """Per-session usage display — Phase 5."""
    _not_implemented()


@router.get("/skills")
async def list_skills():
    """List all available skills.

    Skills are PromptCommands (Phase 2.7b.1) loaded from
    ``skills/bundled``, ``~/.edwin/skills``, and ``<cwd>/.edwin/skills``.
    The /commands endpoint already returns these too — this endpoint is a
    skills-only filter for the legacy ``/skills`` slash command's UI.
    """
    from ..skills.discovery import discover_skills

    return [
        {
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "aliases": list(s.get("aliases") or []),
            "when_to_use": s.get("when_to_use", ""),
        }
        for s in await discover_skills()
        if not s.get("is_hidden")
    ]


@router.get("/models")
def list_models():
    """Return all available models from the LiteLLM proxy."""
    from app.bridges.litellm_bridge import get_all_model_info

    return [{"id": m["name"], **m} for m in get_all_model_info()]


@router.get("/commands")
async def list_commands():
    """Canonical command registry. Frontend uses this for typeahead + dispatch.

    For each command:
      - name, description, aliases, argument_hint: presentation metadata
      - type: "prompt" | "local"
      - execution: "server" — backend runs it (prompt or local); frontend
        sends via /turn and waits for expansion / lifecycle.
      - execution: "client" — frontend runs it; backend only holds metadata
        so discovery is unified. Frontend looks up a local handler by name.
    """
    from ..commands import get_command_name, load_all_commands

    out = []
    for c in await load_all_commands():
        out.append(
            {
                "name": get_command_name(c),
                "description": c.get("description", ""),
                "aliases": list(c.get("aliases") or []),
                "argument_hint": c.get("argument_hint", ""),
                "type": c.get("type", "local"),
                # Prompt commands always execute server-side. Local commands
                # carry an explicit execution tag (defaults to server if missing).
                "execution": c.get("execution", "server"),
                "is_hidden": bool(c.get("is_hidden", False)),
            }
        )
    return out
