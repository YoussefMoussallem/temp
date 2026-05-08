import { useEffect } from "react";
import { Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "frontend-comps";
import TopBar from "./components/TopBar";
import Sidebar from "./components/Sidebar";
import DashboardPage from "./pages/DashboardPage";
import UsersPage from "./pages/UsersPage";
import ProjectsPage from "./pages/ProjectsPage";
import UsagePage from "./pages/UsagePage";
import ModelsPage from "./pages/ModelsPage";

export default function App() {
  // Auth watchdog. ``AuthGate`` in main.jsx covers initial-load
  // unauthenticated state. This effect handles mid-session
  // unauthentication: explicit logout from the TopBar, MSAL session
  // revoked silently, or the silent-token-failure path in useAdminApi
  // calling signOut. ``loading`` is checked because MSAL briefly
  // reports unauthenticated during bootstrap.
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, loading } = useAuth();
  useEffect(() => {
    if (loading || isAuthenticated) return;
    if (location.pathname === "/login") return;
    navigate("/login", { replace: true });
  }, [loading, isAuthenticated, location.pathname, navigate]);

  return (
    <div className="h-screen flex flex-col bg-gray-100">
      <TopBar />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-6">
          <Routes>
            <Route index element={<DashboardPage />} />
            <Route path="users" element={<UsersPage />} />
            <Route path="projects" element={<ProjectsPage />} />
            <Route path="usage" element={<UsagePage />} />
            <Route path="models" element={<ModelsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
