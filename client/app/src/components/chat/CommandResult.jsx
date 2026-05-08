import { Terminal } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { proseClasses } from "../../utils/proseClasses";
import HelpResult from "./results/HelpResult";
import CostResult from "./results/CostResult";
import ContextResult from "./results/ContextResult";
import MemoryResult from "./results/MemoryResult";
import SkillsResult from "./results/SkillsResult";
import ActionResult from "./results/ActionResult";

const STRUCTURED = {
  help: HelpResult,
  cost: CostResult,
  context: ContextResult,
  memory: MemoryResult,
  skills: SkillsResult,
};

const ACTIONS = new Set(["export", "compact", "remember"]);

export default function CommandResult({ content, command, data }) {
  // Action commands (export, compact, remember) — inline pill
  if (command && ACTIONS.has(command)) {
    return (
      <div className="my-3 px-3 py-2.5 rounded-xl bg-gray-50 border border-gray-100">
        <ActionResult command={command} data={data} value={content} />
      </div>
    );
  }

  // Structured data commands — rich card
  const Renderer = command && data ? STRUCTURED[command] : null;

  if (Renderer) {
    return (
      <div className="my-3 rounded-xl bg-gray-50 border border-gray-100 overflow-hidden">
        <div className="flex items-center gap-1.5 px-3.5 py-2 border-b border-gray-100">
          <Terminal size={11} className="text-brand" />
          <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">/{command}</span>
        </div>
        <div className="px-3 py-2.5">
          <Renderer data={data} />
        </div>
      </div>
    );
  }

  // Fallback — generic markdown. ReactMarkdown asserts `children` is a
  // string; coerce defensively so a content-block array (e.g. an upstream
  // builder forgot to flatten) renders as text instead of crashing the UI.
  const text = typeof content === "string"
    ? content
    : Array.isArray(content)
      ? content
          .filter((b) => b && (b.type === "text" || typeof b === "string"))
          .map((b) => (typeof b === "string" ? b : b.text ?? ""))
          .join("")
      : String(content ?? "");

  return (
    <div className="my-3 rounded-xl bg-gray-50 border border-gray-100 overflow-hidden">
      <div className="flex items-center gap-1.5 px-3.5 py-2 border-b border-gray-100">
        <Terminal size={11} className="text-brand" />
        <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Result</span>
      </div>
      <div className={`px-3.5 py-3 ${proseClasses}`}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
    </div>
  );
}
