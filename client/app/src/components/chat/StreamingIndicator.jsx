import { Loader2 } from "lucide-react";
import MessageBlocks from "./MessageBlocks";
import UsageBlock from "./UsageBlock";

export default function StreamingIndicator({ stream, error }) {
  const blocks = stream.blocks || [];
  const hasContent =
    blocks.length > 0 ||
    stream.usage ||
    error;

  // Multiple searches get numbered (Search 1, Search 2, …). Match the
  // old behaviour: only when more than one search appears in the stream.
  const searchCount = blocks.filter((b) => b.type === "search").length;

  return (
    <div className="py-2">
      {!hasContent && (
        <div className="flex items-center gap-2 text-[11px] text-gray-400 italic">
          <Loader2 size={12} className="animate-spin text-brand" />
          <span>Generating...</span>
        </div>
      )}

      <MessageBlocks
        blocks={blocks}
        streaming
        multipleSearches={searchCount > 1}
      />

      {error && <div className="text-xs text-red-500 mt-1">{error}</div>}

      <UsageBlock usage={stream.usage} />
    </div>
  );
}
