import { useState } from "react";
import { Scissors, ChevronDown, ChevronUp, User, Bot } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { proseClasses } from "../../utils/proseClasses";

/**
 * Inline divider rendered in the message list whenever the backend
 * fired a compaction (auto threshold or manual /compact). The divider
 * has two arrival paths into the chat list, both produce the same
 * `boundary` payload shape:
 *
 *   1. Mid-session: SSE `compact_boundary` event from the active turn.
 *      `useChat`'s onCompactBoundary handler injects a
 *      {role: "compact-boundary", boundary} message.
 *   2. From history: a persisted system-role row whose content[0].type
 *      is "compact_boundary". `rowToUiMessage` (messageBuilders.js)
 *      rewrites that row to the same shape on initial load and
 *      "Load older messages".
 *
 * Either way `<Message>` dispatches the row to this component.
 *
 * Props: the `boundary` payload:
 *   { tokens_before, tokens_after, dropped_count, summary, manual, compacted_at }
 *
 * The shape is normalised by the streamHandler / row mapper — anything
 * missing is treated as 0 / "" so this component never throws on a
 * partial event.
 */
export default function CompactBoundary({ boundary }) {
  const [expanded, setExpanded] = useState(false);
  if (!boundary) return null;

  const before = boundary.tokens_before ?? 0;
  const after = boundary.tokens_after ?? 0;
  const dropped = boundary.dropped_count ?? 0;
  const saved = Math.max(0, before - after);
  const summary = (boundary.summary || "").trim();
  const manual = !!boundary.manual;

  const headline = manual
    ? "Conversation summarised (manual)"
    : "Conversation summarised";
  const subhead = `${dropped} message${dropped === 1 ? "" : "s"} replaced · saved ~${saved.toLocaleString()} tokens`;
  const SourceIcon = manual ? User : Bot;

  return (
    <div className="my-4 select-none">
      <div className="flex items-center gap-2 text-[11px] text-gray-400">
        <div className="flex-1 border-t border-dashed border-gray-200" />
        <Scissors size={11} className="text-gray-300" />
        <SourceIcon size={11} className="text-gray-300" />
        <span className="font-medium">{headline}</span>
        <div className="flex-1 border-t border-dashed border-gray-200" />
      </div>

      <div className="text-center text-[11px] text-gray-400 mt-1">
        {subhead}
      </div>

      {summary && (
        <div className="text-center mt-1.5">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-gray-400 hover:text-brand transition-colors"
          >
            {expanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            {expanded ? "Hide summary" : "Show summary"}
          </button>
        </div>
      )}

      {expanded && summary && (
        <div className="mt-2 mx-2 px-3 py-2 bg-gray-50 border border-gray-200 rounded-md">
          <div className={proseClasses}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{summary}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
