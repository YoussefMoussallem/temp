"""ReadMemory — fetch the body of one long-term memory by scope + slug."""

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
from .prompt import DESCRIPTION, READ_MEMORY_TOOL_NAME


class ReadMemoryInput(BaseModel):
    scope: Literal["user", "project"] = Field(
        description="Which memory store to read from.",
    )
    slug: str = Field(
        max_length=64,
        description="Slug as shown in the matching List tool's output.",
    )


class ReadMemoryToolImpl(BaseTool[ReadMemoryInput, str]):
    name = READ_MEMORY_TOOL_NAME
    inputSchema = ReadMemoryInput
    # Memory bodies can be long-form; allow generous headroom but cap so
    # an oversized entry doesn't blow a turn's context budget. The cap
    # is well above realistic body sizes (a few KB) but stops a corrupt
    # row from melting the prompt.
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
        scope = input.get("scope") if isinstance(input, dict) else getattr(input, "scope", None)
        if scope == "user" and not context.user_id:
            return ValidationError(
                message="No authenticated user on context.",
                errorCode=1,
            )
        if scope == "project" and not context.project_id:
            return ValidationError(
                message=('No active project on context. Switch to a project or use scope="user".'),
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
        parsed: ReadMemoryInput = (
            args if isinstance(args, ReadMemoryInput) else ReadMemoryInput(**args)
        )

        if parsed.scope == "user":
            row = await db_client.get_user_memory(
                context.authorization or "",
                context.user_id or "",
                parsed.slug,
            )
        else:
            row = await db_client.get_project_memory(
                context.authorization or "",
                context.project_id or "",
                parsed.slug,
            )

        if row is None:
            # Treat 404 as a soft error — the loop wraps it as an
            # is_error tool_result so the model can recover by listing
            # the index and picking a real slug.
            raise ValueError(
                f"No memory at [{parsed.scope}:{parsed.slug}]. "
                f"Use List{parsed.scope.capitalize()}Memories to see what exists."
            )

        # Frame the body with its metadata so the model sees the full
        # entry as a coherent block — same convention SkillTool uses
        # for its frontmatter wrap.
        text = (
            f"Memory: [{parsed.scope}:{row['slug']}]\n"
            f"Type: {row['type']}\n"
            f"Name: {row['name']}\n"
            f"Description: {row['description']}\n"
            f"\n"
            f"---\n"
            f"{row['body']}\n"
            f"---"
        )
        return ToolResult(data=text)


ReadMemoryTool = ReadMemoryToolImpl()
