import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// 开发端口 8902；后端默认 8900。线上经反向代理合并。
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    host: "0.0.0.0",
    port: 8902,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8900",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:8900",
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
