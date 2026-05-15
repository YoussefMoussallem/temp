"""ListUserMemories — return the index of the caller's user-scope memories."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.bridges import db_client

from ...Tool import (
    BaseTool,
    ToolResult,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, LIST_USER_MEMORIES_TOOL_NAME


class ListUserMemoriesInput(BaseModel):
    """No arguments — caller's identity comes from request context."""

    pass


class ListUserMemoriesToolImpl(BaseTool[ListUserMemoriesInput, str]):
    name = LIST_USER_MEMORIES_TOOL_NAME
    inputSchema = ListUserMemoriesInput
    maxResultSizeChars = 50_000
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return True

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(
        self,
        input: Any,
        context: ToolUseContext,
    ) -> ValidationResult:
        if not context.user_id:
            return ValidationError(
                message="No authenticated user on context.",
                errorCode=1,
            )
        if not context.authorization:
            return ValidationError(
                message="Missing authorization on tool context.",
                errorCode=2,
            )
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[str]:
        rows = await db_client.list_user_memories(
            context.authorization or "",
            context.user_id or "",
        )

        if not rows:
            return ToolResult(
                data=(
                    "No user memories saved yet. The user has no long-term "
                    "preferences or feedback recorded for cross-session use."
                ),
            )

        # Index-only rendering: slug, type, name, description per row.
        # Bodies are NOT included — those come via ReadMemory.
        lines = [
            "# User Memory (index)",
            "",
            (
                "Long-term facts saved about this user, available across "
                'all conversations. Use ReadMemory(scope="user", '
                "slug=...) to fetch a specific entry's body."
            ),
            "",
        ]
        for r in rows:
            lines.append(f"- [{r['slug']}] ({r['type']}) {r['name']} — {r['description']}")
        return ToolResult(data="\n".join(lines))


ListUserMemoriesTool = ListUserMemoriesToolImpl()
