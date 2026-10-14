import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const proxyAdminApiTarget = env.VITE_PROXY_ADMIN_API_TARGET;

  return {
    plugins: [react()],
    server: {
      port: 5174,
      proxy: proxyAdminApiTarget
        ? {
          "/admin-api": {
            target: proxyAdminApiTarget,
            changeOrigin: true,
            secure: true,
            rewrite: (requestPath) => requestPath.replace(/^\/admin-api/, ""),
          },
          }
        : undefined,
    },
  };
});
