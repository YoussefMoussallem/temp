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
        <span
          aria-label="Generating"
          className="inline-block h-4 w-[2px] bg-brand align-text-bottom animate-cursor-blink"
        />
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
