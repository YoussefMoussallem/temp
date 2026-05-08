"""
SkillTool — agent-invocable wrapper around a discovered skill.

Lets the model autonomously invoke any registered skill mid-turn. The
tool looks up the skill, expands its prompt template with the model's
``args`` substituted into ``${ARGS}``, and returns the expanded text
as the tool result. The model then reads its own tool result and
follows those instructions on the next iteration of the loop.

This is Phase 2.7b.3 — Option B (no fork). The full plan calls for a
forked sub-agent, but the architectural prerequisite (abort-controller
plumbing in ``ToolUseContext``) hasn't landed; see "FOLLOW-UP: forking"
below for what would change.

==============================================================================
FOLLOW-UP: forking (Option A)
==============================================================================

This MVP runs each skill *inline* — the model invokes ``Skill``, reads
the expansion as a tool_result, and continues its current turn. That
means:

  - The skill's ``allowed_tools`` frontmatter is advisory only. The
    parent has every tool registered; nothing prevents the model from
    using a tool the skill said to avoid.
  - The skill's intermediate tool calls (if any) interleave with the
    parent's history, growing context proportional to skill length.
  - There is no per-skill abort. The user's existing Stop button kills
    the whole turn (parent + skill).
  - There is no separate UI block for the skill — its expansion shows
    up as a single tool_result entry; subsequent assistant work renders
    as normal turn flow.

A future port (Option A) would:

  1. Add ``abortController`` to ``ToolUseContext`` (Tool.py:142 marks
     this as deferred).
  2. Add ``utils/forked_agent.py`` — spawns a sub-``query()`` with a
     fresh context (empty messages, filtered tools per ``allowed_tools``,
     own abort signal). Streams sub-events back so the parent UI can
     render them as a nested collapsible block.
  3. Change ``SkillTool.call`` here to delegate to ``fork_agent(...)``,
     return only the sub-agent's final assistant text as the tool result.
  4. Add frontend nested rendering — collapsible "Running /<name>..."
     block grouping the sub-agent's tool calls.

When fork pays off:
  - Skills with strict ``allowed_tools`` enforcement (security).
  - Skills with their own system prompt (different persona).
  - Skill-calls-skill (recursion stays clean).
  - Long skills where keeping intermediate state out of parent saves tokens.

For Edwin's current 4 bundled skills (outline-deck, pitch-rewrite,
simplify, speaker-notes) — none of those drivers apply, so MVP is
sufficient. Revisit when the first skill that needs one of those
properties shows up.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ...Tool import (
    BaseTool,
    ToolResult,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, SKILL_TOOL_NAME


class SkillToolInput(BaseModel):
    name: str = Field(
        description=(
            "Skill name without the leading slash, e.g. 'outline-deck'. "
            "Aliases listed in the skill inventory also work. Case-insensitive."
        ),
    )
    args: str = Field(
        default="",
        description=(
            "Arguments to substitute into the skill's ${ARGS} token. "
            "Same shape as what a user would type after the slash command. "
            "Pass empty string if the skill takes no arguments."
        ),
    )


class SkillToolOutput(BaseModel):
    skill_name: str
    args: str
    instructions: str


class SkillToolImpl(BaseTool[SkillToolInput, SkillToolOutput]):
    name = SKILL_TOOL_NAME
    inputSchema = SkillToolInput
    # Skill bodies are short by convention (a few KB). Cap generously so a
    # large user/project skill doesn't get truncated mid-instruction.
    maxResultSizeChars = 50_000
    description_text = DESCRIPTION
    searchHint = "invoke a registered skill by name"

    def is_read_only(self, input: Any = None) -> bool:
        # The tool itself only reads the skill registry and substitutes
        # text — no IO, no mutation. Whether the skill's *instructions*
        # cause downstream writes is the parent agent's call, not ours.
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return True

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def description(self, input: Any, options: dict) -> str:
        name = (
            input.get("name", "") if isinstance(input, dict)
            else getattr(input, "name", "")
        )
        return f"Invoke skill /{name}" if name else "Invoke a skill"

    def user_facing_name(self, input: Any = None) -> str:
        return "Skill"

    async def validate_input(
        self, input: Any, context: ToolUseContext
    ) -> ValidationResult:
        name = (
            input.get("name", "") if isinstance(input, dict)
            else getattr(input, "name", "")
        )
        if not name or not str(name).strip():
            return ValidationError(
                message="`name` is required (e.g. 'outline-deck').",
                errorCode=1,
            )
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[SkillToolOutput]:
        """Look up the skill, expand its prompt template, return the
        instructions.

        Errors are raised — the query loop wraps any exception into an
        ``is_error: true`` tool_result automatically, matching the
        convention used by MCPTool/ReadMcpResourceTool. Don't catch
        and re-encode error states into the success path; the LLM
        relies on the ``is_error`` flag to know the call failed and
        decide whether to retry with a different skill.
        """
        # Late imports keep the tool module cheap to import — skills
        # discovery hits the filesystem.
        from ...skills.discovery import discover_skills  # noqa: PLC0415
        from ...commands import find_command  # noqa: PLC0415

        parsed: SkillToolInput = (
            args if isinstance(args, SkillToolInput) else SkillToolInput(**args)
        )

        if on_progress is not None:
            on_progress({"message": f"Looking up skill /{parsed.name}..."})

        skills = await discover_skills(None)
        skill = find_command(parsed.name, skills)

        if skill is None:
            available = ", ".join(
                f"/{s.get('name')}" for s in skills if not s.get("is_hidden")
            ) or "(none)"
            raise ValueError(
                f"Skill /{parsed.name} not found. "
                f"Available skills: {available}."
            )

        # Security: skills with disable_model_invocation are user-only.
        # The model must not be able to escalate by guessing the name.
        if skill.get("disable_model_invocation"):
            raise PermissionError(
                f"Skill /{parsed.name} is user-invocable only "
                f"(disable_model_invocation=true). Ask the user to run "
                f"it manually if needed."
            )

        if skill.get("type") != "prompt":
            # SkillTool is for PromptCommand skills (template expansion).
            # Local-type skills run server-side without a model in the
            # loop and don't fit the "instructions for you" contract.
            raise TypeError(
                f"Skill /{parsed.name} is not a prompt-template skill "
                f"and can't be invoked through Skill. The user can run "
                f"/{parsed.name} directly."
            )

        get_prompt = skill.get("get_prompt_for_command")
        if not callable(get_prompt):
            raise RuntimeError(
                f"Skill /{parsed.name} is malformed "
                f"(missing get_prompt_for_command)."
            )

        # Let exceptions from get_prompt propagate — they carry useful
        # context for the model (e.g. malformed args, FS errors on a
        # skill that reads sibling files via ${SKILL_DIR}).
        blocks = await get_prompt(parsed.args, context)

        body = "".join(
            b.get("text", "")
            for b in (blocks or [])
            if isinstance(b, dict) and b.get("type") == "text"
        )
        if not body.strip():
            raise RuntimeError(
                f"Skill /{parsed.name} expanded to empty body."
            )

        canonical_name = skill.get("name") or parsed.name
        return ToolResult(
            data=SkillToolOutput(
                skill_name=canonical_name,
                args=parsed.args,
                instructions=body,
            ),
        )

    def map_tool_result_to_block(
        self, content: SkillToolOutput, tool_use_id: str
    ) -> dict:
        # The model needs three things in the result text: which skill
        # ran, what args it received, and the instructions to follow.
        # Wrap explicitly so the model can disambiguate skill output from
        # its own prior context — the framing also makes prompt-injection
        # via the skill body more visible in transcripts.
        if isinstance(content, SkillToolOutput):
            text = (
                f"Skill: /{content.skill_name}\n"
                f"Args: {content.args}\n"
                f"\n"
                f"Instructions (follow these to answer the user):\n"
                f"---\n"
                f"{content.instructions}\n"
                f"---"
            )
        else:
            text = str(content)
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": text,
        }


SkillTool = SkillToolImpl()
