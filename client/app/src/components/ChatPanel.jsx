import { useState } from "react";
import { Eye } from "lucide-react";
import ChatToolbar from "./chat/ChatToolbar";
import MessageList from "./chat/MessageList";
import InputArea from "./chat/InputArea";
import TokenWarning from "./chat/TokenWarning";

export default function ChatPanel({
  chat,
  onSend,
  onStop,
  thinking,
  onToggleThinking,
  webSearch,
  onToggleWebSearch,
  conversations,
  conversationsLoading,
  conversationsError,
  activeConversationId,
  onSelectConversation,
  onCreateConversation,
  onDeleteConversation,
  readOnly = false,
  onClose,
}) {
  const handleCompactNow = () => {
    if (chat.busy || readOnly || !chat.conversationId) return;
    onSend?.("/compact");
  };
  const [exhausted, setExhausted] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);

  const handleLoadOlder = async () => {
    if (!chat.loadOlder || loadingOlder || exhausted) return;
    setLoadingOlder(true);
    try {
      const count = await chat.loadOlder();
      if (count === 0) setExhausted(true);
    } finally {
      setLoadingOlder(false);
    }
  };

  // Reset pagination state when conversation changes.
  const convId = chat.conversationId;
  const [lastConv, setLastConv] = useState(convId);
  if (convId !== lastConv) {
    setLastConv(convId);
    setExhausted(false);
  }

  return (
    <div className="w-full h-full bg-white flex flex-col shadow-[-1px_0_12px_rgba(0,0,0,0.04)]">
      <ChatToolbar
        thinking={thinking}
        onToggleThinking={onToggleThinking}
        webSearch={webSearch}
        onToggleWebSearch={onToggleWebSearch}
        onNewChat={chat.clear}
        agentState={chat.agentState}
        conversations={conversations}
        conversationsLoading={conversationsLoading}
        conversationsError={conversationsError}
        activeConversationId={activeConversationId}
        onSelectConversation={onSelectConversation}
        onCreateConversation={onCreateConversation}
        onDeleteConversation={onDeleteConversation}
        onClose={onClose}
      />

      <TokenWarning
        warning={chat.compactWarning}
        dismissed={!chat.compactWarningVisible}
        onDismiss={chat.dismissCompactWarning}
        onCompactNow={handleCompactNow}
        disabled={chat.busy || readOnly || !chat.conversationId}
      />

      {chat.messages.length > 0 && !exhausted && (
        <div className="px-3 py-2 border-b border-gray-100">
          <button
            type="button"
            onClick={handleLoadOlder}
            disabled={loadingOlder}
            className="w-full text-[11px] text-gray-400 hover:text-brand transition-colors disabled:opacity-50"
          >
            {loadingOlder ? "Loading…" : "Load older messages"}
          </button>
        </div>
      )}

      <MessageList
        messages={chat.messages}
        busy={chat.busy}
        stream={chat.stream}
        error={chat.error}
        loadingHistory={chat.loadingHistory}
        pendingToolRequest={chat.pendingToolRequest}
        onSubmitToolAnswer={chat.submitToolAnswer}
        onSubmitPlanAnswer={chat.submitPlanAnswer}
        todos={chat.todos}
      />

      {readOnly && (
        <div className="px-4 py-2 border-t border-gray-100 bg-blue-50/40 flex items-center gap-2 text-[11px] text-blue-700">
          <Eye size={12} />
          <span>
            You have <strong>view-only</strong> access to this project. Ask the
            owner for editor access to send messages.
          </span>
        </div>
      )}
      <InputArea
        disabled={chat.busy || readOnly}
        onSend={onSend}
        onStop={onStop}
      />
    </div>
  );
}
