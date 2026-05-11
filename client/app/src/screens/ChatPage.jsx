import { Lock, PanelLeftOpen, PanelRightOpen, Presentation, MessageSquare } from "lucide-react";
import Header from "../components/common/Header";
import SlideFilmstrip from "../components/deck/SlideFilmstrip";
import DeckPreview from "../components/deck/DeckPreview";
import ChatPanel from "../components/ChatPanel";
import ResizeHandle from "../components/common/ResizeHandle";
import { useDeck } from "../context/DeckContext.jsx";
import { useChatContext } from "../context/ChatContext.jsx";
import { useResizable } from "../hooks/useResizable";
import { useToggle } from "../hooks/useToggle";

export default function ChatPage({
  activeProject,
  activeConversationId,
  setActiveConversationId,
  conversations,
  onBackToProjects,
  chatOpen,
  toggleChat,
  slidesOpen,
  toggleSlides,
  onOpenUserMemory,
  onOpenProjectMemory,
}) {
  const deck = useDeck();
  const chat = useChatContext();

  // Viewers can read history but not send new messages — the backend
  // would 403 on /turn anyway, so disable the input proactively.
  const isViewer = activeProject?.role === "viewer";

  const slidePanel = useResizable(150, 100, 260);
  const chatPanel = useResizable(420, 320, 640, true);
  const [thinking, toggleThinking] = useToggle(false);
  const [webSearch, toggleWebSearch] = useToggle(true);

  const handleSend = (text) => {
    chat.send(text, { thinking, webSearch });
  };

  const handleCreateConversation = async (title) => conversations.create(title);
  const handleDeleteConversation = async (id) => {
    await conversations.remove(id);
    if (activeConversationId === id) setActiveConversationId(null);
  };

  return (
    <div className="h-screen flex flex-col bg-gray-100">
      <Header
        activeProjectName={activeProject?.name}
        onBackToProjects={onBackToProjects}
        onOpenUserMemory={onOpenUserMemory}
      />

      {deck.forbidden && (
        <ForbiddenOverlay
          projectName={activeProject?.name}
          onLeave={onBackToProjects}
        />
      )}

      <div className="flex-1 flex overflow-hidden">
        {slidesOpen ? (
          <>
            <div style={{ width: slidePanel.width }} className="shrink-0">
              <SlideFilmstrip
                slides={deck.slides}
                selectedIndex={deck.selectedIndex}
                onSelect={deck.setSelectedIndex}
                onReorder={deck.reorderSlide}
                onDelete={deck.deleteSlide}
                isLoading={deck.isLoading}
                readOnly={isViewer}
                onClose={toggleSlides}
              />
            </div>
            <ResizeHandle onResize={slidePanel.onResize} />
          </>
        ) : (
          <PeekTab side="left" icon={Presentation} label="Slides" onClick={toggleSlides} />
        )}

        <DeckPreview slide={deck.selectedSlide} />

        {chatOpen ? (
          <>
            <ResizeHandle onResize={chatPanel.onResize} />
            <div style={{ width: chatPanel.width }} className="shrink-0">
              <ChatPanel
                chat={chat}
                onSend={handleSend}
                onStop={chat.stop}
                thinking={thinking}
                onToggleThinking={toggleThinking}
                webSearch={webSearch}
                onToggleWebSearch={toggleWebSearch}
                conversations={conversations.conversations}
                conversationsLoading={conversations.loading}
                conversationsError={conversations.error}
                activeConversationId={activeConversationId}
                onSelectConversation={setActiveConversationId}
                onCreateConversation={handleCreateConversation}
                onDeleteConversation={handleDeleteConversation}
                readOnly={isViewer}
                onClose={toggleChat}
                onOpenProjectMemory={onOpenProjectMemory}
              />
            </div>
          </>
        ) : (
          <PeekTab side="right" icon={MessageSquare} label="Chat" onClick={toggleChat} />
        )}
      </div>
    </div>
  );
}

/**
 * Slim vertical tab on the edge of the screen — replaces the old
 * header toggle for showing a hidden panel. Slides peek on the left,
 * chat peeks on the right, both with their own icon so the user knows
 * what they're reopening.
 */
function PeekTab({ side, icon: Icon, label, onClick }) {
  const isLeft = side === "left";
  const ChevronIcon = isLeft ? PanelLeftOpen : PanelRightOpen;
  return (
    <button
      type="button"
      onClick={onClick}
      title={`Show ${label.toLowerCase()}`}
      className={`group h-full w-7 shrink-0 flex flex-col items-center justify-center gap-2 bg-white/60 hover:bg-white border-gray-200/60 transition-colors cursor-pointer ${
        isLeft ? "border-r" : "border-l"
      }`}
    >
      <ChevronIcon
        size={14}
        className="text-gray-400 group-hover:text-brand transition-colors"
      />
      <span
        className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 group-hover:text-brand transition-colors"
        style={{ writingMode: "vertical-rl", textOrientation: "mixed" }}
      >
        {label}
      </span>
      <Icon
        size={12}
        className="text-gray-300 group-hover:text-brand transition-colors"
      />
    </button>
  );
}

// Modal overlay shown when a deck-level fetch returns 403 — the user
// has been removed from this project mid-session. We block interaction
// with the now-stale UI behind it (otherwise the user keeps clicking
// into the filmstrip and getting more 403s) and offer a single exit:
// "Back to projects". Refresh would re-fetch the project list and
// quietly drop this project from view via the existing App.jsx guard.
function ForbiddenOverlay({ projectName, onLeave }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 backdrop-blur-sm">
      <div className="max-w-sm w-full mx-4 rounded-xl bg-white shadow-xl p-6 text-center">
        <div className="mx-auto w-12 h-12 rounded-full bg-red-50 flex items-center justify-center mb-4">
          <Lock size={20} className="text-red-600" />
        </div>
        <h2 className="text-base font-semibold text-gray-900 mb-1">
          You don't have access
        </h2>
        <p className="text-sm text-gray-600 mb-5">
          {projectName
            ? `Your access to "${projectName}" was removed.`
            : "Your access to this project was removed."}
        </p>
        <button
          type="button"
          onClick={onLeave}
          className="w-full px-4 py-2 rounded-lg bg-brand text-white text-sm font-medium hover:bg-brand/90 transition-colors"
        >
          Back to projects
        </button>
      </div>
    </div>
  );
}
