/**
 * About Settings 组件
 * 显示 Frago 版本信息和技术栈
 */

export default function AboutSettings() {
  return (
    <div className="card">
      <h2 className="text-lg font-semibold text-[var(--accent-primary)] mb-4">
        关于
      </h2>

      <div className="space-y-4 text-sm text-[var(--text-secondary)]">
        <div>
          <h3 className="font-medium text-[var(--text-primary)] mb-2">
            Frago
          </h3>
          <p className="text-[var(--text-muted)]">
            AI 驱动的多运行时自动化框架
          </p>
        </div>

        <div className="border-t border-[var(--border-color)] pt-4">
          <h3 className="font-medium text-[var(--text-primary)] mb-2">
            技术栈
          </h3>
          <ul className="space-y-1 text-[var(--text-muted)]">
            <li>• 前端：React + TypeScript + TailwindCSS + Vite</li>
            <li>• 后端：Python + pywebview + Pydantic</li>
            <li>• 自动化：Chrome CDP + Websocket</li>
          </ul>
        </div>

        <div className="border-t border-[var(--border-color)] pt-4">
          <p className="text-[var(--text-muted)]">
            © 2024 Frago. All rights reserved.
          </p>
        </div>
      </div>
    </div>
  );
}
