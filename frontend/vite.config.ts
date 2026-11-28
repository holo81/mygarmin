import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to the local backend so the frontend never needs
// to know the backend port and no CORS issues arise in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts: [".ts.net"],
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8787",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
