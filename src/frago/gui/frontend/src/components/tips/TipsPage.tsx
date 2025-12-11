import { Accordion, AccordionItem } from '../ui/Accordion';

export default function TipsPage() {
  return (
    <div className="page-scroll flex flex-col gap-4 h-full">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">欢迎使用 frago</h1>

      <Accordion>
        <AccordionItem title="认识 frago" defaultOpen>
          <p className="mb-3">
            你让 AI 提取 YouTube 字幕，它花 5
            分钟探索成功了。第二天同样的需求——它又从头来过，完全忘了昨天怎么做的。
          </p>
          <p className="mb-3">
            即使像 Claude Code
            这样强大的工具，面对每个人独特的任务需求时也显得笨拙：每次都要重新探索，每次都在烧
            token，10 次尝试里可能只有 5 次走对了路。
          </p>
          <p>
            frago 解决的就是这个问题：第一次探索，记录过程，固化成可复用的配方。下次同样的任务，直接调用，不再重复探索。AI
            足够聪明，但还不够「有经验」。frago 教它记住怎么做事。
          </p>
        </AccordionItem>

        <AccordionItem title="关键概念">
          <p className="mb-3">
            <strong className="text-[var(--text-primary)]">Recipe（配方）</strong>
            ：可复用的自动化脚本，定义了一系列浏览器操作。配方可以保存、分享、反复执行。
          </p>
          <p className="mb-3">
            <strong className="text-[var(--text-primary)]">Task（任务）</strong>
            ：一次配方执行的实例。每个任务有独立的运行状态、日志和结果。
          </p>
          <p>
            <strong className="text-[var(--text-primary)]">Session（会话）</strong>
            ：与 Chrome 浏览器的连接。一个会话可以执行多个任务，共享浏览器上下文（登录状态、cookies
            等）。
          </p>
        </AccordionItem>

        <AccordionItem title="用途与场景">
          <p className="mb-3">frago 适用于需要与网页交互的重复性工作：</p>
          <ul className="list-disc list-inside space-y-1">
            <li>从多个网站采集数据并整理成结构化格式</li>
            <li>自动填写表单、提交申请</li>
            <li>监控网页变化并触发通知</li>
            <li>执行 UI 测试，验证页面功能</li>
            <li>批量下载文件或图片</li>
          </ul>
        </AccordionItem>

        <AccordionItem title="GUI vs 命令行">
          <p className="mb-3">
            <strong className="text-[var(--text-primary)]">GUI 模式</strong>
            适合后台执行、批量管理任务。你可以同时监控多个任务的进度，查看历史记录，管理配方库。适合已经验证过的稳定配方。
          </p>
          <p>
            <strong className="text-[var(--text-primary)]">命令行模式</strong>
            适合开发调试、交互式执行。你可以实时看到每一步操作，在关键节点确认后再继续。适合新配方的编写和测试。
          </p>
        </AccordionItem>

        <AccordionItem title="快速开始">
          <ol className="list-decimal list-inside space-y-2">
            <li>
              确保 Chrome 已启动并开启调试模式（
              <code className="font-mono text-sm bg-[var(--bg-subtle)] px-1.5 py-0.5 rounded">
                --remote-debugging-port=9222
              </code>
              ）
            </li>
            <li>
              在 <strong className="text-[var(--text-primary)]">Recipes</strong>{' '}
              页面创建新配方或导入现有配方
            </li>
            <li>
              选择配方，点击运行，在{' '}
              <strong className="text-[var(--text-primary)]">Tasks</strong> 页面查看执行进度
            </li>
          </ol>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
