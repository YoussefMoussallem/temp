"""AgentTool result + output schemas + cross-/turn pause frame.

Port of `Utilities/claude files/software agent/src/tools/AgentTool/agentToolUtils.ts`
(result schemas) and `tools/AgentTool/AgentTool.tsx` (sync/async outputs).

Phase 6 Lane B Foundation — pure wire-format shapes with no runtime
dependencies. Safe to land before the handler/runAgent.

Source-parity citations:

- TS: `Utilities/claude files/software agent/src/tools/AgentTool/agentToolUtils.ts`
  - agentToolResultSchema (Zod)  — TS lines 227-258
  - AgentToolResult type alias   — TS line 260
- TS: `Utilities/claude files/software agent/src/tools/AgentTool/AgentTool.tsx`
  - outputSchema (sync + async union) — TS lines 140-155

Python-port notes:

- TS uses Zod schemas (runtime validation). We use TypedDict — the result
  shapes are CONSTRUCTED by handler code (not parsed from untrusted
  input), so type-checker-only is sufficient. The schema discipline lives
  in the handler that builds the dict.
- ``total=False`` mirrors TS optional fields (``?`` markers). Required-vs-
  optional split via private ``_*Required`` base classes per the
  convention used elsewhere in the agent package.
- TeammateSpawnedOutput (TS `AgentTool.tsx:159-176`) is gated behind
  ``ENABLE_AGENT_SWARMS`` and lands in 6.B.5 — not part of Foundation.
"""

from __future__ import annotations

from typing import List, Literal, TypedDict, Union


# ============================================================================
# Result content + token usage
# ============================================================================


class AgentToolContentText(TypedDict):
    """Source `agentToolUtils.ts:234`. Text block in the result content array."""

    type: Literal["text"]
    text: str


class AgentToolUsageServerToolUse(TypedDict):
    """Source `agentToolUtils.ts:243-247`. Server-side tool use counters."""

    web_search_requests: int
    web_fetch_requests: int


class AgentToolUsageCacheCreation(TypedDict):
    """Source `agentToolUtils.ts:250-254`. Cache write breakdown by TTL."""

    ephemeral_1h_input_tokens: int
    ephemeral_5m_input_tokens: int


class AgentToolUsage(TypedDict):
    """Source `agentToolUtils.ts:238-256`. Token + service-tier accounting
    aggregated across the subagent's run.

    Nullable fields mirror TS ``.nullable()`` — Python represents these as
    ``<type> | None`` and the consumer must accept None.
    """

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int | None
    cache_read_input_tokens: int | None
    server_tool_use: AgentToolUsageServerToolUse | None
    service_tier: Literal["standard", "priority", "batch"] | None
    cache_creation: AgentToolUsageCacheCreation | None


# ============================================================================
# AgentToolResult — the core schema returned from finalize_agent_tool()
# ============================================================================


class _AgentToolResultRequired(TypedDict):
    """Required fields on AgentToolResult."""

    agentId: str
    content: List[AgentToolContentText]
    totalToolUseCount: int
    totalDurationMs: int
    totalTokens: int
    usage: AgentToolUsage


class AgentToolResult(_AgentToolResultRequired, total=False):
    """Source `agentToolUtils.ts:227-258`. Aggregated subagent run summary.

    ``agentType`` is OPTIONAL because older persisted sessions won't carry it
    (resume replays results verbatim without re-validation). At runtime
    every fresh subagent run sets it; absence indicates legacy data.
    """

    agentType: str


# ============================================================================
# AgentTool.call() output discriminated union (sync vs async)
# ============================================================================


class _AgentToolSyncOutputRequired(TypedDict):
    """Required fields on AgentToolSyncOutput."""

    status: Literal["completed"]
    prompt: str


class AgentToolSyncOutput(
    _AgentToolResultRequired,
    _AgentToolSyncOutputRequired,
    total=False,
):
    """Source `AgentTool.tsx:142-145`. Synchronous completion result.

    Inherits every AgentToolResult required field plus required
    ``status: 'completed'`` and ``prompt`` (the prompt the subagent ran
    with — useful for transcript replay). The optional ``agentType``
    field flows through here too via the ``total=False`` flag.
    """

    agentType: str


class _AgentToolAsyncOutputRequired(TypedDict):
    """Required fields on AgentToolAsyncOutput."""

    status: Literal["async_launched"]
    agentId: str
    description: str
    prompt: str
    outputFile: str


class AgentToolAsyncOutput(_AgentToolAsyncOutputRequired, total=False):
    """Source `AgentTool.tsx:146-153`. Background launch acknowledgement —
    deferred to v2 (run_in_background path). Schema kept for forward-
    compat so the discriminated-union type signature stays parity-shaped;
    nothing emits this shape today.
    """

    canReadOutputFile: bool


# Source `AgentTool.tsx:154`. Discriminated union — consumers narrow via
# ``output["status"]``.
AgentToolOutput = Union[AgentToolSyncOutput, AgentToolAsyncOutput]


# ============================================================================
# Subagent pause/resume frame (Phase 6.B.1.7)
# ============================================================================
#
# Edwin-specific machinery — TS source has no equivalent because TS runs
# everything in one process. Our backend/frontend split forces subagent
# loops to span multiple /turn calls when the subagent uses frontend-side
# tools. When the subagent's inner query() yields
# Terminal(awaiting_frontend_tools), AgentTool.call() captures the frame
# below into ClientState.pending_subagents so the next /turn can resume.
#
# Round-trips through chat-ui as part of the opaque ClientState blob —
# chat-ui treats it as bytes (per feedback_dumb_client).


class _PendingSubagentFrameRequired(TypedDict):
    """Required fields on PendingSubagentFrame."""

    # The subagent's stable identity. Re-used across resumes so finalize
    # reports a consistent agentId.
    agentId: str
    # Built-in agent type ('Explore' / 'Plan' / 'general-purpose' /
    # 'verification'). Resume re-resolves the AgentDefinition from the
    # registry by this field — definitions live in code, not state.
    agentType: str
    # The parent's Agent tool_use ID. AgentTool.call() at resume looks
    # itself up by ``tool_use_block.id == this``. Critical: identifies which
    # frame to load when there are nested or queued subagent invocations.
    parentToolUseId: str
    # Subagent's accumulated message stream (user kickoff → assistant
    # tool_use → ... → in-flight assistant message with frontend tool_uses).
    # On resume we append the freshly-delivered tool_results and re-drive
    # query().
    accumulatedMessages: List[dict]
    # IDs of the frontend tool_uses the subagent emitted in its in-flight
    # assistant message. The next /turn arrives with tool_results for these
    # IDs in the user message; resume sifts by ID and injects.
    pendingToolUseIds: List[str]
    # Original kickoff prompt — needed by finalize_agent_tool's metadata.
    kickoffPrompt: str
    # Subagent's start time in epoch ms — needed for totalDurationMs.
    startTimeMs: int
    # Original AgentTool input description — finalize uses it.
    description: str


class PendingSubagentFrame(_PendingSubagentFrameRequired, total=False):
    """Serializable subagent state across a /turn boundary.

    Edwin-specific. Stashed onto ClientState.pending_subagents when an
    AgentTool dispatch pauses on frontend tool_request.

    Multi-frame support: the bucket holds N concurrently-paused sync
    frames keyed by ``parentToolUseId`` for resume. The router pre-loop's
    ``_route_subagent_tool_results`` walks all frames and routes any
    matching tool_result block.
    """

    # Reserved for fork lane: parent's full message context for cache-
    # identical prefix. Sync path leaves None.
    forkContextMessages: List[dict]

    # SkillTool-fork lane: identifies which tool authored the frame so
    # resume detection routes correctly. Defaults to "Agent" by convention
    # (AgentTool frames omit the field — back-compat). SkillTool fork
    # dispatch sets "Skill" so its own resume hook picks up its own frames.
    originatingTool: str

    # SkillTool-fork lane: resume re-resolves the original PromptCommand
    # from the registry by name (the same way AgentTool resume re-looks-up
    # ``agentType``). The args carry the ``$ARGUMENTS`` substitution
    # payload. None on AgentTool frames.
    skillCommandName: str
    skillArgs: str

    # SkillTool-fork lane: caller's intent string passed via the new
    # SkillToolInput.intent field. Reconstructed into the system prompt
    # on every iteration of the fork's query() loop so the model never
    # forgets the framing across resume boundaries.
    skillIntent: str

    # SkillTool-fork lane: recursion depth so the fork can refuse to
    # spawn another fork past MAX_SKILL_FORK_DEPTH. Counts only skill-
    # fork hops; AgentTool dispatches don't bump this.
    skillForkDepth: int
