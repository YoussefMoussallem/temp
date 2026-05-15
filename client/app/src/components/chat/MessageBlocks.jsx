import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ThinkingBlock from "./ThinkingBlock";
import SearchBlock from "./SearchBlock";
import ToolUseBlock from "./ToolUseBlock";
import { proseClasses } from "../../utils/proseClasses";

/**
 * Render an ordered list of stream blocks in arrival order.
 *
 * Block shape:
 *   { type: "thinking", text }
 *   { type: "search",   id, query, result, active }
 *   { type: "tool",     id, name, active, progress }
 *   { type: "text",     text }
 *
 * Used by both StreamingIndicator (live) and AssistantMessage
 * (persisted) so the visual sequence is identical: the user sees
 * thinking, tool calls, searches, and prose text interleaved exactly
 * as they were emitted by the model.
 */
export default function MessageBlocks({ blocks, streaming = false, multipleSearches = false }) {
  if (!blocks || blocks.length === 0) return null;
  let searchSeen = 0;
  // Index of the last text block — only that one carries the trailing
  // cursor while streaming. If a tool/search/thinking is the trailing
  // block, those have their own activity affordance and no cursor is
  // attached.
  const lastTextIdx = streaming
    ? blocks.reduce(
        (acc, b, i) =>
          b.type === "text" && b.text && i > acc ? i : acc,
        -1,
      )
    : -1;
  return (
    <>
      {blocks.map((b, i) => {
        if (b.type === "thinking") {
          return (
            <ThinkingBlock
              key={`th-${i}`}
              text={b.text}
              done={!streaming || !b.active}
            />
          );
        }
        if (b.type === "search") {
          const idx = multipleSearches ? searchSeen++ : null;
          return (
            <SearchBlock
              key={`sr-${b.id ?? i}`}
              active={!!b.active}
              query={b.query}
              result={b.result || ""}
              index={idx}
              defaultOpen={streaming && !b.result}
            />
          );
        }
        if (b.type === "tool") {
          return (
            <ToolUseBlock
              key={`tl-${b.id ?? i}`}
              name={b.name}
              active={!!b.active}
              progress={b.progress}
              subagentActivity={b.subagentActivity}
            />
          );
        }
        if (b.type === "text") {
          if (!b.text) return null;
          const isStreamingTail = i === lastTextIdx;
          return (
            <div
              key={`tx-${i}`}
              className={
                isStreamingTail
                  ? `${proseClasses} streaming-text-tail`
                  : proseClasses
              }
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{b.text}</ReactMarkdown>
            </div>
          );
        }
        return null;
      })}
    </>
  );
}

/**
 * Derive ordered UI blocks from a persisted assistant message's raw
 * Anthropic content array. Used as a fallback for messages loaded
 * from the DB (which don't carry the streaming-time ``blocks`` meta).
 *
 * Anthropic block kinds we care about: ``text``, ``thinking``,
 * ``tool_use``. Searches aren't part of persisted assistant content
 * (they're separate SSE events), so DB-loaded messages won't
 * interleave searches — but for everything that *is* persisted we
 * preserve the model's emission order, which is the whole point.
 */
export function blocksFromRaw(raw) {
  if (!Array.isArray(raw)) return null;
  const out = [];
  for (const b of raw) {
    if (!b || typeof b !== "object") continue;
    if (b.type === "text") {
      out.push({ type: "text", text: b.text || "" });
    } else if (b.type === "thinking") {
      out.push({ type: "thinking", text: b.thinking || b.text || "" });
    } else if (b.type === "tool_use") {
      out.push({ type: "tool", id: b.id, name: b.name, active: false });
    }
  }
  return out.length ? out : null;
}
