"""
Parse a single SKILL.md file into a PromptCommand.

Source: src/skills/frontmatterSkill.ts.

A SKILL.md is a markdown file with YAML frontmatter:

    ---
    name: outline-deck
    description: Turn a topic into a deck outline.
    argumentHint: <topic>
    aliases: [deck-outline, outline]
    allowedTools: [CreateSlide, UpdateSlide]
    isHidden: false
    ---
    Body becomes the prompt template, with ${ARGS} and ${SKILL_DIR}
    substituted at expansion time / parse time respectively.

Skills are first-class slash-commands — same dispatcher, same XML
wrapping, same lifecycle as built-ins from Phase 2.8.2. They land
in the registry through ``commands.loader.load_all_commands``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from app_logger import get_logger

from ..types.command import PromptCommand

log = get_logger(__name__)


# Substitution tokens. Source uses CLAUDE_-prefixed names; we keep the
# unprefixed Edwin-natural ones as primary and accept CLAUDE_ aliases
# so SKILL.md files copied from the source repo Just Work.
_SKILL_DIR_TOKENS = ("${SKILL_DIR}", "${CLAUDE_SKILL_DIR}")
_ARGS_TOKENS = ("${ARGS}",)
# ${SESSION_ID} / ${CLAUDE_SESSION_ID} substitution is deferred — Edwin's
# ToolUseContext doesn't carry conversation_id yet. TODO when forked-agent
# work lands in 2.7b.3.


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body). Empty dict + raw text if no
    frontmatter is present. Raises ValueError on malformed YAML so the
    directory walker can log + skip the offending file.
    """
    if not text.startswith("---"):
        return {}, text

    # First marker is the leading ---; find the closing one. Source's
    # parser uses a non-greedy regex; we match the same shape with split.
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    raw_fm = parts[1]
    body = parts[2].lstrip("\n")

    parsed = yaml.safe_load(raw_fm) or {}
    if not isinstance(parsed, dict):
        raise ValueError(f"frontmatter must parse to a mapping, got {type(parsed).__name__}")
    return parsed, body


def _replace_all(s: str, tokens: tuple[str, ...], value: str) -> str:
    for tok in tokens:
        s = s.replace(tok, value)
    return s


def _ensure_str(v: Any) -> str:
    """Coerce frontmatter values that callers expect to be strings.

    Lists become " | "-joined (matches author's likely intent for
    argumentHint/whenToUse-style fields). Anything else falls back to
    str(). Empty/None becomes the empty string.
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return " | ".join(str(x) for x in v if x is not None)
    return str(v)


def parse_skill_file(
    skill_md_path: Path,
    *,
    source: str = "bundled",
) -> PromptCommand:
    """Load a single SKILL.md, return a PromptCommand.

    ``source`` is one of "bundled", "user", "project" — drives the
    PromptCommand.source field used for last-wins layering in
    ``discovery.discover_skills``.

    Raises:
      - FileNotFoundError if path doesn't exist
      - ValueError if frontmatter is malformed or required keys are missing
    """
    text = skill_md_path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)

    name = fm.get("name")
    description = fm.get("description")
    if not name or not description:
        raise ValueError(f"SKILL.md at {skill_md_path} missing required name/description")

    skill_dir = str(skill_md_path.parent.resolve())

    # SKILL_DIR substitutes at parse time — the directory is known now and
    # never changes. ARGS substitutes at expansion time — see closure below.
    body_template = _replace_all(body, _SKILL_DIR_TOKENS, skill_dir)

    aliases = list(fm.get("aliases") or [])
    allowed_tools = fm.get("allowedTools") or fm.get("allowed_tools")
    # Coerce string-ish frontmatter fields. Authors sometimes write
    # ``argumentHint: [foo | bar]`` which YAML parses as a flow list —
    # render-time string ops blow up. Stringify defensively.
    argument_hint = _ensure_str(fm.get("argumentHint") or fm.get("argument_hint") or "")
    when_to_use = _ensure_str(fm.get("whenToUse") or fm.get("when_to_use") or "")
    is_hidden = bool(fm.get("isHidden") or fm.get("is_hidden") or False)
    model_override = fm.get("model")
    arg_names = fm.get("argNames") or fm.get("arg_names") or []
    # forceFork / fork is the per-skill opt-in for SkillTool fork mode.
    # When set, SkillTool spawns a fresh sub-query() (its own message
    # context, strict allowed_tools enforcement, base-agent persona,
    # caller intent threaded into the system prompt). Default = inline:
    # SkillTool returns the expanded body as a tool_result the caller
    # reads on its next iteration. Aliases ``forceFork`` (source TS) and
    # ``fork`` (edwin-native) both accepted.
    context_mode = (
        "fork"
        if (fm.get("forceFork") or fm.get("force_fork") or fm.get("fork"))
        else "inline"
    )
    # Fork lane: which built-in agent's persona the fork runs under. The
    # base agent provides the system prompt; the skill's overlay (below)
    # is appended. Default = "general-purpose" so an author who opts into
    # fork without specifying agent gets a sensible identity.
    base_agent = _ensure_str(fm.get("agent") or "")
    # Fork lane: optional text appended to the base agent's system prompt
    # so the skill author can layer additional framing on top of the base
    # persona without replacing it.
    system_prompt_overlay = _ensure_str(
        fm.get("systemPromptOverlay")
        or fm.get("system_prompt_overlay")
        or ""
    )

    async def _get_prompt(args: str, _ctx: Any) -> list[dict]:
        """Closure baked at parse time — captures the per-skill body
        template so each PromptCommand has its own substitution."""
        text = _replace_all(body_template, _ARGS_TOKENS, args or "")
        return [{"type": "text", "text": text}]

    cmd: PromptCommand = cast(
        PromptCommand,
        {
            "type": "prompt",
            "execution": "server",
            "name": name,
            "description": description,
            "aliases": aliases,
            "argument_hint": argument_hint,
            "when_to_use": when_to_use,
            "is_hidden": is_hidden,
            "loaded_from": "skills",
            "source": source,
            "skill_root": skill_dir,
            "context": context_mode,
            "progress_message": f"running skill {name}",
            "content_length": max(200, len(body_template) + 100),
            "get_prompt_for_command": _get_prompt,
        },
    )
    if allowed_tools:
        cmd["allowed_tools"] = list(allowed_tools)
    if model_override:
        cmd["model"] = model_override
    if arg_names:
        cmd["arg_names"] = list(arg_names)
    if base_agent:
        cmd["agent"] = base_agent
    if system_prompt_overlay:
        cmd["system_prompt_overlay"] = system_prompt_overlay

    return cmd
