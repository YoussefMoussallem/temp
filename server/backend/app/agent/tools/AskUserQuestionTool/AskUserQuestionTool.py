"""
AskUserQuestionTool — structured question prompt for user interaction.

The real "execution" happens client-side: the loop suspends via tool_request,
the frontend renders a modal, the user picks, and the next /turn carries
tool_results with the answers. Backend call() is a no-op fallback.
"""

from __future__ import annotations

from typing import Any

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
from .prompt import ASK_USER_QUESTION_TOOL_NAME, DESCRIPTION

class OptionSchema(BaseModel):
    label: str = Field(description="Display text for this option (1-5 words)")
    description: str = Field(default="", description="Explanation of what this option means")
    preview: str | None = Field(default=None, description="Optional preview content (text/code)")


class QuestionSchema(BaseModel):
    question: str = Field(description="The question to ask the user")
    header: str = Field(description="Short chip label (max 12 chars)")
    options: list[OptionSchema] = Field(description="2-4 options to choose from")
    multiSelect: bool = Field(default=False, description="Allow multiple selections")


class AskUserQuestionInput(BaseModel):
    questions: list[QuestionSchema] = Field(description="1-4 questions to ask")


class AskUserQuestionOutput(BaseModel):
    questions: list[QuestionSchema] = Field(default_factory=list)
    answers: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, dict] = Field(default_factory=dict)


class AskUserQuestionToolImpl(BaseTool[AskUserQuestionInput, AskUserQuestionOutput]):
    """AskUserQuestionTool — structured question prompt rendered client-side."""

    name = ASK_USER_QUESTION_TOOL_NAME
    inputSchema = AskUserQuestionInput
    maxResultSizeChars = 10_000
    searchHint = "ask the user a clarifying question"
    shouldDefer = True
    description_text = DESCRIPTION

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return True

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def requires_user_interaction(self) -> bool:
        return True

    async def description(self, input: Any, options: dict) -> str:
        return "Ask the user a question"

    def user_facing_name(self, input: Any = None) -> str:
        return "Ask User"

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(
        self, input: Any, context: ToolUseContext
    ) -> ValidationResult:
        qs = input.get("questions", []) if isinstance(input, dict) else getattr(input, "questions", [])
        if not qs:
            return ValidationError(message="At least one question is required", errorCode=1)
        if len(qs) > 4:
            return ValidationError(message="Maximum 4 questions allowed", errorCode=1)
        for q in qs:
            opts = q.get("options", []) if isinstance(q, dict) else getattr(q, "options", [])
            if len(opts) < 2:
                return ValidationError(message="Each question needs at least 2 options", errorCode=1)
            if len(opts) > 4:
                return ValidationError(message="Maximum 4 options per question", errorCode=1)
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[AskUserQuestionOutput]:
        parsed = args if isinstance(args, AskUserQuestionInput) else AskUserQuestionInput(**args)
        output = AskUserQuestionOutput(questions=parsed.questions)
        return ToolResult(data=output)

    def map_tool_result_to_block(self, content: AskUserQuestionOutput, tool_use_id: str) -> dict:
        lines = []
        for q in content.questions:
            answer = content.answers.get(q.question, "(no answer)")
            lines.append(f'Q: "{q.question}" = "{answer}"')
            ann = content.annotations.get(q.question, {})
            if ann.get("preview"):
                lines.append(f"  Selected preview: {ann['preview']}")
            if ann.get("notes"):
                lines.append(f"  User notes: {ann['notes']}")
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": "\n".join(lines) if lines else str(content),
        }


AskUserQuestionTool = AskUserQuestionToolImpl()
