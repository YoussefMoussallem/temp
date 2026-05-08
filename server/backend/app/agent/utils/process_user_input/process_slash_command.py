"""
Slash-command resolver.

Port of src/utils/processUserInput/processSlashCommand.tsx's inline branch.
The forked-execution path (context:"fork") and assistant-mode are deferred
(see Phase 2.7b).

Public entry points:
  - process_slash_command(input, ctx, attachments=None) -> ProcessedInput
  - get_messages_for_slash_command(name, args, ctx) -> dispatcher (internal,
    but exposed for tests).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app_logger import get_logger

from ...constants.xml import (
    COMMAND_ARGS_TAG,
    COMMAND_MESSAGE_TAG,
    COMMAND_NAME_TAG,
)
from ..create_command_input_message import (
    create_command_input_message,
    user_message,
    wrap_xml,
)
from ..slash_command_parsing import parse_slash_command
from ...commands import find_command, get_command, has_command, load_all_commands

if TYPE_CHECKING:
    from ...Tool import ToolUseContext

log = get_logger(__name__)


# ----------------------------------------------------------------------------
# Result shape
# ----------------------------------------------------------------------------


@dataclass
class ProcessedInput:
    """Return value of process_slash_command.

    Matches the source's inline-branch return shape:
      - messages: list of loop-shape dicts to insert into the conversation.
        Shape: [{"type":"user","message":{"role":"user","content":[...]}}]
      - should_query: if False, the caller skips the model call this turn.
      - allowed_tools, model, effort: forwarded to the caller's
        QueryEngine.options for this turn only (prompt-type only).
      - next_input / submit_next_input: used by the local-command follow-up
        convention (a command can chain into another prompt).
    """
    messages: list[dict] = field(default_factory=list)
    should_query: bool = True
    allowed_tools: list[str] | None = None
    model: str | None = None
    effort: str | None = None
    next_input: str | None = None
    submit_next_input: bool = False


# ----------------------------------------------------------------------------
# Dispatcher
# ----------------------------------------------------------------------------


async def get_messages_for_slash_command(
    name: str,
    args: str,
    original_input: str,
    ctx: "ToolUseContext",
    commands: list,
) -> ProcessedInput:
    """Dispatch one command. Assumes `has_command(name, commands)` is True.

    Mirrors src/utils/processUserInput/processSlashCommand.tsx:
    getMessagesForSlashCommand.
    """
    command = get_command(name, commands)

    try:
        ctype = command.get("type")

        if ctype == "local":
            load = command.get("load")
            if not callable(load):
                return ProcessedInput(
                    messages=[user_message(f"Command /{name} has no load().")],
                    should_query=False,
                )
            mod = await load()
            call_fn = getattr(mod, "call", None)
            if not callable(call_fn):
                return ProcessedInput(
                    messages=[user_message(f"Command /{name} module has no call().")],
                    should_query=False,
                )
            result = await call_fn(args, ctx)
            result_type = (result or {}).get("type")

            if result_type == "skip":
                # Short-circuit — no messages, no query.
                return ProcessedInput(messages=[], should_query=False)

            if result_type == "value":
                value = result.get("value", "") or ""
                # Source emits: the user-typed command *then* the local-command
                # stdout as a second synthetic user message. The first one is
                # what the model would have seen if we routed through it; the
                # second carries the command's output.
                return ProcessedInput(
                    messages=[
                        user_message(original_input),
                        create_command_input_message(value),
                    ],
                    should_query=False,
                )

            # Unknown shape — treat as skip to be safe.
            return ProcessedInput(messages=[], should_query=False)

        if ctype == "prompt":
            get_prompt = command.get("get_prompt_for_command")
            if not callable(get_prompt):
                return ProcessedInput(
                    messages=[user_message(f"Command /{name} has no get_prompt_for_command().")],
                    should_query=False,
                )
            skill_blocks = await get_prompt(args, ctx)
            # skill_blocks is a list[dict] — most commonly a single text block.
            body = "".join(b.get("text", "") for b in skill_blocks if b.get("type") == "text")
            # Source wraps the expansion in three tagged user messages so the
            # model can tell a slash-command turn from a regular user message.
            content_blocks = [
                {"type": "text", "text": wrap_xml(COMMAND_NAME_TAG, f"/{name}")},
                {"type": "text", "text": wrap_xml(COMMAND_ARGS_TAG, args)},
                {"type": "text", "text": wrap_xml(COMMAND_MESSAGE_TAG, body)},
            ]
            return ProcessedInput(
                messages=[user_message(content_blocks)],
                should_query=True,
                allowed_tools=command.get("allowed_tools"),
                model=command.get("model"),
                effort=command.get("effort"),
            )

        log.warning("Command /%s has unknown type %r", name, ctype)
        return ProcessedInput(
            messages=[user_message(f"Command /{name} has unknown type.")],
            should_query=False,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("Slash command /%s failed: %s", name, e)
        return ProcessedInput(messages=[], should_query=False)


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------


async def process_slash_command(
    input_str: str,
    ctx: "ToolUseContext",
    attachments: list[dict] | None = None,
) -> ProcessedInput:
    """Main entry. Called from the turn path when the user types a '/' line.

    Behavior:
      - Parser says None  → caveat + attachments + guidance message (should_query=False).
        Source also emits the caveat, matching the TUI's behavior.
      - Command not found → fall back to a normal prompt (source does this
        silently — typos become regular model input).
      - Command found     → delegate to get_messages_for_slash_command.
    """
    attachments = list(attachments or [])

    parsed = parse_slash_command(input_str)
    if parsed is None:
        caveat = user_message(
            "Commands are in the form /command [args]."
        )
        return ProcessedInput(
            messages=[caveat, *attachments],
            should_query=False,
        )

    name, args = parsed

    # Lazy-fetch the registry — allows tests to pass a custom registry via
    # ctx.options.commands (parity with source). Uses load_all_commands so
    # filesystem-discovered skills (Phase 2.7b.1) are findable alongside
    # built-ins; tests that want only built-ins can inject the smaller list.
    #
    # ``cwd`` for project-level skill discovery: source assumes a real
    # working directory (CLI). On the web, Edwin doesn't have a per-user
    # cwd — bundled + ~/.edwin/skills are the only practical layers
    # today. Project-scoped skills land when there's a user-uploads-skills
    # flow (per-account, per-deck). Pass None until then.
    commands = getattr(ctx.options, "commands", None) if ctx is not None else None
    if not commands:
        commands = await load_all_commands(None)

    if not has_command(name, commands):
        # Unknown command → treat the whole input as a regular prompt. Source:
        # "fall back to a normal prompt so typos don't surface as errors."
        return ProcessedInput(
            messages=[user_message(input_str), *attachments],
            should_query=True,
        )

    return await get_messages_for_slash_command(name, args, input_str, ctx, commands)
