import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// 开发环境将 /api 与 /healthz 代理到本地后端；
// 可用环境变量 VITE_API_TARGET 覆盖目标（如本机另起的 API：VITE_API_TARGET=http://localhost:8010 npm run dev）
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_');
  const apiTarget = env.VITE_API_TARGET || 'http://localhost:8000';
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/healthz': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      rollupOptions: {
        output: {
          // 拆分体积较大的第三方库，避免单包过大
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            antd: ['antd', '@ant-design/icons'],
          },
        },
      },
    },
  };
});
