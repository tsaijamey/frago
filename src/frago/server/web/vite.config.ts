import { defineConfig, Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Fix file:// protocol and script loading order issues
function fixFileProtocol(): Plugin {
  return {
    name: 'fix-file-protocol',
    transformIndexHtml(html) {
      // 1. Remove crossorigin and type="module" attributes (causes CORS errors under file:// protocol)
      let result = html
        .replace(/ crossorigin/g, '')
        .replace(/ type="module"/g, '');

      // 2. Move script from head to end of body (ensure DOM is parsed)
      const scriptMatch = result.match(/<script src="[^"]+"><\/script>/);
      if (scriptMatch) {
        const script = scriptMatch[0];
        result = result
          .replace(script, '')  // Remove from head
          .replace('</body>', `  ${script}\n  </body>`);  // Add to end of body
      }

      return result;
    },
  }
}

export default defineConfig({
  plugins: [react(), fixFileProtocol()],
  // Use relative paths, support file:// protocol
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: '../assets',
    emptyOutDir: true,
    sourcemap: false,
    // Disable module preload to avoid CORS issues under file:// protocol
    modulePreload: false,
    rollupOptions: {
      output: {
        // Simplify output structure
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]',
        // Use IIFE format to avoid ES modules CORS issues under file:// protocol
        format: 'iife',
        inlineDynamicImports: true,
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
})
