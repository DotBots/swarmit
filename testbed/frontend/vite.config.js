import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from "node:path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(),],
  base: '/',
  resolve: {
    alias: {
      // Force any internal React references to use your top-level React
      // I had to add this, because I was having conflicts
      // between this projects react and qrkey package react.
      react: path.resolve("./node_modules/react"),
      "react-dom": path.resolve("./node_modules/react-dom"),
    },
  },
  define: {
    "process.env": {},
  },
})
