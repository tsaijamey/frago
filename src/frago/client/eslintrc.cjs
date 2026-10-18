/**
 * ESLint 8 的 eslintrc 格式配置。
 *
 * 文件名不以点开头，因为仓库根 `.gitignore` 有一条 `.*`，`.eslintrc.cjs` 会被静默
 * 忽略、永远进不了版本库；lint 脚本显式用 `--config` 指向这里。
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parser: '@typescript-eslint/parser',
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
  plugins: ['@typescript-eslint', 'react-hooks', 'react-refresh'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', 'node_modules', 'eslintrc.cjs'],
  rules: {
    // 这个代码库里大量回调签名用 `_name` 标记「接口要求、这里不用」。那是刻意的写法，
    // 不是漏掉的清理；按前导下划线放行，别把既有约定当成错误。
    '@typescript-eslint/no-unused-vars': [
      'error',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
    // 与平台/第三方边界打交道的地方已有大量显式 any；这条规则在这套代码里从未生效过。
    '@typescript-eslint/no-explicit-any': 'off',
    // 页面文件常同时导出组件与判读函数；这不会改变运行行为，也不在本轮修复范围。
    'react-refresh/only-export-components': 'off',
  },
};
