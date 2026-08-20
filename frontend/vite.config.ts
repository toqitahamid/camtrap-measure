import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // built assets ship inside the Python package; FastAPI serves them
  build: { outDir: '../src/camtrap_measure/ui', emptyOutDir: true },
})
