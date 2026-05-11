import { Brain, Globe, ClipboardList, PanelRightClose } from "lucide-react";
import ConversationMenu from "./ConversationMenu";

export default function ChatToolbar({
  thinking,
  onToggleThinking,
  webSearch,
  onToggleWebSearch,
  onNewChat,
  agentState,
  conversations,
  conversationsLoading,
  conversationsError,
  activeConversationId,
  onSelectConversation,
  onCreateConversation,
  onDeleteConversation,
  onClose,
}) {
  return (
    <div className="px-3 h-12 flex items-center gap-1.5 shrink-0 border-b border-gray-100 min-w-0">
      {conversations && (
        <ConversationMenu
          conversations={conversations}
          loading={conversationsLoading}
          error={conversationsError}
          activeId={activeConversationId}
          onSelect={onSelectConversation}
          onCreate={onCreateConversation}
          onDelete={onDeleteConversation}
        />
      )}

      <div className="w-px h-4 bg-gray-200 mx-0.5 shrink-0" />

      <div className="mr-auto" />

      {agentState?.permission_mode === "plan" && (
        <div className="shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 text-[10px] font-semibold">
          <ClipboardList size={10} />
          <span>Plan</span>
        </div>
      )}

      <ToggleButton
        active={thinking}
        onClick={onToggleThinking}
        icon={<Brain size={13} />}
        label="Think"
        title="Thinking"
      />

      <ToggleButton
        active={webSearch}
        onClick={onToggleWebSearch}
        icon={<Globe size={13} />}
        label="Search"
        title="Search"
      />

      {onClose && (
        <button
          onClick={onClose}
          title="Hide chat"
          className="shrink-0 w-7 h-7 rounded-md flex items-center justify-center text-gray-400 hover:bg-gray-50 hover:text-gray-700 transition-colors cursor-pointer"
        >
          <PanelRightClose size={14} />
        </button>
      )}
    </div>
  );
}

function ToggleButton({ active, onClick, icon, label, title }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`shrink-0 h-7 px-2 rounded-md flex items-center gap-1.5 text-[11px] font-medium transition-all duration-150 cursor-pointer
        ${active
          ? "bg-brand/10 text-brand"
          : "text-gray-400 hover:bg-gray-50 hover:text-gray-600"
        }`}
    >
      {icon}
      <span className="hidden xl:inline">{label}</span>
    </button>
  );
}
