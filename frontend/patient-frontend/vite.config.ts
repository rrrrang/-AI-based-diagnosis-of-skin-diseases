/** 독립 개발 서버: 환자 5173 / 의사 5174 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': process.env.SKINAI_API_TARGET ?? 'http://127.0.0.1:8000' },
  },
});
