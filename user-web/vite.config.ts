import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(projectRoot, "src"),
      },
    },
    server: {
      proxy: env.VITE_PROXY_API_TARGET
        ? {
            "/image2-assets": {
              target: new URL(env.VITE_PROXY_API_TARGET).origin,
              changeOrigin: true,
              secure: true,
            },
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
