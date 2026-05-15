"""
Message types.

Port of src/types/message.ts. The TS source is partly auto-generated stubs
(`Message` is loosely typed), so this Python port preserves the same loose
shape: a Message is essentially a dict with a discriminated `type` field
plus optional UUID, content, role, etc.

Keeping it loose at this layer is intentional — narrowing happens at use
sites in tools/services where the concrete shape matters.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict
from uuid import UUID

# Discriminant for message subtypes.
MessageType = Literal[
    "user",
    "assistant",
    "system",
    "attachment",
    "progress",
    "grouped_tool_use",
    "collapsed_read_search",
]

# A single content element inside message.content arrays.
# Loose type — concrete shape comes from the Anthropic SDK content blocks.
ContentItem = Any

# A message's content can be a plain string, or a list of content blocks.
MessageContent = str | list[ContentItem]

# Typed content array — used in narrowed message subtypes.
TypedMessageContent = list[ContentItem]


class _InnerMessage(TypedDict, total=False):
    """The nested `message` field on most Message variants."""

    role: str
    id: str
    content: MessageContent
    usage: dict[str, Any]


class Message(TypedDict, total=False):
    """
    Base message type. All fields except `type` and `uuid` are optional —
    the source TS uses `[key: string]: unknown` to allow arbitrary extra keys.
    """

    type: MessageType
    uuid: UUID
    isMeta: bool
    isCompactSummary: bool
    toolUseResult: Any
    isVisibleInTranscriptOnly: bool
    attachment: dict[str, Any]
    message: _InnerMessage


# Narrowed message subtypes.
# In TS these are `Message & { type: 'X' }` intersection types; in Python we
# just use Message directly and rely on the `type` field for runtime narrowing.
AssistantMessage = Message
AttachmentMessage = Message
ProgressMessage = Message
SystemLocalCommandMessage = Message
SystemMessage = Message
UserMessage = Message
NormalizedUserMessage = UserMessage
NormalizedAssistantMessage = AssistantMessage
NormalizedMessage = Message
TombstoneMessage = Message
ToolUseSummaryMessage = Message
HookResultMessage = Message
SystemThinkingMessage = Message
SystemAPIErrorMessage = Message
SystemFileSnapshotMessage = Message
SystemAgentsKilledMessage = Message
SystemApiMetricsMessage = Message
SystemAwaySummaryMessage = Message
SystemBridgeStatusMessage = Message
SystemInformationalMessage = Message
SystemMemorySavedMessage = Message
SystemMicrocompactBoundaryMessage = Message
SystemPermissionRetryMessage = Message
SystemScheduledTaskFireMessage = Message
SystemTurnDurationMessage = Message
SystemCompactBoundaryMessage = Message

MessageOrigin = str
SystemMessageLevel = str
PartialCompactDirection = str
CompactMetadata = dict[str, Any]


# Stream / request events — loose at this layer.
class StreamEvent(TypedDict, total=False):
    type: str


class RequestStartEvent(TypedDict, total=False):
    type: str


class StopHookInfo(TypedDict, total=False):
    command: str
    durationMs: int


class GroupedToolUseMessage(TypedDict, total=False):
    type: Literal["grouped_tool_use"]
    toolName: str
    messages: list[NormalizedAssistantMessage]
    results: list[NormalizedUserMessage]
    displayMessage: NormalizedAssistantMessage | NormalizedUserMessage


class CollapsedReadSearchGroup(TypedDict, total=False):
    type: Literal["collapsed_read_search"]
    uuid: UUID
    searchCount: int
    readCount: int
    listCount: int
    replCount: int
    memorySearchCount: int
    memoryReadCount: int
    memoryWriteCount: int
    readFilePaths: list[str]
    searchArgs: list[str]
    messages: list[Message]
    displayMessage: Message
    bashCount: int
    gitOpBashCount: int


# Renderable + collapsible unions — loose because consumers narrow on `type`.
RenderableMessage = Message
CollapsibleMessage = Message
