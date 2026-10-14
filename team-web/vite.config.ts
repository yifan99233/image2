import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");

  return {
    base: "./",
    plugins: [react()],
    server: {
      port: 5176,
      proxy: env.VITE_PROXY_API_TARGET
        ? {
            "/api": {
              target: env.VITE_PROXY_API_TARGET,
              changeOrigin: true,
              secure: true,
              rewrite: (requestPath) => requestPath.replace(/^\/api/, ""),
            },
          }
        : undefined,
    },
  };
});
