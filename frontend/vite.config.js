import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/admin/api": "http://127.0.0.1:8080",
      "/admin/login": "http://127.0.0.1:8080",
      "/admin/logout": "http://127.0.0.1:8080",
      "/v1": "http://127.0.0.1:8080",
      "/health": "http://127.0.0.1:8080"
    }
  }
});
