import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";

  return {
    plugins: [react(), tailwindcss()],
    test: {
      // jsdom gives us window/document for component tests; node mode
      // would require every test that touches the DOM to opt in.
      environment: "jsdom",
      globals: true,
      // Pin a single tests/ root so test discovery is fast and the
      // file layout matches the backend convention.
      include: ["tests/**/*.{test,spec}.{js,jsx}"],
    },
    server: {
      proxy: {
        "/api": {
          target: apiProxyTarget,
          configure: (proxy) => {
            proxy.on("proxyRes", (proxyRes) => {
              const ct = proxyRes.headers["content-type"] || "";
              if (ct.includes("text/event-stream")) {
                proxyRes.headers["cache-control"] = "no-cache";
                proxyRes.headers["x-accel-buffering"] = "no";
                delete proxyRes.headers["content-length"];
              }
            });
          },
        },
      },
    },
  };
});
