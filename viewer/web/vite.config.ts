import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` talks to a backend started with `lbd-view --dev` (port 8765, token "dev").
// `npm run build` writes into the viewer package (viewer/src/lbd_viewer/static).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", changeOrigin: true },
      "/docs": { target: "http://127.0.0.1:8765", changeOrigin: true },
    },
  },
  build: {
    outDir: "../src/lbd_viewer/static",
    emptyOutDir: true,
  },
});
