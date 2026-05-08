// Dispatches a pending tool_request from the backend to the matching
// frontend tool's UI component. Today's interactive tools:
// - AskUserQuestion: structured Q&A modal
// - ExitPlanMode: plan approval / revise
//
// ExportDeck is NOT interactive — it runs entirely on the backend (LLM
// converts each slide's HTML to a pptxgenjs spec) and pushes a
// `deck_export_ready` SSE event that useChat picks up to assemble and
// download the .pptx in the browser. No user click required.

import { UI as AskUserQuestionUI, TOOL_NAME as ASK_NAME } from "./tools/AskUserQuestionTool/index.js";
import { UI as ExitPlanModeUI, TOOL_NAME as EXIT_PLAN_NAME } from "./tools/ExitPlanModeTool/index.js";

export function PendingToolRequest({
  request,
  onSubmitToolAnswer,
  onSubmitPlanAnswer,
}) {
  if (!request) return null;

  if (request.tool_name === EXIT_PLAN_NAME) {
    return (
      <ExitPlanModeUI
        request={request}
        onApprove={() => onSubmitPlanAnswer?.(true, "")}
        onReject={(reason) => onSubmitPlanAnswer?.(false, reason)}
      />
    );
  }

  if (request.tool_name === ASK_NAME) {
    return (
      <AskUserQuestionUI
        request={request}
        onSubmit={onSubmitToolAnswer}
      />
    );
  }

  return null;
}
