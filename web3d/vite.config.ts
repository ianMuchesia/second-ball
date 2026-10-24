import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// three gets its own chunk, like SOKA: the app code changes, the engine does not.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: { output: { manualChunks: { three: ["three"], react: ["react", "react-dom"] } } },
  },
});
