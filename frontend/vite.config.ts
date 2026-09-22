import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const apiPort = process.env.VITE_API_PORT ?? "8000";
const devPort = process.env.VITE_DEV_PORT ?? (apiPort === "8001" ? "5173" : "5174");

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: Number(devPort),
    strictPort: true,
    proxy: {
      "/api": `http://localhost:${apiPort}`,
    },
  },
});
