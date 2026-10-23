import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api goes to the broadcast API (stream/api): `make api`, or API_TARGET.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": process.env.API_TARGET ?? "http://127.0.0.1:8000" },
  },
  preview: {
    proxy: { "/api": process.env.API_TARGET ?? "http://127.0.0.1:8000" },
  },
});
