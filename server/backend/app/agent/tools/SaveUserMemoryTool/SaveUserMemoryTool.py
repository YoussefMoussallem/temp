"""SaveUserMemory — upsert a long-term memory in the user scope."""

from __future__ import annotations

import re
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
from .prompt import DESCRIPTION, SAVE_USER_MEMORY_TOOL_NAME


# Match db-service's UpsertUserMemoryRequest slug regex. Client-side
# validation surfaces a clean error to the model instead of an HTTP 422.
_SLUG_RE = re.compile(r"^[a-z0-9_]+$")

# Types valid for user-scope memory. Enforced here so the model gets a
# scope-appropriate error message rather than a generic literal-check
# failure from pydantic.
_USER_TYPES = {"user", "feedback", "reference"}


class SaveUserMemoryInput(BaseModel):
    slug: str = Field(
        max_length=64,
        description="Stable handle (lowercase letters, digits, underscores).",
    )
    type: Literal["user", "feedback", "reference"] = Field(
        description="Category tag. user = identity/preferences; feedback = corrections; reference = external pointers.",
    )
    name: str = Field(
        max_length=120,
        description="Human-readable title.",
    )
    description: str = Field(
        max_length=150,
        description="One-line hook for the index. Concrete > vague.",
    )
    body: str = Field(
        description="Full memory content as markdown.",
    )


class SaveUserMemoryToolImpl(BaseTool[SaveUserMemoryInput, str]):
    name = SAVE_USER_MEMORY_TOOL_NAME
    inputSchema = SaveUserMemoryInput
    maxResultSizeChars = 1_000
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return False

    def is_concurrency_safe(self, input: Any = None) -> bool:
        # Two parallel saves to the same slug would race on the upsert.
        return False

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(
        self, input: Any, context: ToolUseContext,
    ) -> ValidationResult:
        slug = input.get("slug") if isinstance(input, dict) else getattr(input, "slug", None)
        type_ = input.get("type") if isinstance(input, dict) else getattr(input, "type", None)

        if not slug or not _SLUG_RE.match(slug):
            return ValidationError(
                message=(
                    "`slug` must be lowercase letters, digits, and "
                    "underscores only (e.g. `user_role`, `feedback_no_emoji`). "
                    f"Got: {slug!r}"
                ),
                errorCode=1,
            )
        if type_ not in _USER_TYPES:
            return ValidationError(
                message=(
                    f"`type` must be one of {sorted(_USER_TYPES)}. "
                    f"Got: {type_!r}"
                ),
                errorCode=2,
            )
        if not context.user_id:
            return ValidationError(
                message="No authenticated user on context — cannot save user memory.",
                errorCode=3,
            )
        if not context.authorization:
            return ValidationError(
                message="Missing authorization on tool context.",
                errorCode=4,
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
        parsed: SaveUserMemoryInput = (
            args if isinstance(args, SaveUserMemoryInput) else SaveUserMemoryInput(**args)
        )

        saved = await db_client.upsert_user_memory(
            context.authorization or "",
            context.user_id or "",
            slug=parsed.slug,
            type=parsed.type,
            name=parsed.name,
            description=parsed.description,
            body=parsed.body,
        )

        return ToolResult(
            data=(
                f"Saved [user:{saved['slug']}] "
                f"(type={saved['type']}, name={saved['name']!r})."
            ),
        )


SaveUserMemoryTool = SaveUserMemoryToolImpl()
