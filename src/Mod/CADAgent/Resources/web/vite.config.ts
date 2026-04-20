import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build into ./dist/ and use relative paths so Qt can load index.html via file://
// After `npm run build`, point WebChatPanel.py at Resources/web/dist/index.html.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsInlineLimit: 0,
  },
});
