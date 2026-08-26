import { defineConfig } from 'vite';

// ビルド成果物は Python のダッシュボードが配信する。
// 開発中は /api を 127.0.0.1:8787 へ中継する。
export default defineConfig({
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: true },
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8787' } },
});
