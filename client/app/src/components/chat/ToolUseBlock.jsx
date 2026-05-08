import { Loader2, Wrench, Globe, Search, MessageSquare, CheckCircle2, ClipboardList, ListChecks, LogOut, Download } from "lucide-react";

const TOOL_ICONS = {
  WebFetch: Globe,
  WebSearch: Search,
  AskUserQuestion: MessageSquare,
  EnterPlanMode: ClipboardList,
  ExitPlanMode: LogOut,
  TodoWrite: ListChecks,
  ExportDeck: Download,
};

const HIDDEN_TOOLS = new Set(["ExitPlanMode", "TodoWrite"]);

export default function ToolUseBlock({ name, active = false, progress = null }) {
  if (HIDDEN_TOOLS.has(name)) return null;

  const DoneIcon = TOOL_ICONS[name] || Wrench;
  const progressText = progress
    ? (typeof progress === "string" ? progress : progress.message || "")
    : "";

  return (
    <div className={`inline-flex items-center gap-1.5 mb-1.5 text-[11px] italic
      ${active ? "text-brand" : "text-gray-400"}`}
    >
      {active
        ? <Loader2 size={11} className="animate-spin" />
        : <CheckCircle2 size={11} />
      }
      <DoneIcon size={11} />
      <span>{active ? `${name}...` : name}</span>
      {active && progressText && (
        <span className="text-gray-500 not-italic">— {progressText}</span>
      )}
    </div>
  );
}
