"""SaveMemory — upsert a long-term agent memory in either user or project scope."""

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
from .prompt import DESCRIPTION, SAVE_MEMORY_TOOL_NAME


# Match the regex enforced by db-service's UpsertUserMemoryRequest /
# UpsertProjectMemoryRequest. Validating here surfaces a clean error
# message to the model instead of bubbling an HTTP 422 from db-service.
_SLUG_RE = re.compile(r"^[a-z0-9_]+$")

# Allowed types per scope. Keep tight — the model will invent new tags
# if we don't pin them, and the system-prompt rendering relies on a
# small known set.
_USER_TYPES = {"user", "feedback", "reference"}
_PROJECT_TYPES = {"project", "reference", "stakeholder", "decision"}


class SaveMemoryInput(BaseModel):
    scope: Literal["user", "project"] = Field(
        description="Which memory store to write to. See description for guidance.",
    )
    slug: str = Field(
        max_length=64,
        description="Stable handle (lowercase letters, digits, underscores).",
    )
    type: str = Field(
        max_length=32,
        description="Category tag — see description for the allowed values per scope.",
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


class SaveMemoryToolImpl(BaseTool[SaveMemoryInput, str]):
    name = SAVE_MEMORY_TOOL_NAME
    inputSchema = SaveMemoryInput
    maxResultSizeChars = 1_000
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return False

    def is_concurrency_safe(self, input: Any = None) -> bool:
        # Writes to db-service. Two parallel saves with the same
        # (scope, slug) would race on the upsert — keep serial.
        return False

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(
        self, input: Any, context: ToolUseContext,
    ) -> ValidationResult:
        scope = input.get("scope") if isinstance(input, dict) else getattr(input, "scope", None)
        slug = input.get("slug") if isinstance(input, dict) else getattr(input, "slug", None)
        type_ = input.get("type") if isinstance(input, dict) else getattr(input, "type", None)

        if not slug or not _SLUG_RE.match(slug):
            return ValidationError(
                message=(
                    "`slug` must be lowercase letters, digits, and "
                    "underscores only (e.g. `user_role`, `audience`). "
                    f"Got: {slug!r}"
                ),
                errorCode=1,
            )

        if scope == "user":
            if type_ not in _USER_TYPES:
                return ValidationError(
                    message=(
                        f"For scope=\"user\", type must be one of "
                        f"{sorted(_USER_TYPES)}. Got: {type_!r}"
                    ),
                    errorCode=2,
                )
            if not context.user_id:
                return ValidationError(
                    message="No authenticated user on context — cannot save user memory.",
                    errorCode=3,
                )
        elif scope == "project":
            if type_ not in _PROJECT_TYPES:
                return ValidationError(
                    message=(
                        f"For scope=\"project\", type must be one of "
                        f"{sorted(_PROJECT_TYPES)}. Got: {type_!r}"
                    ),
                    errorCode=4,
                )
            if not context.project_id:
                return ValidationError(
                    message=(
                        "No active project on context — cannot save project "
                        "memory. Either ask the user to open a project or "
                        "save with scope=\"user\" if the fact generalises."
                    ),
                    errorCode=5,
                )

        if not context.authorization:
            return ValidationError(
                message="Missing authorization on tool context.",
                errorCode=6,
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
        parsed: SaveMemoryInput = (
            args if isinstance(args, SaveMemoryInput) else SaveMemoryInput(**args)
        )

        if parsed.scope == "user":
            saved = await db_client.upsert_user_memory(
                context.authorization or "",
                context.user_id or "",
                slug=parsed.slug,
                type=parsed.type,
                name=parsed.name,
                description=parsed.description,
                body=parsed.body,
            )
        else:
            saved = await db_client.upsert_project_memory(
                context.authorization or "",
                context.project_id or "",
                slug=parsed.slug,
                type=parsed.type,
                name=parsed.name,
                description=parsed.description,
                body=parsed.body,
            )

        # Result text mirrors CreateSlide's "Created slide … at position …"
        # confirmation — short, includes the addressable handle so the
        # model can refer back to it in the same turn.
        return ToolResult(
            data=(
                f"Saved [{parsed.scope}:{saved['slug']}] "
                f"(type={saved['type']}, name={saved['name']!r})."
            ),
        )


SaveMemoryTool = SaveMemoryToolImpl()
