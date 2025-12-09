import { defineConfig, Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// 修复 file:// 协议和脚本加载时序问题
function fixFileProtocol(): Plugin {
  return {
    name: 'fix-file-protocol',
    transformIndexHtml(html) {
      // 1. 移除 crossorigin 和 type="module" 属性（file:// 协议下会导致 CORS 错误）
      let result = html
        .replace(/ crossorigin/g, '')
        .replace(/ type="module"/g, '');

      // 2. 将脚本从 head 移到 body 末尾（确保 DOM 已解析完成）
      const scriptMatch = result.match(/<script src="[^"]+"><\/script>/);
      if (scriptMatch) {
        const script = scriptMatch[0];
        result = result
          .replace(script, '')  // 从 head 中移除
          .replace('</body>', `  ${script}\n  </body>`);  // 添加到 body 末尾
      }

      return result;
    },
  }
}

export default defineConfig({
  plugins: [react(), fixFileProtocol()],
  // 使用相对路径，支持 file:// 协议
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
    // 禁用模块预加载，避免在 file:// 协议下的 CORS 问题
    modulePreload: false,
    rollupOptions: {
      output: {
        // 简化输出结构
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]',
        // 使用 IIFE 格式，避免 ES modules 在 file:// 协议下的 CORS 问题
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
