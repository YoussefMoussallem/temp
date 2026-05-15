import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";

  return {
    plugins: [react(), tailwindcss()],
    test: {
      environment: "jsdom",
      globals: true,
      include: ["tests/**/*.{test,spec}.{js,jsx}"],
    },
    server: {
      port: 5174,
      proxy: {
        "/api": {
          target: apiProxyTarget,
        },
      },
    },
  };
});
