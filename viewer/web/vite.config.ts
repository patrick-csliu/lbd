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
    // One script for the whole page (about 600 kB, 190 kB compressed) is right here: the page is
    // loaded from this computer, so Vite's 500 kB hint for websites doesn't apply.
    chunkSizeWarningLimit: 1000,
  },
});
