"""ListProjectMemories — return the index of the active project's memories."""

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
from .prompt import DESCRIPTION, LIST_PROJECT_MEMORIES_TOOL_NAME


class ListProjectMemoriesInput(BaseModel):
    """No arguments — project_id comes from request context."""

    pass


class ListProjectMemoriesToolImpl(BaseTool[ListProjectMemoriesInput, str]):
    name = LIST_PROJECT_MEMORIES_TOOL_NAME
    inputSchema = ListProjectMemoriesInput
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
        if not context.project_id:
            return ValidationError(
                message=(
                    "No active project on context. This tool is only "
                    "usable inside a project conversation."
                ),
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
        rows = await db_client.list_project_memories(
            context.authorization or "",
            context.project_id or "",
        )

        if not rows:
            return ToolResult(
                data=(
                    "No project memories saved yet. Nothing recorded "
                    "about this project's audience, decisions, or "
                    "references."
                ),
            )

        lines = [
            "# Project Memory (index)",
            "",
            (
                "Long-term facts saved about this project. Use "
                'ReadMemory(scope="project", slug=...) to fetch a '
                "specific entry's body."
            ),
            "",
        ]
        for r in rows:
            lines.append(f"- [{r['slug']}] ({r['type']}) {r['name']} — {r['description']}")
        return ToolResult(data="\n".join(lines))


ListProjectMemoriesTool = ListProjectMemoriesToolImpl()
