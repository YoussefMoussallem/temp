"""
Command type definitions.

Port of src/types/command.ts. Three variant TypedDicts unioned on `type`:
  - PromptCommand: expands to messages wrapped with XML tags, triggers a model call.
  - LocalCommand: runs fully client/server side, returns {skip} or {value: str}.

LOCAL-JSX VARIANT DROPPED — source has it for Ink-only UI. No browser equivalent.
If command-owned UI is ever needed, dispatch a reducer action via the
local-command path instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable, Literal, TypedDict

if TYPE_CHECKING:
    from ..Tool import ToolUseContext


CommandAvailability = Literal["interactive", "non-interactive", "forked"]


class CommandBase(TypedDict, total=False):
    """17 shared fields. All optional in TS source; required `name`+`description`
    are enforced at registration time, not by the type.

    ``execution`` is an Edwin-specific addition (not in source): the CLI runs
    as one process so source doesn't need to distinguish. On web, some
    commands (``/clear``, ``/plan``, ``/cost``) are inherently client-side —
    backend holds metadata so discovery is unified, frontend runs them.
    """

    availability: list[CommandAvailability]
    description: str
    has_user_specified_description: bool
    is_enabled: Callable[[], bool]
    is_hidden: bool
    name: str
    aliases: list[str]
    is_mcp: bool
    argument_hint: str
    when_to_use: str
    version: str
    disable_model_invocation: bool
    user_invocable: bool
    loaded_from: Literal["skills", "plugin", "managed", "bundled", "mcp", "commands_DEPRECATED"]
    kind: Literal["workflow"]
    immediate: bool
    is_sensitive: bool
    user_facing_name: Callable[[], str]
    # Where the command executes. "server" = backend runs it (prompt-type or
    # backend-owned local); "client" = frontend runs it, backend holds
    # metadata for typeahead only. Prompt-type is always "server".
    execution: Literal["server", "client"]


class PromptCommand(CommandBase, total=False):
    """Variant: expands to model-bound messages."""

    type: Literal["prompt"]
    progress_message: str
    content_length: int
    arg_names: list[str]
    allowed_tools: list[str]
    model: str
    source: Literal["user", "project", "managed", "builtin", "mcp", "plugin", "bundled"]
    plugin_info: dict
    disable_non_interactive: bool
    hooks: dict
    skill_root: str
    context: Literal["inline", "fork"]
    agent: str
    # SkillTool fork lane: optional text appended to the base agent's
    # system prompt when the skill runs in fork mode. Lets a skill
    # author declare additional persona/framing on top of the base
    # agent's identity without replacing it.
    system_prompt_overlay: str
    effort: str
    paths: list[str]
    get_prompt_for_command: Callable[[str, "ToolUseContext"], Awaitable[list[dict]]]


class LocalCommandResultSkip(TypedDict):
    type: Literal["skip"]


class LocalCommandResultValue(TypedDict):
    type: Literal["value"]
    value: str


LocalCommandResult = LocalCommandResultSkip | LocalCommandResultValue


class LocalCommandModule(TypedDict):
    """Shape returned by LocalCommand.load()."""

    call: Callable[[str, "ToolUseContext"], Awaitable[LocalCommandResult]]


class LocalCommand(CommandBase, total=False):
    """Variant: runs synchronously; output wrapped in <local-command-stdout>."""

    type: Literal["local"]
    supports_non_interactive: bool
    load: Callable[[], Awaitable[LocalCommandModule]]


Command = PromptCommand | LocalCommand
