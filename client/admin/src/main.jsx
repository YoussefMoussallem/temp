import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthShell, AuthGate, LoginPage } from "frontend-comps";
import "frontend-comps/styles.css";
import "./index.css";
import App from "./App";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <AuthShell
        clientId={import.meta.env.VITE_AZURE_CLIENT_ID}
        tenantId={import.meta.env.VITE_AZURE_TENANT_ID}
      >
        <Routes>
          <Route
            path="/login"
            element={
              <LoginPage
                productName="Edwin Admin"
                tagline="Administration panel"
              />
            }
          />
          <Route
            path="/*"
            element={
              <AuthGate redirectTo="/login">
                <App />
              </AuthGate>
            }
          />
        </Routes>
      </AuthShell>
    </BrowserRouter>
  </StrictMode>,
);
