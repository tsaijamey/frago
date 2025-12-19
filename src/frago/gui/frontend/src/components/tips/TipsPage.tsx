import { useState } from 'react';
import { Accordion, AccordionItem } from '../ui/Accordion';
import { openTutorial } from '@/api/pywebview';
import { ExternalLink, Loader2 } from 'lucide-react';

interface TutorialButtonProps {
  tutorialId: string;
  label?: string;
  anchor?: string;
}

function TutorialButton({ tutorialId, label = '查看详细教程', anchor = '' }: TutorialButtonProps) {
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    setLoading(true);
    try {
      const result = await openTutorial(tutorialId, 'auto', anchor);
      if (result.status === 'error') {
        console.error('Failed to open tutorial:', result.error);
      }
    } catch (error) {
      console.error('Failed to open tutorial:', error);
    } finally {
      // 延迟重置 loading 状态，给用户视觉反馈
      setTimeout(() => setLoading(false), 500);
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium
                 text-[var(--accent-primary)] bg-[var(--accent-primary)]/10
                 hover:bg-[var(--accent-primary)]/20 rounded-md transition-colors
                 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {loading ? (
        <Loader2 size={14} className="animate-spin" />
      ) : (
        <ExternalLink size={14} />
      )}
      {label}
    </button>
  );
}

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
          <TutorialButton tutorialId="intro" />
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
          <TutorialButton tutorialId="intro" label="了解更多概念" anchor="concepts" />
        </AccordionItem>

        <AccordionItem title="功能操作指南">
          <p className="mb-3">frago 的核心操作流程：</p>
          <ol className="list-decimal list-inside space-y-1 mb-3">
            <li>启动 Chrome 调试模式</li>
            <li>创建或选择配方</li>
            <li>运行配方，监控任务状态</li>
            <li>查看结果，优化配方</li>
          </ol>
          <TutorialButton tutorialId="guide" />
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
          <TutorialButton tutorialId="intro" label="查看应用场景" anchor="use-cases" />
          <TutorialButton tutorialId="best-practices" label="最佳实践指南" />
        </AccordionItem>

        <AccordionItem title="视频教程">
          <p className="mb-3">
            通过视频教程快速上手 frago，包含入门指南、进阶技巧和实战案例。
          </p>
          <TutorialButton tutorialId="videos" label="浏览视频教程" />
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
          <TutorialButton tutorialId="guide" label="查看完整指南" />
        </AccordionItem>
      </Accordion>
    </div>
  );
}
