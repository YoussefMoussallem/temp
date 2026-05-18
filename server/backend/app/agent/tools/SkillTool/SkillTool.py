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

import time
from typing import Any

from app_logger import get_logger
from pydantic import BaseModel, Field

from ...Tool import (
    BaseTool,
    ToolResult,
    Tools,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...types.hooks import CanUseToolFn
from ...types.ids import create_agent_id
from ...utils.messages import create_user_message
from ..AgentTool.exceptions import SubagentAwaitingFrontendTools
from ..AgentTool.types import PendingSubagentFrame
from .prompt import DESCRIPTION, SKILL_TOOL_NAME

log = get_logger(__name__)


# Recursion bound for skill-on-skill fork dispatch. With cap = 3, a
# fork can call another fork (A→B→C), but C cannot fork further.
# Inline-mode skills do not count against this depth.
MAX_SKILL_FORK_DEPTH = 3


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
    intent: str = Field(
        default="",
        description=(
            "Why you are invoking this skill right now and what you want "
            "the skill to keep in mind from the surrounding work. Required "
            "for fork-mode skills (the fork runs in an isolated loop and "
            "loses caller context otherwise); ignored for inline skills. "
            "1-3 sentences is enough."
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
        name = input.get("name", "") if isinstance(input, dict) else getattr(input, "name", "")
        return f"Invoke skill /{name}" if name else "Invoke a skill"

    def user_facing_name(self, input: Any = None) -> str:
        return "Skill"

    async def validate_input(self, input: Any, context: ToolUseContext) -> ValidationResult:
        name = input.get("name", "") if isinstance(input, dict) else getattr(input, "name", "")
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
    ) -> ToolResult[Any]:
        """Look up the skill and either expand inline or run as a fork.

        Errors are raised — the query loop wraps any exception into an
        ``is_error: true`` tool_result automatically, matching the
        convention used by MCPTool/ReadMcpResourceTool. Don't catch
        and re-encode error states into the success path; the LLM
        relies on the ``is_error`` flag to know the call failed and
        decide whether to retry with a different skill.

        Phase 6.B.1.7: resume detection runs first. When the parent
        Skill tool_use was orphan in a prior /turn (fork-skill paused
        on awaiting_frontend_tools), ``ClientState.pending_subagents``
        holds the frame keyed by ``parentToolUseId``. The fork's resume
        path picks up the frame and re-drives ``run_agent`` with the
        accumulated history.
        """
        # Late imports keep the tool module cheap to import — skills
        # discovery hits the filesystem.
        from ...skills.discovery import discover_skills  # noqa: PLC0415
        from ...commands import find_command  # noqa: PLC0415
        from ..AgentTool.AgentTool import _get_pending_bucket  # noqa: PLC0415

        # ── Resume detection (fork-skill only) ──────────────────────────
        my_tool_use_id = getattr(context, "toolUseId", None) or ""
        pending_bucket = _get_pending_bucket(context)
        for frame in pending_bucket:
            if not isinstance(frame, dict):
                continue
            if frame.get("originatingTool") != "Skill":
                continue
            if (
                frame.get("parentToolUseId") == my_tool_use_id
                and my_tool_use_id
            ):
                return await self._call_fork_resume(
                    resume_frame=frame,
                    pending_bucket=pending_bucket,
                    context=context,
                    can_use_tool=can_use_tool,
                    on_progress=on_progress,
                )

        # ── Fresh dispatch — parse + look up skill ──────────────────────
        parsed: SkillToolInput = (
            args if isinstance(args, SkillToolInput) else SkillToolInput(**args)
        )

        if on_progress is not None:
            on_progress({"message": f"Looking up skill /{parsed.name}..."})

        skills = await discover_skills(None)
        skill = find_command(parsed.name, skills)

        if skill is None:
            available = (
                ", ".join(f"/{s.get('name')}" for s in skills if not s.get("is_hidden")) or "(none)"
            )
            raise ValueError(f"Skill /{parsed.name} not found. Available skills: {available}.")

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

        # Branch: fork-mode skills run in an isolated sub-query() with
        # the skill's allowed_tools strictly enforced; inline skills
        # return the expanded body as a tool_result the caller reads
        # next iteration.
        if skill.get("context") == "fork":
            return await self._call_fork_fresh(
                skill=skill,
                parsed=parsed,
                context=context,
                can_use_tool=can_use_tool,
                on_progress=on_progress,
            )

        return await self._call_inline(skill=skill, parsed=parsed, context=context)

    async def _call_fork_fresh(
        self,
        *,
        skill: dict[str, Any],
        parsed: SkillToolInput,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        on_progress: Any | None = None,
    ) -> ToolResult[Any]:
        """Fork mode: spawn an isolated sub-``query()`` for the skill.

        The skill body becomes the kickoff user message; the system
        prompt = base agent's prompt + skill's ``system_prompt_overlay``
        + caller intent footer. The fork's tool pool is the skill's
        ``allowed_tools`` strictly enforced (not just advisory). On a
        cross-/turn pause, raises ``SubagentAwaitingFrontendTools`` with
        ``originatingTool="Skill"`` so the resume path picks it back up.
        """
        # Lazy imports — fork path pulls the AgentTool subsystem; the
        # inline path doesn't need it.
        from ...query.transitions import Terminal as _Terminal  # noqa: PLC0415
        from ...services.agents import merge_agent_definitions  # noqa: PLC0415
        from ...tools_registry import get_all_base_tools  # noqa: PLC0415
        from ..AgentTool.AgentTool import _emit_agent_progress_for_message  # noqa: PLC0415
        from ..AgentTool.agentToolUtils import finalize_agent_tool  # noqa: PLC0415
        from ..AgentTool.runAgent import run_agent  # noqa: PLC0415

        # ── Depth guard ─────────────────────────────────────────────────
        current_depth = getattr(context.options, "skillForkDepth", 0) or 0
        if current_depth >= MAX_SKILL_FORK_DEPTH:
            raise ValueError(
                f"Skill fork depth limit ({MAX_SKILL_FORK_DEPTH}) reached. "
                "A skill called you that was itself called by a skill that "
                "was itself called by a skill — too deep. Use inline skills "
                "or rework the flow."
            )
        new_depth = current_depth + 1

        # ── Expand the skill body ──────────────────────────────────────
        get_prompt = skill.get("get_prompt_for_command")
        if not callable(get_prompt):
            raise RuntimeError(
                f"Skill /{parsed.name} is malformed (missing get_prompt_for_command)."
            )
        blocks = await get_prompt(parsed.args, context)
        body = "".join(
            b.get("text", "")
            for b in (blocks or [])
            if isinstance(b, dict) and b.get("type") == "text"
        )
        if not body.strip():
            raise RuntimeError(f"Skill /{parsed.name} expanded to empty body.")

        canonical_name = skill.get("name") or parsed.name
        skill_args = parsed.args or ""
        intent = parsed.intent or ""

        # ── Resolve base agent ─────────────────────────────────────────
        # Skill picks the persona via ``agent`` frontmatter; default to
        # general-purpose so a skill that opts into fork without naming
        # an agent gets a sensible identity.
        base_type = skill.get("agent") or "general-purpose"
        registry = merge_agent_definitions()
        base_agent: dict[str, Any] | None = None
        for a in registry.get("activeAgents", []):
            if a.get("agentType") == base_type:
                base_agent = a
                break
        if base_agent is None:
            available = ", ".join(
                a.get("agentType", "")
                for a in registry.get("activeAgents", [])
            )
            raise ValueError(
                f"Skill /{canonical_name}: base agent '{base_type}' not "
                f"registered. Available: {available}"
            )

        # ── Build the effective forked agent definition ────────────────
        # Clone the base agent (shallow) so we can override fields without
        # mutating the registered built-in. Three overrides:
        #   - ``tools``: skill's allowed_tools (strict allowlist)
        #   - ``model``: skill's model override (if any) wins over base
        #   - ``getSystemPrompt``: wrapped to layer overlay + intent on top
        skill_overlay = skill.get("system_prompt_overlay") or ""
        base_get_prompt = base_agent.get("getSystemPrompt")

        def _wrapped_get_system_prompt(*, toolUseContext: Any = None, **_kw: Any) -> str:
            base_prompt = ""
            if callable(base_get_prompt):
                try:
                    base_prompt = base_get_prompt(toolUseContext=toolUseContext) or ""
                except Exception:  # noqa: BLE001
                    base_prompt = ""
            parts: list[str] = []
            if base_prompt:
                parts.append(base_prompt)
            if skill_overlay:
                parts.append(skill_overlay)
            if intent:
                parts.append(
                    "This skill was invoked with the following caller intent:\n"
                    + intent
                )
            return "\n\n".join(parts)

        forked_agent: dict[str, Any] = dict(base_agent)
        forked_agent["getSystemPrompt"] = _wrapped_get_system_prompt
        if skill.get("allowed_tools"):
            forked_agent["tools"] = list(skill["allowed_tools"])
        if skill.get("model"):
            forked_agent["model"] = skill["model"]

        # ── Worker pool — strip Skill if next depth would hit the cap ──
        # When new_depth == MAX, the spawned fork wouldn't be allowed to
        # fork further anyway; stripping Skill from its pool surfaces
        # the limit at tool-discovery time rather than via a runtime
        # error. Inline skills aren't blocked because they don't bump
        # the depth.
        worker_pool = get_all_base_tools()
        if new_depth >= MAX_SKILL_FORK_DEPTH:
            worker_pool = Tools(tools=[t for t in worker_pool if t.name != "Skill"])

        # ── Build kickoff + dispatch ────────────────────────────────────
        kickoff_text = (
            f"You are running the /{canonical_name} skill in fork mode.\n"
            f"Args: {skill_args or '(none)'}\n\n"
            f"---\n\n"
            f"{body}"
        )
        prompt_messages = [create_user_message(kickoff_text)]
        agent_id = create_agent_id(label=f"skill-{canonical_name}")
        start_time_ms = int(time.time() * 1000)
        my_tool_use_id = getattr(context, "toolUseId", None) or ""

        # Stamp new_depth onto parent options BEFORE run_agent so its
        # ``dataclasses.replace`` clones the bumped value into the sub-
        # context. Restore in finally so the caller's siblings see the
        # original depth. The mutation is contained because every fork
        # restores its own counter on exit.
        saved_depth = getattr(context.options, "skillForkDepth", 0) or 0
        context.options.skillForkDepth = new_depth

        # Initial kickoff progress emit so chat-ui captures the fork's
        # task line in the activity stream BEFORE the iterator starts.
        # Plain dict — query_loop's on_progress wraps it as the SSE
        # event's ``data`` field; wrapping in ToolProgress here would
        # nest the payload one level deep and the frontend's
        # `progress.type === "agent_progress"` check would miss.
        if on_progress is not None and my_tool_use_id:
            try:
                on_progress({
                    "type": "agent_progress",
                    "message": prompt_messages[0],
                    "prompt": intent or f"running /{canonical_name}",
                    "agentId": str(agent_id),
                })
            except Exception:  # noqa: BLE001
                log.exception("skill_fork_progress_forward_failed")

        try:
            agent_messages, pending_by_id, final_terminal = await self._drain_run_agent(
                agent_definition=forked_agent,
                prompt_messages=prompt_messages,
                context=context,
                can_use_tool=can_use_tool,
                available_tools=worker_pool,
                description=f"running /{canonical_name}",
                agent_id=agent_id,
                on_progress=on_progress,
                parent_tool_use_id=my_tool_use_id,
            )
        finally:
            context.options.skillForkDepth = saved_depth

        # ── Pause path ─────────────────────────────────────────────────
        if final_terminal is not None and final_terminal.reason in (
            "awaiting_frontend_tools",
            "tool_request",
        ):
            pending_tool_uses = list(pending_by_id.values())
            frame: PendingSubagentFrame = {
                "agentId": str(agent_id),
                "agentType": forked_agent.get("agentType", base_type),
                "parentToolUseId": "",  # query_loop catch site stamps
                "accumulatedMessages": agent_messages,
                "pendingToolUseIds": [
                    tu.get("id", "") for tu in pending_tool_uses if tu.get("id")
                ],
                "kickoffPrompt": kickoff_text,
                "startTimeMs": start_time_ms,
                "description": f"running /{canonical_name}",
                # SkillTool-fork fields — discriminate this frame from
                # AgentTool's. Resume will re-resolve the PromptCommand
                # by name + args + intent.
                "originatingTool": "Skill",
                "skillCommandName": canonical_name,
                "skillArgs": skill_args,
                "skillIntent": intent,
                "skillForkDepth": new_depth,
            }
            log.info(
                "skill_fork_pause",
                extra={
                    "skillName": canonical_name,
                    "agentId": str(agent_id),
                    "pendingCount": len(pending_tool_uses),
                    "depth": new_depth,
                },
            )
            raise SubagentAwaitingFrontendTools(
                frame=frame, tool_uses=pending_tool_uses
            )

        # ── Completion ─────────────────────────────────────────────────
        result_body = finalize_agent_tool(
            agent_messages,
            agent_id=str(agent_id),
            metadata={
                "prompt": kickoff_text,
                "resolvedAgentModel": forked_agent.get("model"),
                "isBuiltInAgent": True,  # base is always built-in in v1
                "startTime": start_time_ms,
                "agentType": forked_agent.get("agentType", base_type),
            },
        )
        sync_output: dict[str, Any] = {
            "status": "completed",
            "prompt": kickoff_text,
            "skill_name": canonical_name,
            "skill_args": skill_args,
            **result_body,
        }
        log.info(
            "skill_fork_complete",
            extra={
                "skillName": canonical_name,
                "agentId": str(agent_id),
                "messageCount": len(agent_messages),
                "depth": new_depth,
            },
        )
        return ToolResult(data=sync_output)

    async def _call_fork_resume(
        self,
        *,
        resume_frame: PendingSubagentFrame,
        pending_bucket: list[Any],
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        on_progress: Any | None = None,
    ) -> ToolResult[Any]:
        """Resume a paused fork-skill from its persisted frame.

        Mirrors ``AgentTool._call_resume``. Re-resolves the PromptCommand
        from the registry by ``frame.skillCommandName``; re-derives base
        agent + overlay + tool filter the same way the fresh dispatch
        did; feeds ``frame.accumulatedMessages`` (already augmented by
        the router pre-loop with the freshly-delivered tool_results)
        into ``run_agent`` and drives onward.
        """
        # Lazy imports — same justification as fresh path.
        from ...commands import find_command  # noqa: PLC0415
        from ...query.transitions import Terminal as _Terminal  # noqa: PLC0415
        from ...services.agents import merge_agent_definitions  # noqa: PLC0415
        from ...skills.discovery import discover_skills  # noqa: PLC0415
        from ...tools_registry import get_all_base_tools  # noqa: PLC0415
        from ..AgentTool.AgentTool import _emit_agent_progress_for_message  # noqa: PLC0415
        from ..AgentTool.agentToolUtils import finalize_agent_tool  # noqa: PLC0415
        from ..AgentTool.runAgent import run_agent  # noqa: PLC0415

        skill_name = resume_frame.get("skillCommandName", "")
        skill_args = resume_frame.get("skillArgs", "")
        intent = resume_frame.get("skillIntent", "")
        agent_id_str = resume_frame.get("agentId", "")
        agent_type = resume_frame.get("agentType", "")
        kickoff_text = resume_frame.get("kickoffPrompt", "")
        start_time_ms = int(resume_frame.get("startTimeMs", 0))
        depth = int(resume_frame.get("skillForkDepth", 1))
        accumulated_messages = list(resume_frame.get("accumulatedMessages") or [])

        # Re-resolve the skill from the registry. Skills are reloaded per
        # /turn so this picks up edits to the skill definition between
        # the pause and the resume.
        skills = await discover_skills(None)
        skill = find_command(skill_name, skills)
        if skill is None or skill.get("type") != "prompt":
            log.warning(
                "skill_fork_resume_unknown_skill",
                extra={"skillName": skill_name, "agentId": agent_id_str},
            )
            # Migrate the frame's pending tool_use_ids to the consumed-
            # ledger so the next /turn's router strips the tool_results
            # chat-ui sends back. Without this, the tool_results have no
            # frame AND no ledger entry → router passes them to the LLM
            # → 400.
            stale_pending_ids = list(resume_frame.get("pendingToolUseIds") or [])
            cs = getattr(context, "client_state", None)
            consumed = (
                getattr(cs, "consumed_subagent_tool_use_ids", None)
                if cs is not None
                else None
            )
            if isinstance(consumed, list) and stale_pending_ids:
                seen = set(consumed)
                for tid in stale_pending_ids:
                    if tid and tid not in seen:
                        consumed.append(tid)
                        seen.add(tid)
            try:
                pending_bucket.remove(resume_frame)
            except ValueError:
                pass
            return ToolResult(data={
                "status": "completed",
                "prompt": kickoff_text,
                "skill_name": skill_name,
                "agentId": agent_id_str,
                "agentType": agent_type,
                "content": [{
                    "type": "text",
                    "text": (
                        f"Skill fork resume failed: skill /{skill_name} "
                        "is no longer registered. The pending state was "
                        "discarded; ask the user to re-issue the request."
                    ),
                }],
                "totalDurationMs": 0,
                "totalTokens": 0,
                "totalToolUseCount": 0,
                "usage": {},
            })

        # Re-resolve base agent (matches fresh path).
        base_type = skill.get("agent") or "general-purpose"
        registry = merge_agent_definitions()
        base_agent: dict[str, Any] | None = None
        for a in registry.get("activeAgents", []):
            if a.get("agentType") == base_type:
                base_agent = a
                break
        if base_agent is None:
            try:
                pending_bucket.remove(resume_frame)
            except ValueError:
                pass
            raise ValueError(
                f"Skill fork resume: base agent '{base_type}' not registered."
            )

        # Rebuild the wrapped getSystemPrompt with the SAME overlay + intent
        # the fresh path used — the kickoff_text in accumulated_messages
        # already references it but the system prompt is recomposed every
        # iteration of the inner query() so it must stay stable across
        # resumes.
        skill_overlay = skill.get("system_prompt_overlay") or ""
        base_get_prompt = base_agent.get("getSystemPrompt")

        def _wrapped_get_system_prompt(*, toolUseContext: Any = None, **_kw: Any) -> str:
            base_prompt = ""
            if callable(base_get_prompt):
                try:
                    base_prompt = base_get_prompt(toolUseContext=toolUseContext) or ""
                except Exception:  # noqa: BLE001
                    base_prompt = ""
            parts: list[str] = []
            if base_prompt:
                parts.append(base_prompt)
            if skill_overlay:
                parts.append(skill_overlay)
            if intent:
                parts.append(
                    "This skill was invoked with the following caller intent:\n"
                    + intent
                )
            return "\n\n".join(parts)

        forked_agent: dict[str, Any] = dict(base_agent)
        forked_agent["getSystemPrompt"] = _wrapped_get_system_prompt
        if skill.get("allowed_tools"):
            forked_agent["tools"] = list(skill["allowed_tools"])
        if skill.get("model"):
            forked_agent["model"] = skill["model"]

        # Remove the stale frame BEFORE driving the loop so a re-pause
        # appends a FRESH frame instead of duplicating.
        try:
            pending_bucket.remove(resume_frame)
        except ValueError:
            pass

        worker_pool = get_all_base_tools()
        if depth >= MAX_SKILL_FORK_DEPTH:
            worker_pool = Tools(tools=[t for t in worker_pool if t.name != "Skill"])

        # Resume-replay: forward accumulated history via on_progress so
        # chat-ui's activity list picks up the user(tool_result) injected
        # by the router pre-loop. Same shape as AgentTool's resume.
        resume_parent_id = getattr(context, "toolUseId", None) or ""
        if on_progress is not None and resume_parent_id:
            for accumulated_event in accumulated_messages:
                if not isinstance(accumulated_event, dict):
                    continue
                if accumulated_event.get("type") not in ("user", "assistant"):
                    continue
                _emit_agent_progress_for_message(
                    accumulated_event,
                    on_progress=on_progress,
                    tool_use_id=resume_parent_id,
                    agent_id=agent_id_str,
                )

        # Stamp depth onto parent options for the duration of run_agent
        # so the sub-context inherits it via dataclasses.replace.
        saved_depth = getattr(context.options, "skillForkDepth", 0) or 0
        context.options.skillForkDepth = depth
        try:
            agent_messages, pending_by_id, final_terminal = await self._drain_run_agent(
                agent_definition=forked_agent,
                prompt_messages=accumulated_messages,
                context=context,
                can_use_tool=can_use_tool,
                available_tools=worker_pool,
                description=f"resuming /{skill_name}",
                agent_id=agent_id_str,
                on_progress=on_progress,
                parent_tool_use_id=resume_parent_id,
            )
        finally:
            context.options.skillForkDepth = saved_depth

        # Pause again: build new frame from accumulated + this iteration's
        # new messages.
        if final_terminal is not None and final_terminal.reason in (
            "awaiting_frontend_tools",
            "tool_request",
        ):
            pending_tool_uses = list(pending_by_id.values())
            new_frame: PendingSubagentFrame = {
                "agentId": agent_id_str,
                "agentType": agent_type,
                "parentToolUseId": "",
                "accumulatedMessages": accumulated_messages + agent_messages,
                "pendingToolUseIds": [
                    tu.get("id", "") for tu in pending_tool_uses if tu.get("id")
                ],
                "kickoffPrompt": kickoff_text,
                "startTimeMs": start_time_ms,
                "description": f"running /{skill_name}",
                "originatingTool": "Skill",
                "skillCommandName": skill_name,
                "skillArgs": skill_args,
                "skillIntent": intent,
                "skillForkDepth": depth,
            }
            log.info(
                "skill_fork_repause",
                extra={
                    "skillName": skill_name,
                    "agentId": agent_id_str,
                    "pendingCount": len(pending_tool_uses),
                    "depth": depth,
                },
            )
            raise SubagentAwaitingFrontendTools(
                frame=new_frame, tool_uses=pending_tool_uses
            )

        # Completion — finalize over FULL message history.
        full_messages = accumulated_messages + agent_messages
        result_body = finalize_agent_tool(
            full_messages,
            agent_id=agent_id_str,
            metadata={
                "prompt": kickoff_text,
                "resolvedAgentModel": forked_agent.get("model"),
                "isBuiltInAgent": True,
                "startTime": start_time_ms,
                "agentType": agent_type,
            },
        )
        sync_output: dict[str, Any] = {
            "status": "completed",
            "prompt": kickoff_text,
            "skill_name": skill_name,
            "skill_args": skill_args,
            **result_body,
        }
        log.info(
            "skill_fork_complete_after_resume",
            extra={
                "skillName": skill_name,
                "agentId": agent_id_str,
                "messageCount": len(full_messages),
                "depth": depth,
            },
        )
        # Bounded-edge cleanup: if this resume drained the last frame
        # (no more pending subagents/forks), clear the consumed-ids
        # ledger so it doesn't grow unboundedly across the chat lifetime.
        cs = getattr(context, "client_state", None)
        if cs is not None:
            ledger_pending = getattr(cs, "pending_subagents", None) or []
            ledger_consumed = getattr(cs, "consumed_subagent_tool_use_ids", None)
            if (
                not ledger_pending
                and isinstance(ledger_consumed, list)
                and ledger_consumed
            ):
                ledger_consumed.clear()
        return ToolResult(data=sync_output)

    async def _drain_run_agent(
        self,
        *,
        agent_definition: dict[str, Any],
        prompt_messages: list[Any],
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        available_tools: Any,
        description: str,
        agent_id: Any,
        on_progress: Any | None = None,
        parent_tool_use_id: str = "",
    ) -> tuple[list[Any], dict[str, dict[str, Any]], Any]:
        """Drain helper — mirrors ``AgentTool._drain_run_agent``.

        Captures user/assistant messages into ``agent_messages`` (and
        forwards them via ``on_progress`` for the UI activity list).
        Captures frontend tool dispatches in two shapes (mid-stream
        ``tool_dispatch`` events + post-stream ``tool_request`` payloads)
        keyed by id for dedupe. Returns ``(messages, pending_by_id,
        final_terminal)``.
        """
        from ...query.transitions import Terminal as _Terminal  # noqa: PLC0415
        from ..AgentTool.AgentTool import _emit_agent_progress_for_message  # noqa: PLC0415
        from ..AgentTool.runAgent import run_agent  # noqa: PLC0415

        agent_messages: list[Any] = []
        pending_by_id: dict[str, dict[str, Any]] = {}
        final_terminal: _Terminal | None = None

        async for event in run_agent(
            agent_definition=agent_definition,
            prompt_messages=prompt_messages,
            tool_use_context=context,
            can_use_tool=can_use_tool,
            available_tools=available_tools,
            description=description,
            agent_id=agent_id,
            model=None,
        ):
            if isinstance(event, _Terminal):
                final_terminal = event
                continue
            if isinstance(event, dict):
                etype = event.get("type")
                if etype in ("user", "assistant"):
                    agent_messages.append(event)
                    _emit_agent_progress_for_message(
                        event,
                        on_progress=on_progress,
                        tool_use_id=parent_tool_use_id,
                        agent_id=str(agent_id),
                    )
                elif etype == "tool_dispatch":
                    call_id = event.get("call_id") or ""
                    if call_id and call_id not in pending_by_id:
                        pending_by_id[call_id] = {
                            "type": "tool_use",
                            "id": call_id,
                            "name": event.get("name", ""),
                            "input": event.get("input") or {},
                        }
                elif etype == "tool_request":
                    for tu in (event.get("parallel_calls") or []):
                        if isinstance(tu, dict):
                            tu_id = tu.get("tool_use_id") or tu.get("id") or ""
                            if tu_id and tu_id not in pending_by_id:
                                pending_by_id[tu_id] = {
                                    "type": "tool_use",
                                    "id": tu_id,
                                    "name": tu.get("tool_name") or tu.get("name", ""),
                                    "input": tu.get("tool_input") or tu.get("input") or {},
                                }
                    for tu in (event.get("sequential_calls") or []):
                        if isinstance(tu, dict):
                            tu_id = tu.get("tool_use_id") or tu.get("id") or ""
                            if tu_id and tu_id not in pending_by_id:
                                pending_by_id[tu_id] = {
                                    "type": "tool_use",
                                    "id": tu_id,
                                    "name": tu.get("tool_name") or tu.get("name", ""),
                                    "input": tu.get("tool_input") or tu.get("input") or {},
                                }

        return agent_messages, pending_by_id, final_terminal

    async def _call_inline(
        self,
        *,
        skill: dict[str, Any],
        parsed: SkillToolInput,
        context: ToolUseContext,
    ) -> ToolResult[SkillToolOutput]:
        """Inline mode: expand the skill body and return as a tool_result.

        Caller's loop reads the result and follows the instructions on
        its next iteration. The skill's ``allowed_tools`` is advisory
        only here — the caller has its full tool pool.
        """
        get_prompt = skill.get("get_prompt_for_command")
        if not callable(get_prompt):
            raise RuntimeError(
                f"Skill /{parsed.name} is malformed (missing get_prompt_for_command)."
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
            raise RuntimeError(f"Skill /{parsed.name} expanded to empty body.")

        canonical_name = skill.get("name") or parsed.name
        return ToolResult(
            data=SkillToolOutput(
                skill_name=canonical_name,
                args=parsed.args,
                instructions=body,
            ),
        )

    def map_tool_result_to_block(self, content: Any, tool_use_id: str) -> dict:
        # Two shapes land here depending on which path ran:
        #   - INLINE: ``SkillToolOutput`` dataclass — wrap explicitly with
        #     skill name + args + instructions so the model disambiguates
        #     skill output from its own prior context (also makes prompt-
        #     injection via skill bodies more visible in transcripts).
        #   - FORK: ``dict`` from ``finalize_agent_tool`` — only the
        #     subagent's final assistant text matters; metadata
        #     (agentId, totalTokens, etc.) would be repr noise the LLM
        #     can't decode. Ship the canonical content list directly.
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
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": text,
            }
        if isinstance(content, dict):
            inner = content.get("content")
            if isinstance(inner, list):
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": inner,
                }
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": str(content) if content is not None else "",
        }


SkillTool = SkillToolImpl()
