import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
    base: "/canvas-app/",
    plugins: [react()],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    define: { __APP_VERSION__: JSON.stringify("image2-e856c878"), __APP_RELEASES__: "[]" },
    build: { outDir: "../user-web/public/canvas-app", emptyOutDir: true },
});
