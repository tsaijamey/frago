/**
 * TimelineEventRow — Renders a single PA event in the timeline.
 *
 * Humanize rules (from spec):
 * - channel name 直接嵌入标题，不翻译
 * - prompt 提取 <instruction> 标签内容，fallback 到原文
 * - PA decision 用模板化标题，不暴露 action 类型给用户
 * - agent_exited 区分完成/异常
 */

import { formatRelativeTime, formatDuration } from './constants';
import type { TimelineEvent } from './useTimeline';

/** Extract <instruction> content from ingestion prompt, fallback to raw text */
function extractInstruction(prompt: string): string {
  const match = prompt.match(/<instruction>\s*([\s\S]*?)\s*<\/instruction>/);
  if (match) return match[1].trim();
  // No instruction tag — use raw prompt, skip <context> block if present
  const cleaned = prompt.replace(/<context>[\s\S]*?<\/context>\s*/g, '').trim();
  return cleaned || prompt;
}

/** Truncate text to maxLen, adding ellipsis */
function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '…';
}

interface EventDisplay {
  icon: string;
  iconClass: string;
  title: string;
  subtitle: string;
}

function getEventDisplay(event: TimelineEvent): EventDisplay {
  const d = event.data;

  switch (event.type) {
    case 'ingestion': {
      const channel = (d.channel as string) || '';
      const prompt = (d.prompt as string) || '';
      const instruction = extractInstruction(prompt);
      return {
        icon: '✉',
        iconClass: 'tl-icon--accent',
        title: `收到 ${channel} 消息`,
        subtitle: truncate(instruction, 80),
      };
    }

    case 'pa_decision': {
      const action = (d.action as string) || '';
      const details = (d.details as Record<string, unknown>) || {};
      const desc =
        (details.description as string) ||
        (details.recipe_name as string) ||
        (details.prompt as string) ||
        '';

      // Humanize action → title
      let title: string;
      switch (action) {
        case 'run':
          title = '分配任务给 Agent';
          break;
        case 'reply':
          title = '回复消息';
          break;
        case 'resume':
          title = '继续执行';
          break;
        case 'recipe':
          title = '执行配方';
          break;
        case 'update':
          title = '更新任务状态';
          break;
        default:
          title = action; // fallback — 未知 action 直接显示
      }

      return {
        icon: '⚡',
        iconClass: 'tl-icon--accent',
        title,
        subtitle: truncate(desc, 80),
      };
    }

    case 'agent_launched': {
      const desc = (d.description as string) || '';
      return {
        icon: '▸',
        iconClass: 'tl-icon--accent',
        title: 'Agent 开始执行',
        subtitle: desc,
      };
    }

    case 'agent_exited': {
      const dur = d.duration_seconds as number | undefined;
      const ok = d.has_completion as boolean | undefined;
      const durText = dur !== undefined ? `耗时 ${formatDuration(dur * 1000)}` : '';
      return {
        icon: ok ? '◼' : '✗',
        iconClass: ok ? 'tl-icon--accent' : 'tl-icon--error',
        title: ok ? 'Agent 执行完毕' : 'Agent 异常退出',
        subtitle: durText,
      };
    }

    case 'pa_reply': {
      const channel = (d.channel as string) || '';
      const text = (d.reply_text as string) || '';
      return {
        icon: '↩',
        iconClass: 'tl-icon--accent',
        title: `已回复 ${channel}`,
        subtitle: truncate(text, 80),
      };
    }

    default:
      return {
        icon: '•',
        iconClass: 'tl-icon--dim',
        title: event.type,
        subtitle: '',
      };
  }
}

export default function TimelineEventRow({ event }: { event: TimelineEvent }) {
  const display = getEventDisplay(event);

  return (
    <div className="tl-row tl-row--event">
      <span className="tl-ts">{formatRelativeTime(event.timestamp)}</span>
      <span className={`tl-icon ${display.iconClass}`}>{display.icon}</span>
      <span className="tl-content">
        <span className="tl-title">{display.title}</span>
        {display.subtitle && <span className="tl-subtitle">{display.subtitle}</span>}
      </span>
    </div>
  );
}
