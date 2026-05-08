from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ...Tool import BaseTool, ToolResult, ToolUseContext
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, ENTER_PLAN_MODE_TOOL_NAME


class EnterPlanModeInput(BaseModel):
    pass


class EnterPlanModeToolImpl(BaseTool[EnterPlanModeInput, str]):
    name = ENTER_PLAN_MODE_TOOL_NAME
    inputSchema = EnterPlanModeInput
    maxResultSizeChars = 1_000
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        # Mutates context.options.permissionMode; must run sequentially so
        # no other tool's call() observes a mid-flip mode value.
        return False

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
        context.options.permissionMode = "plan"
        return ToolResult(
            data="Plan mode activated. Outline your approach with TodoWrite, "
                 "then call ExitPlanMode with your complete plan."
        )


EnterPlanModeTool = EnterPlanModeToolImpl()
