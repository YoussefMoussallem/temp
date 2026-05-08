from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ...Tool import (
    BaseTool,
    ToolResult,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, TODO_WRITE_TOOL_NAME


class TodoItem(BaseModel):
    id: str = Field(description="Unique identifier for this todo item")
    subject: str = Field(description="Short description of the task")
    status: Literal["pending", "in_progress", "completed"] = "pending"


class TodoWriteInput(BaseModel):
    todos: list[TodoItem] = Field(description="Complete list of todo items (replaces previous list)")


class TodoWriteToolImpl(BaseTool[TodoWriteInput, str]):
    name = TODO_WRITE_TOOL_NAME
    inputSchema = TodoWriteInput
    maxResultSizeChars = 10_000
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return True

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(
        self, input: Any, context: ToolUseContext
    ) -> ValidationResult:
        todos = input.get("todos", []) if isinstance(input, dict) else getattr(input, "todos", [])
        if not todos:
            return ValidationError(message="todos list must not be empty", errorCode=1)
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[str]:
        parsed: TodoWriteInput = (
            args if isinstance(args, TodoWriteInput) else TodoWriteInput(**args)
        )
        completed = sum(1 for t in parsed.todos if t.status == "completed")
        return ToolResult(
            data=f"Todo list updated: {len(parsed.todos)} items, {completed} completed."
        )


TodoWriteTool = TodoWriteToolImpl()
