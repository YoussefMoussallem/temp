import { useRef, useEffect } from "react";
import Message from "./Message";
import StreamingIndicator from "./StreamingIndicator";
import Skeleton from "../common/Skeleton";
import { UI as TodoWriteUI } from "../../agent/tools/TodoWriteTool/index.js";
import { PendingToolRequest } from "../../agent/toolExecutor.jsx";

export default function MessageList({ messages, busy, stream, error, loadingHistory = false, pendingToolRequest, onSubmitToolAnswer, onSubmitPlanAnswer, todos }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, stream.fullText]);

  // History fetch in flight: render skeleton bubbles instead of either
  // the real list (would be empty) or the "describe your presentation"
  // empty-state CTA (would be wrong — we don't yet know if there are
  // messages or not).
  if (messages.length === 0 && loadingHistory) {
    return <HistorySkeleton />;
  }

  // History fetch finished but an error happened — surface it instead
  // of falling through to the empty CTA, otherwise the user thinks
  // it's a fresh conversation when actually we just couldn't load.
  if (messages.length === 0 && !busy && !loadingHistory && error) {
    return (
      <div className="flex-1 flex items-center justify-center text-center px-8">
        <div className="rounded-md border border-red-200 bg-red-50/60 px-4 py-3 text-[12px] text-red-700 max-w-sm">
          Couldn't load this conversation: {error}
        </div>
      </div>
    );
  }

  if (messages.length === 0 && !busy) {
    return (
      <div className="flex-1 flex items-center justify-center text-center px-8">
        <p className="text-[13px] text-gray-400 leading-relaxed">
          Describe your presentation to get started.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="px-5 py-4">
        {messages.map((msg, i) => (
          <Message key={i} message={msg} />
        ))}

        {busy && <StreamingIndicator stream={stream} error={error} />}

        <TodoWriteUI todos={todos} />

        <PendingToolRequest
          request={pendingToolRequest}
          onSubmitToolAnswer={onSubmitToolAnswer}
          onSubmitPlanAnswer={onSubmitPlanAnswer}
        />

        {!busy && error && (
          <div className="text-xs text-red-500 py-2">{error}</div>
        )}

        <div ref={endRef} />
      </div>
    </div>
  );
}

// Three alternating-side skeleton bubbles. Roughly mimics the real
// MessageList layout (user-right / assistant-left / user-right) so the
// content snap on real-data arrival is minimal. Counts/widths are
// hand-picked to look plausibly "chat-like" rather than uniform.
function HistorySkeleton() {
  return (
    <div className="flex-1 overflow-hidden" aria-label="Loading conversation">
      <div className="px-5 py-4 flex flex-col gap-4">
        <SkeletonBubble side="right" lines={1} widths={["w-2/3"]} />
        <SkeletonBubble side="left" lines={3} widths={["w-3/4", "w-full", "w-1/2"]} />
        <SkeletonBubble side="right" lines={2} widths={["w-1/2", "w-2/3"]} />
      </div>
    </div>
  );
}

function SkeletonBubble({ side, lines, widths }) {
  const isUser = side === "right";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-xl px-4 py-2.5 flex flex-col gap-1.5 ${
          isUser ? "bg-gray-100" : "bg-gray-50 ring-1 ring-gray-200/60"
        }`}
      >
        {Array.from({ length: lines }).map((_, i) => (
          <Skeleton key={i} className={`h-3 ${widths[i] ?? "w-full"}`} />
        ))}
      </div>
    </div>
  );
}
