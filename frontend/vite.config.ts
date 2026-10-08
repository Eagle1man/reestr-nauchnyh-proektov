import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// П.10.2 п.5: рабочие формы корректно отображаются от 1366×768, публичная
// часть — от 360 пикселей. П.10.2 п.3: поддерживаются две последние стабильные
// версии Chrome, Edge и Firefox — трансляция esbuild по умолчанию.
export default defineConfig({
  plugins: [react()],
  build: {
    // Цель по умолчанию не включает IE; для перечисленных браузеров
    // достаточно es2020. Sourcemaps выключены: исходный код закрытой зоны
    // не должен попадать в сборку публичной части.
    target: 'es2020',
    sourcemap: false,
    outDir: 'dist',
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    proxy: {
      // В разработке API живёт на backend; в сборке — тот же домен,
      // поэтому префикс /api в собранной версии работает без настройки.
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8077',
        changeOrigin: true,
      },
    },
  },
});