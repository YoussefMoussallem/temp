import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import MessageBlocks, { blocksFromRaw } from "./MessageBlocks";
import UsageBlock from "./UsageBlock";
import { proseClasses } from "../../utils/proseClasses";

export default function AssistantMessage({ content, meta }) {
  // Prefer the streaming-time ordered blocks (set by useChat when the
  // turn finishes); fall back to deriving blocks from the persisted
  // Anthropic content array for messages loaded from the DB. If
  // neither is available, we degrade to "just render the text" — the
  // old pre-blocks behaviour.
  const blocks = meta?.blocks || blocksFromRaw(meta?.raw);
  const searchCount = blocks ? blocks.filter((b) => b.type === "search").length : 0;

  return (
    <div className="py-2">
      {blocks ? (
        <MessageBlocks blocks={blocks} multipleSearches={searchCount > 1} />
      ) : (
        <div className={proseClasses}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      )}

      <UsageBlock usage={meta?.usage} />
    </div>
  );
}
