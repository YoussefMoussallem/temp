import { createContext, useContext } from "react";
import { useChat } from "../hooks/useChat";
import { useDeck } from "./DeckContext.jsx";

const ChatContext = createContext(null);

// Wraps useChat so descendants can read the chat state without prop
// drilling. Subscribes to DeckContext internally so slide_* SSE events
// reach the deck reducer automatically.
//
// ``onCreateConversation`` / ``onSetActiveConversation`` /
// ``onSetConversationTitle`` are forwarded into ``useChat`` to enable
// the auto-create-on-first-message flow. Owners of those primitives
// (App.jsx — it owns ``activeConversationId`` and the conversations
// hook) thread them in via this provider rather than ``useChat``
// reaching out to App-level state directly.
export function ChatProvider({
  getToken,
  conversationId,
  projectId,
  onCreateConversation = null,
  onSetActiveConversation = null,
  onSetConversationTitle = null,
  children,
}) {
  const deck = useDeck();
  const chat = useChat(getToken, conversationId, {
    projectId,
    onSlideEvent: deck.applySlideEvent,
    onCreateConversation,
    onSetActiveConversation,
    onSetConversationTitle,
  });
  return <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>;
}

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChatContext must be used within <ChatProvider>");
  return ctx;
}
