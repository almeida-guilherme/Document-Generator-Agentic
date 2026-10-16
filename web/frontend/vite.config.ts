import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs separately (uvicorn on port 8000); Vite forwards /api to it so the
// login cookie stays on one origin, as it does in production where FastAPI serves the built app.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
