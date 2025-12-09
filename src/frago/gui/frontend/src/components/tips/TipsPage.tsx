export default function TipsPage() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">
        欢迎使用 Frago
      </h1>

      <div className="card">
        <h2 className="font-medium mb-2 text-[var(--accent-primary)]">
          快速开始
        </h2>
        <ul className="list-disc list-inside text-[var(--text-secondary)] space-y-1">
          <li>使用 <code className="font-mono text-sm bg-[var(--bg-subtle)] px-1.5 py-0.5 rounded">frago run</code> 执行自动化任务</li>
          <li>在 Tasks 页面查看任务执行历史</li>
          <li>在 Recipes 页面管理可复用的配方脚本</li>
          <li>在 Skills 页面查看 Claude Code 技能</li>
        </ul>
      </div>

      <div className="card">
        <h2 className="font-medium mb-2 text-[var(--accent-primary)]">
          常用命令
        </h2>
        <div className="space-y-2 text-[var(--text-secondary)]">
          <div className="flex gap-4">
            <code className="font-mono text-sm w-40 flex-shrink-0">frago recipe</code>
            <span>管理配方脚本</span>
          </div>
          <div className="flex gap-4">
            <code className="font-mono text-sm w-40 flex-shrink-0">frago chrome</code>
            <span>连接到 Chrome 浏览器</span>
          </div>
          <div className="flex gap-4">
            <code className="font-mono text-sm w-40 flex-shrink-0">frago gui</code>
            <span>启动图形界面</span>
          </div>
        </div>
      </div>

      <div className="card">
        <h2 className="font-medium mb-2 text-[var(--accent-primary)]">
          键盘快捷键
        </h2>
        <div className="space-y-2 text-[var(--text-secondary)]">
          <div className="flex gap-4">
            <kbd className="font-mono text-xs bg-[var(--bg-subtle)] px-2 py-1 rounded border border-[var(--border-color)]">Ctrl+1-5</kbd>
            <span>切换到对应页面</span>
          </div>
          <div className="flex gap-4">
            <kbd className="font-mono text-xs bg-[var(--bg-subtle)] px-2 py-1 rounded border border-[var(--border-color)]">Ctrl+R</kbd>
            <span>刷新当前页面数据</span>
          </div>
          <div className="flex gap-4">
            <kbd className="font-mono text-xs bg-[var(--bg-subtle)] px-2 py-1 rounded border border-[var(--border-color)]">Esc</kbd>
            <span>返回列表页面</span>
          </div>
        </div>
      </div>
    </div>
  );
}
