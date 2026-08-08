import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // 개발 서버에서 API 는 백엔드로 넘긴다. 쿠키가 같은 출처로 오가야 세션이 유지된다.
    proxy: { "/api": { target: "http://127.0.0.1:8005", changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: false },
});
