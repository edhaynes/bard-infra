import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Bard console — Vite + React (ADR-0007). Port chosen to avoid the
// Router (8080) / Registry (8081) / agent sshd (2222) used by the stack.
export default defineConfig({
  plugins: [react()],
  server: { port: 5273 },
});
