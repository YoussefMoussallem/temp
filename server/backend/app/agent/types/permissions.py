"""
Permission type definitions.

Port of src/types/permissions.ts. Pure type definitions with no runtime
dependencies — implementation lives in hooks/toolPermission/.

NOTE: per Q9 v1 scope, the permission hierarchy is 4 levels:
session, project, managed, default. Per-user rules removed for v1
(see project_agent_port_hooks). User-related rule sources are kept
in this file for parity with source — they're just not surfaced in
the UI yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

# ============================================================================
# Permission Modes
# ============================================================================

ExternalPermissionMode = Literal[
    "acceptEdits",
    "bypassPermissions",
    "default",
    "dontAsk",
    "plan",
]

EXTERNAL_PERMISSION_MODES: tuple[ExternalPermissionMode, ...] = (
    "acceptEdits",
    "bypassPermissions",
    "default",
    "dontAsk",
    "plan",
)

# Exhaustive mode union for typechecking.
InternalPermissionMode = Literal[
    "acceptEdits",
    "bypassPermissions",
    "default",
    "dontAsk",
    "plan",
    "auto",
    "bubble",
]
PermissionMode = InternalPermissionMode

# Runtime validation set (matches source's INTERNAL_PERMISSION_MODES).
# 'auto' is gated behind TRANSCRIPT_CLASSIFIER feature in source; included
# here unconditionally — guard at use site if needed.
INTERNAL_PERMISSION_MODES: tuple[PermissionMode, ...] = (
    "acceptEdits",
    "bypassPermissions",
    "default",
    "dontAsk",
    "plan",
    "auto",
)
PERMISSION_MODES = INTERNAL_PERMISSION_MODES


# ============================================================================
# Permission Behaviors
# ============================================================================

PermissionBehavior = Literal["allow", "deny", "ask"]


# ============================================================================
# Permission Rules
# ============================================================================

PermissionRuleSource = Literal[
    "userSettings",
    "projectSettings",
    "localSettings",
    "flagSettings",
    "policySettings",
    "cliArg",
    "command",
    "session",
]


@dataclass(frozen=True)
class PermissionRuleValue:
    """The value of a permission rule — specifies which tool and optional content."""

    toolName: str
    ruleContent: str | None = None


@dataclass(frozen=True)
class PermissionRule:
    """A permission rule with its source and behavior."""

    source: PermissionRuleSource
    ruleBehavior: PermissionBehavior
    ruleValue: PermissionRuleValue


# ============================================================================
# Permission Updates
# ============================================================================

PermissionUpdateDestination = Literal[
    "userSettings",
    "projectSettings",
    "localSettings",
    "session",
    "cliArg",
]


@dataclass(frozen=True)
class PermissionUpdateAddRules:
    type: Literal["addRules"]
    destination: PermissionUpdateDestination
    rules: list[PermissionRuleValue]
    behavior: PermissionBehavior


@dataclass(frozen=True)
class PermissionUpdateReplaceRules:
    type: Literal["replaceRules"]
    destination: PermissionUpdateDestination
    rules: list[PermissionRuleValue]
    behavior: PermissionBehavior


@dataclass(frozen=True)
class PermissionUpdateRemoveRules:
    type: Literal["removeRules"]
    destination: PermissionUpdateDestination
    rules: list[PermissionRuleValue]
    behavior: PermissionBehavior


@dataclass(frozen=True)
class PermissionUpdateSetMode:
    type: Literal["setMode"]
    destination: PermissionUpdateDestination
    mode: ExternalPermissionMode


@dataclass(frozen=True)
class PermissionUpdateAddDirectories:
    type: Literal["addDirectories"]
    destination: PermissionUpdateDestination
    directories: list[str]


@dataclass(frozen=True)
class PermissionUpdateRemoveDirectories:
    type: Literal["removeDirectories"]
    destination: PermissionUpdateDestination
    directories: list[str]


PermissionUpdate = (
    PermissionUpdateAddRules
    | PermissionUpdateReplaceRules
    | PermissionUpdateRemoveRules
    | PermissionUpdateSetMode
    | PermissionUpdateAddDirectories
    | PermissionUpdateRemoveDirectories
)


# ============================================================================
# Working Directory
# ============================================================================

WorkingDirectorySource = PermissionRuleSource


@dataclass(frozen=True)
class AdditionalWorkingDirectory:
    path: str
    source: WorkingDirectorySource


# ============================================================================
# Permission Decisions & Results
# ============================================================================


class PermissionCommandMetadata(TypedDict, total=False):
    """Minimal command shape for permission metadata."""

    name: str
    description: str


PermissionMetadata = dict[str, PermissionCommandMetadata] | None


# Decision reasons (discriminated union).
@dataclass(frozen=True)
class _PermissionDecisionReasonRule:
    type: Literal["rule"]
    rule: PermissionRule


@dataclass(frozen=True)
class _PermissionDecisionReasonMode:
    type: Literal["mode"]
    mode: PermissionMode


@dataclass(frozen=True)
class _PermissionDecisionReasonSubcommandResults:
    type: Literal["subcommandResults"]
    reasons: dict[str, "PermissionResult"]


@dataclass(frozen=True)
class _PermissionDecisionReasonPermissionPromptTool:
    type: Literal["permissionPromptTool"]
    permissionPromptToolName: str
    toolResult: Any


@dataclass(frozen=True)
class _PermissionDecisionReasonHook:
    type: Literal["hook"]
    hookName: str
    hookSource: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class _PermissionDecisionReasonAsyncAgent:
    type: Literal["asyncAgent"]
    reason: str


@dataclass(frozen=True)
class _PermissionDecisionReasonSandboxOverride:
    type: Literal["sandboxOverride"]
    reason: Literal["excludedCommand", "dangerouslyDisableSandbox"]


@dataclass(frozen=True)
class _PermissionDecisionReasonClassifier:
    type: Literal["classifier"]
    classifier: str
    reason: str


@dataclass(frozen=True)
class _PermissionDecisionReasonWorkingDir:
    type: Literal["workingDir"]
    reason: str


@dataclass(frozen=True)
class _PermissionDecisionReasonSafetyCheck:
    type: Literal["safetyCheck"]
    reason: str
    classifierApprovable: bool


@dataclass(frozen=True)
class _PermissionDecisionReasonOther:
    type: Literal["other"]
    reason: str


PermissionDecisionReason = (
    _PermissionDecisionReasonRule
    | _PermissionDecisionReasonMode
    | _PermissionDecisionReasonSubcommandResults
    | _PermissionDecisionReasonPermissionPromptTool
    | _PermissionDecisionReasonHook
    | _PermissionDecisionReasonAsyncAgent
    | _PermissionDecisionReasonSandboxOverride
    | _PermissionDecisionReasonClassifier
    | _PermissionDecisionReasonWorkingDir
    | _PermissionDecisionReasonSafetyCheck
    | _PermissionDecisionReasonOther
)


@dataclass(frozen=True)
class PendingClassifierCheck:
    """Metadata for a pending classifier check that runs asynchronously."""

    command: str
    cwd: str
    descriptions: list[str]


@dataclass
class PermissionAllowDecision:
    """Result when permission is granted."""

    behavior: Literal["allow"] = "allow"
    updatedInput: dict[str, Any] | None = None
    userModified: bool | None = None
    decisionReason: PermissionDecisionReason | None = None
    toolUseID: str | None = None
    acceptFeedback: str | None = None
    contentBlocks: list[Any] | None = None


@dataclass
class PermissionAskDecision:
    """Result when user should be prompted."""

    behavior: Literal["ask"]
    message: str
    updatedInput: dict[str, Any] | None = None
    decisionReason: PermissionDecisionReason | None = None
    suggestions: list[PermissionUpdate] | None = None
    blockedPath: str | None = None
    metadata: PermissionMetadata = None
    isBashSecurityCheckForMisparsing: bool | None = None
    pendingClassifierCheck: PendingClassifierCheck | None = None
    contentBlocks: list[Any] | None = None


@dataclass
class PermissionDenyDecision:
    """Result when permission is denied."""

    behavior: Literal["deny"]
    message: str
    decisionReason: PermissionDecisionReason
    toolUseID: str | None = None


PermissionDecision = PermissionAllowDecision | PermissionAskDecision | PermissionDenyDecision


@dataclass
class PermissionPassthroughDecision:
    """Permission result with passthrough option."""

    behavior: Literal["passthrough"]
    message: str
    decisionReason: PermissionDecisionReason | None = None
    suggestions: list[PermissionUpdate] | None = None
    blockedPath: str | None = None
    pendingClassifierCheck: PendingClassifierCheck | None = None


PermissionResult = PermissionDecision | PermissionPassthroughDecision


# ============================================================================
# Bash Classifier Types (safety classifier)
# ============================================================================
# These support the auto-mode YOLO safety classifier. v1 hook scope (Q9) keeps
# permission gates without classifier; these stay for parity but are not
# wired into the v1 enforcement path.


@dataclass
class ClassifierResult:
    matches: bool
    confidence: Literal["high", "medium", "low"]
    reason: str
    matchedDescription: str | None = None


ClassifierBehavior = Literal["deny", "ask", "allow"]


@dataclass
class ClassifierUsage:
    inputTokens: int
    outputTokens: int
    cacheReadInputTokens: int
    cacheCreationInputTokens: int


@dataclass
class YoloClassifierResult:
    shouldBlock: bool
    reason: str
    model: str
    thinking: str | None = None
    unavailable: bool | None = None
    transcriptTooLong: bool | None = None
    usage: ClassifierUsage | None = None
    durationMs: int | None = None
    promptLengths: dict[str, int] | None = None
    errorDumpPath: str | None = None
    stage: Literal["fast", "thinking"] | None = None
    stage1Usage: ClassifierUsage | None = None
    stage1DurationMs: int | None = None
    stage1RequestId: str | None = None
    stage1MsgId: str | None = None
    stage2Usage: ClassifierUsage | None = None
    stage2DurationMs: int | None = None
    stage2RequestId: str | None = None
    stage2MsgId: str | None = None


# ============================================================================
# Permission Explainer Types
# ============================================================================

RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


@dataclass
class PermissionExplanation:
    riskLevel: RiskLevel
    explanation: str
    reasoning: str
    risk: str


# ============================================================================
# Tool Permission Context
# ============================================================================

# Mapping of permission rules by their source.
ToolPermissionRulesBySource = dict[PermissionRuleSource, list[str]]


@dataclass(frozen=True)
class ToolPermissionContext:
    """
    Context needed for permission checking in tools.

    `frozen=True` mirrors the source's DeepImmutable. Mutations create new
    instances via dataclasses.replace().
    """

    mode: PermissionMode = "default"
    additionalWorkingDirectories: dict[str, AdditionalWorkingDirectory] = field(
        default_factory=dict
    )
    alwaysAllowRules: ToolPermissionRulesBySource = field(default_factory=dict)
    alwaysDenyRules: ToolPermissionRulesBySource = field(default_factory=dict)
    alwaysAskRules: ToolPermissionRulesBySource = field(default_factory=dict)
    isBypassPermissionsModeAvailable: bool = False
    strippedDangerousRules: ToolPermissionRulesBySource | None = None
    shouldAvoidPermissionPrompts: bool | None = None
    awaitAutomatedChecksBeforeDialog: bool | None = None
    # Stores the permission mode before model-initiated plan mode entry, so
    # it can be restored on exit.
    prePlanMode: PermissionMode | None = None


def get_empty_tool_permission_context() -> ToolPermissionContext:
    """Construct an empty ToolPermissionContext with default values."""
    return ToolPermissionContext()
