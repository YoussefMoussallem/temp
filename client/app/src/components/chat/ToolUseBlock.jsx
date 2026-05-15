import { useState } from "react";
import {
  Loader2,
  Wrench,
  Globe,
  Search,
  MessageSquare,
  CheckCircle2,
  ClipboardList,
  ListChecks,
  LogOut,
  Download,
  Bot,
  ChevronRight,
  ChevronDown,
} from "lucide-react";

const TOOL_ICONS = {
  WebFetch: Globe,
  WebSearch: Search,
  AskUserQuestion: MessageSquare,
  EnterPlanMode: ClipboardList,
  ExitPlanMode: LogOut,
  TodoWrite: ListChecks,
  ExportDeck: Download,
  Agent: Bot,
};

const HIDDEN_TOOLS = new Set(["ExitPlanMode", "TodoWrite"]);

// Pull a one-line action summary out of an agent_progress payload. The
// payload's ``message`` is the full subagent message; we surface the
// first tool_use or tool_result content block as the visible action so
// the activity stack reads like "↳ ReadSlide" / "✓ ReadSlide".
function _summarizeAgentProgressEntry(entry) {
  if (!entry || typeof entry !== "object") return null;
  const msg = entry.message;
  // Kickoff entry: the first emit carries the user(prompt) message + a
  // non-empty ``prompt`` field. Render as the task line so the user sees
  // what the subagent was asked to do.
  if (entry.prompt && msg?.type === "user") {
    return { kind: "kickoff", text: entry.prompt };
  }
  const content = msg?.message?.content;
  if (!Array.isArray(content)) return null;
  for (const block of content) {
    if (!block || typeof block !== "object") continue;
    if (block.type === "tool_use") {
      return { kind: "use", tool: block.name || "tool", id: block.id };
    }
    if (block.type === "tool_result") {
      return {
        kind: "result",
        toolUseId: block.tool_use_id,
        isError: !!block.is_error,
      };
    }
  }
  return null;
}

function SubagentActivityList({ activity, active }) {
  const [open, setOpen] = useState(true);
  if (!activity || activity.length === 0) return null;

  // Build display rows: pair tool_use entries with their matching
  // tool_result so each row can render outcome (✓ / ✗) instead of two
  // separate rows for the same call.
  const summaries = activity.map(_summarizeAgentProgressEntry).filter(Boolean);
  const resultsByToolUseId = new Map();
  for (const s of summaries) {
    if (s.kind === "result" && s.toolUseId) {
      resultsByToolUseId.set(s.toolUseId, s);
    }
  }
  const rows = [];
  for (const s of summaries) {
    if (s.kind === "kickoff") {
      rows.push({ kind: "kickoff", text: s.text });
    } else if (s.kind === "use") {
      const result = resultsByToolUseId.get(s.id);
      rows.push({
        kind: "use",
        tool: s.tool,
        outcome: result ? (result.isError ? "error" : "ok") : "pending",
      });
    }
  }

  if (rows.length === 0) return null;

  return (
    <div className="ml-5 mt-0.5 mb-1.5 border-l border-gray-200 pl-2 text-[11px]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-gray-400 hover:text-gray-600"
      >
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        <span>{rows.length} step{rows.length === 1 ? "" : "s"}</span>
      </button>
      {open && (
        <div className="mt-0.5 space-y-0.5">
          {rows.map((row, i) => {
            if (row.kind === "kickoff") {
              return (
                <div key={`k-${i}`} className="text-gray-500 italic">
                  task: {row.text}
                </div>
              );
            }
            const Icon =
              row.outcome === "ok" ? CheckCircle2
              : row.outcome === "error" ? CheckCircle2
              : Loader2;
            const colorClass =
              row.outcome === "ok" ? "text-gray-500"
              : row.outcome === "error" ? "text-amber-600"
              : active ? "text-brand" : "text-gray-400";
            const spinning = row.outcome === "pending";
            return (
              <div
                key={`a-${i}`}
                className={`flex items-center gap-1 ${colorClass}`}
              >
                <Icon
                  size={10}
                  className={spinning ? "animate-spin" : ""}
                />
                <span>{row.tool}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function ToolUseBlock({
  name,
  active = false,
  progress = null,
  subagentActivity = null,
}) {
  if (HIDDEN_TOOLS.has(name)) return null;

  const DoneIcon = TOOL_ICONS[name] || Wrench;
  // Skip the scalar progress text for Agent — the subagentActivity list
  // below carries the live status. For other tools, agent_progress
  // payloads never reach here so the scalar render path is unchanged.
  const isAgent = name === "Agent";
  const progressText =
    progress && !isAgent
      ? typeof progress === "string"
        ? progress
        : progress.message || ""
      : "";

  return (
    <>
      <div
        className={`flex items-center gap-1.5 mb-1.5 text-[11px] italic ${
          active ? "text-brand" : "text-gray-400"
        }`}
      >
        {active ? (
          <Loader2 size={11} className="animate-spin" />
        ) : (
          <CheckCircle2 size={11} />
        )}
        <DoneIcon size={11} />
        <span>{active ? `${name}...` : name}</span>
        {active && progressText && (
          <span className="text-gray-500 not-italic">— {progressText}</span>
        )}
      </div>
      {isAgent && subagentActivity?.length > 0 && (
        <SubagentActivityList activity={subagentActivity} active={active} />
      )}
    </>
  );
}
