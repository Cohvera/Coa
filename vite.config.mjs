import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Keep this small portal independent of parent workspace PostCSS settings.
  css: { postcss: { plugins: [] } },
});
