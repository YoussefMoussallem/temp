"""SaveProjectMemory — upsert a long-term memory in the project scope."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db import memories

from ...Tool import (
    BaseTool,
    ToolResult,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, SAVE_PROJECT_MEMORY_TOOL_NAME


_SLUG_RE = re.compile(r"^[a-z0-9_]+$")

# Types valid for project-scope memory. Note the absence of `user` and
# `feedback` — those signal cross-project facts and belong in
# SaveUserMemory. Enforced here so a misrouted save fails with a clear
# scope-routing hint.
_PROJECT_TYPES = {"project", "reference", "stakeholder", "decision"}


class SaveProjectMemoryInput(BaseModel):
    slug: str = Field(
        max_length=64,
        description="Stable handle (lowercase letters, digits, underscores).",
    )
    type: Literal["project", "reference", "stakeholder", "decision"] = Field(
        description="Category tag. project = general project fact; decision = explicit choice; stakeholder = who matters; reference = external pointer.",
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


class SaveProjectMemoryToolImpl(BaseTool[SaveProjectMemoryInput, str]):
    name = SAVE_PROJECT_MEMORY_TOOL_NAME
    inputSchema = SaveProjectMemoryInput
    maxResultSizeChars = 1_000
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return False

    def is_concurrency_safe(self, input: Any = None) -> bool:
        # Different slugs → independent UPSERTs at the DB level.
        # Two saves to the same slug race into last-write-wins, which
        # is the documented "overwrite" semantic anyway.
        return True

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(
        self,
        input: Any,
        context: ToolUseContext,
    ) -> ValidationResult:
        slug = input.get("slug") if isinstance(input, dict) else getattr(input, "slug", None)
        type_ = input.get("type") if isinstance(input, dict) else getattr(input, "type", None)

        if not slug or not _SLUG_RE.match(slug):
            return ValidationError(
                message=(
                    "`slug` must be lowercase letters, digits, and "
                    "underscores only (e.g. `audience`, `deadline`). "
                    f"Got: {slug!r}"
                ),
                errorCode=1,
            )
        if type_ not in _PROJECT_TYPES:
            return ValidationError(
                message=(
                    f"`type` must be one of {sorted(_PROJECT_TYPES)}. "
                    f"`user` / `feedback` types belong in SaveUserMemory "
                    f"(different scope). Got: {type_!r}"
                ),
                errorCode=2,
            )
        if not context.project_id:
            return ValidationError(
                message=(
                    "No active project on context — cannot save project "
                    "memory. Either open a project first, or use "
                    "SaveUserMemory if the fact generalises across decks."
                ),
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
        parsed: SaveProjectMemoryInput = (
            args if isinstance(args, SaveProjectMemoryInput) else SaveProjectMemoryInput(**args)
        )

        saved = await memories.upsert_project_memory(
            context.authorization or "",
            context.project_id or "",
            slug=parsed.slug,
            type=parsed.type,
            name=parsed.name,
            description=parsed.description,
            body=parsed.body,
        )

        return ToolResult(
            data=(
                f"Saved [project:{saved['slug']}] (type={saved['type']}, name={saved['name']!r})."
            ),
        )


SaveProjectMemoryTool = SaveProjectMemoryToolImpl()
