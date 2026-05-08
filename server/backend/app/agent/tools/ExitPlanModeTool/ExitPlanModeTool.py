from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ...Tool import BaseTool, ToolResult, ToolUseContext
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, EXIT_PLAN_MODE_TOOL_NAME


class ExitPlanModeInput(BaseModel):
    plan: str = Field(description="Markdown-formatted plan to present for user approval")


class ExitPlanModeToolImpl(BaseTool[ExitPlanModeInput, str]):
    name = EXIT_PLAN_MODE_TOOL_NAME
    inputSchema = ExitPlanModeInput
    maxResultSizeChars = 50_000
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return True

    def requires_user_interaction(self) -> bool:
        return True

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[str]:
        return ToolResult(data="Plan submitted for approval.")

    def map_tool_result_to_block(self, content: Any, tool_use_id: str) -> dict:
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": str(content) if content is not None else "",
        }


ExitPlanModeTool = ExitPlanModeToolImpl()
