"""DeleteMemory — remove a long-term memory by scope + slug."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

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
from .prompt import DELETE_MEMORY_TOOL_NAME, DESCRIPTION


class DeleteMemoryInput(BaseModel):
    scope: Literal["user", "project"] = Field(
        description="Which memory store to delete from.",
    )
    slug: str = Field(
        max_length=64,
        description="Slug of the entry to delete.",
    )


class DeleteMemoryToolImpl(BaseTool[DeleteMemoryInput, str]):
    name = DELETE_MEMORY_TOOL_NAME
    inputSchema = DeleteMemoryInput
    maxResultSizeChars = 500
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return False

    def is_concurrency_safe(self, input: Any = None) -> bool:
        # Single-row delete — concurrent calls on different slugs are
        # safe, but concurrent calls on the same slug are a no-op race
        # we'd rather have surface deterministically. Mark unsafe so
        # the loop runs deletes serially.
        return False

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(
        self, input: Any, context: ToolUseContext,
    ) -> ValidationResult:
        scope = input.get("scope") if isinstance(input, dict) else getattr(input, "scope", None)
        if scope == "user" and not context.user_id:
            return ValidationError(
                message="No authenticated user on context.",
                errorCode=1,
            )
        if scope == "project" and not context.project_id:
            return ValidationError(
                message=(
                    "No active project on context — cannot delete project "
                    "memory."
                ),
                errorCode=2,
            )
        if not context.authorization:
            return ValidationError(
                message="Missing authorization on tool context.",
                errorCode=3,
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
        parsed: DeleteMemoryInput = (
            args if isinstance(args, DeleteMemoryInput) else DeleteMemoryInput(**args)
        )

        if parsed.scope == "user":
            await db_client.delete_user_memory(
                context.authorization or "",
                context.user_id or "",
                parsed.slug,
            )
        else:
            await db_client.delete_project_memory(
                context.authorization or "",
                context.project_id or "",
                parsed.slug,
            )

        # 204 from db-service is idempotent — the delete returns the
        # same shape whether the row existed or not. That's deliberate;
        # the model gets a clean "it's gone now" signal in either case.
        return ToolResult(
            data=f"Deleted [{parsed.scope}:{parsed.slug}]."
        )


DeleteMemoryTool = DeleteMemoryToolImpl()
