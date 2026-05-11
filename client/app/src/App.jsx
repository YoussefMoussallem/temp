import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "frontend-comps";
import { DeckProvider } from "./context/DeckContext.jsx";
import { ChatProvider } from "./context/ChatContext.jsx";
import ChatPage from "./screens/ChatPage";
import ProjectsPage from "./screens/ProjectsPage";
import { useToggle } from "./hooks/useToggle";
import { useToken, useCurrentUserOid } from "./hooks/useToken";
import { useProjects } from "./hooks/useProjects";
import { useConversations } from "./hooks/useConversations";
import { primeRegistry } from "./commands/index.js";
import { setAuthInvalidator } from "./auth/invalidation.js";
import ErrorBanner from "./components/common/ErrorBanner";
import MemoryPage from "./screens/MemoryPage";

const LS_ACTIVE_PROJECT = "edwin.active_project_id";
const LS_ACTIVE_CONV = "edwin.active_conversation_id";

export default function App() {
  // Auth watchdog. ``AuthGate`` (in main.jsx) catches *initial-load*
  // unauthenticated state, but it doesn't run mid-session. If MSAL state
  // flips to unauthenticated while the user is in-app — explicit
  // ``signOut`` from the header, AAD revoking the session, the silent
  // token failure path in useToken calling signOut, or a 401 from any
  // API call routing through invalidateAuth — this effect picks it up
  // and redirects to /login. ``loading`` is checked because MSAL
  // briefly reports unauthenticated during initial bootstrap.
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, loading: authLoading, signOut } = useAuth();
  useEffect(() => {
    if (authLoading || isAuthenticated) return;
    // Belt-and-suspender redirect-loop guard. Today ``main.jsx`` only
    // mounts ``<App />`` under ``/*`` (not ``/login``) so we shouldn't
    // ever observe ``isAuthenticated=false`` while on /login — but if
    // the routing ever changes this prevents a runaway loop.
    if (location.pathname === "/login") return;
    navigate("/login", { replace: true });
  }, [authLoading, isAuthenticated, location.pathname, navigate]);

  // Register the auth-invalidation callback so non-React modules
  // (api.js, agent SSE readers) can trigger a logout when the server
  // returns 401. Without this bridge, a backend-side session
  // revocation (token still valid by MSAL but the server has dropped
  // the session) would loop on 401s with no redirect.
  useEffect(() => {
    setAuthInvalidator(signOut);
    return () => setAuthInvalidator(null);
  }, [signOut]);

  const getToken = useToken();
  const currentUserOid = useCurrentUserOid();

  const projects = useProjects(getToken);
  const [activeProjectId, setActiveProjectId] = useState(
    () => localStorage.getItem(LS_ACTIVE_PROJECT) || null,
  );
  const conversations = useConversations(getToken, activeProjectId);
  const [activeConversationId, setActiveConversationId] = useState(
    () => localStorage.getItem(LS_ACTIVE_CONV) || null,
  );

  const [chatOpen, toggleChat] = useToggle(true);
  const [slidesOpen, toggleSlides] = useToggle(true);
  // Whether the user is currently viewing a memory page (full-screen
  // surface that replaces ProjectsPage / ChatPage while open). null
  // means we render the normal project flow. Pages instead of a
  // drawer per user feedback — gives memory its own surface so users
  // don't conflate it with the chat workspace.
  const [memoryView, setMemoryView] = useState(null); // "user" | "project" | null
  const openUserMemory = () => setMemoryView("user");
  const openProjectMemory = () => setMemoryView("project");
  const closeMemory = () => setMemoryView(null);

  // Fetch the backend command registry once on boot. Populates the typeahead
  // with server-only commands (theme, export, mcp, …) that the frontend
  // doesn't otherwise know about.
  useEffect(() => {
    primeRegistry(getToken);
  }, [getToken]);

  useEffect(() => {
    if (activeProjectId) localStorage.setItem(LS_ACTIVE_PROJECT, activeProjectId);
    else localStorage.removeItem(LS_ACTIVE_PROJECT);
  }, [activeProjectId]);

  useEffect(() => {
    if (activeConversationId) localStorage.setItem(LS_ACTIVE_CONV, activeConversationId);
    else localStorage.removeItem(LS_ACTIVE_CONV);
  }, [activeConversationId]);

  // Stored project ID no longer exists (deleted elsewhere) — drop it.
  useEffect(() => {
    if (projects.loading || !activeProjectId) return;
    if (!projects.projects.find((p) => p.id === activeProjectId)) {
      setActiveProjectId(null);
      setActiveConversationId(null);
    }
  }, [projects.loading, projects.projects, activeProjectId]);

  // Stored conversation ID no longer in the active project — drop it.
  useEffect(() => {
    if (conversations.loading || !activeConversationId) return;
    if (!conversations.conversations.find((c) => c.id === activeConversationId)) {
      setActiveConversationId(null);
    }
  }, [conversations.loading, conversations.conversations, activeConversationId]);

  // Memory pages — own full-screen surfaces. Routed in front of the
  // normal project flow when memoryView is set. User scope is always
  // reachable; project scope requires an active project.
  if (memoryView === "user") {
    return (
      <>
        <ErrorBanner />
        <MemoryPage
          scope="user"
          scopeId={currentUserOid}
          onBack={closeMemory}
          getToken={getToken}
          onOpenUserMemory={openUserMemory}
        />
      </>
    );
  }
  if (memoryView === "project" && activeProjectId) {
    const activeProjectForMem = projects.projects.find((p) => p.id === activeProjectId);
    return (
      <>
        <ErrorBanner />
        <MemoryPage
          scope="project"
          scopeId={activeProjectId}
          projectName={activeProjectForMem?.name ?? null}
          onBack={closeMemory}
          getToken={getToken}
          onOpenUserMemory={openUserMemory}
        />
      </>
    );
  }

  if (!activeProjectId) {
    return (
      <>
        <ErrorBanner />
        <ProjectsPage
          projects={projects}
          onOpenProject={setActiveProjectId}
          onOpenUserMemory={openUserMemory}
          getToken={getToken}
          currentUserOid={currentUserOid}
        />
      </>
    );
  }

  const activeProject = projects.projects.find((p) => p.id === activeProjectId);

  return (
    <DeckProvider projectId={activeProjectId} getToken={getToken}>
      <ChatProvider
        getToken={getToken}
        conversationId={activeConversationId}
        projectId={activeProjectId}
        onCreateConversation={conversations.create}
        onSetActiveConversation={setActiveConversationId}
        onSetConversationTitle={conversations.setTitle}
      >
        <ErrorBanner />
        <ChatPage
          activeProject={activeProject}
          activeConversationId={activeConversationId}
          setActiveConversationId={setActiveConversationId}
          conversations={conversations}
          onBackToProjects={() => {
            setActiveProjectId(null);
            setActiveConversationId(null);
          }}
          chatOpen={chatOpen}
          toggleChat={toggleChat}
          slidesOpen={slidesOpen}
          toggleSlides={toggleSlides}
          onOpenUserMemory={openUserMemory}
          onOpenProjectMemory={openProjectMemory}
        />
      </ChatProvider>
    </DeckProvider>
  );
}
