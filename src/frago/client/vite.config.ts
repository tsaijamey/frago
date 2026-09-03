import { defineConfig, Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Fix file:// protocol and script loading order issues
function fixFileProtocol(): Plugin {
  return {
    name: 'fix-file-protocol',
    // 只在 build 阶段生效。dev 下若也剥掉 type="module"，main.tsx 会被当成
    // classic script 加载失败，React 永远挂不上，页面卡在「启动中…」。
    apply: 'build',
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
    outDir: '../server/assets',
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
    // dev 下前端独立起服务，接口与推送转给本机后端，页面拿到的是真实数据。
    proxy: {
      '/api': { target: 'http://127.0.0.1:8093', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8093', ws: true },
    },
  },
})
