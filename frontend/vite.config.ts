import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { existsSync, readFileSync } from "node:fs";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as { version: string };

const BACKEND = process.env.ROLO_BACKEND_URL ?? "http://localhost:8000";

// HTTPS when ROLO_CERT and ROLO_KEY point to files (run.sh sets them; phones need a secure
// page for the microphone). Otherwise plain HTTP as before.
const certPath = process.env.ROLO_CERT;
const keyPath = process.env.ROLO_KEY;
const https =
  certPath && keyPath && existsSync(certPath) && existsSync(keyPath)
    ? { cert: readFileSync(certPath), key: readFileSync(keyPath) }
    : undefined;
if ((certPath || keyPath) && !https) {
  console.warn("[rolo] ROLO_CERT/ROLO_KEY set but the files weren't found; serving plain HTTP.");
}

const proxy = {
  "/api": { target: BACKEND, changeOrigin: true },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    https,
    proxy,
  },
  preview: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    https,
    proxy,
  },
});
