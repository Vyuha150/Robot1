import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 2500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("@tensorflow") || id.includes("tfjs")) {
            return "tensorflow";
          }
          if (id.includes("coco-ssd")) {
            return "vision-models";
          }
        }
      }
    }
  },
  server: {
    port: 3000,
    host: "0.0.0.0"
  }
});
