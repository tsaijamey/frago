/**
 * 一枚员工语境引用卡片：记录流里那句话带入的 `<frago-employee>` 业务语境块，与 `SkillQuote` 同构。
 *
 * 一整枚圆角签：公文包图标加 `@编号` 与岗位名称，淡品牌色底加一圈同色细边，整枚代表这句话
 * 挂载了该员工的业务语境；内部上万字的职责、数据底账与账本由 agent 自己读，消息里一个字都不摆。
 */

import { Briefcase } from 'lucide-react';
import type { EmployeeBlockItem } from '@/utils/employeeBlocks';
import { truncateChars } from '@/utils/skillBlocks';
import { SKILL_QUOTE_DESC_CHARS } from './SkillQuote';

export interface EmployeeQuoteProps {
  id: string;
  title?: string | null;
  kernel?: string | null;
}

export function EmployeeQuote({ id, title, kernel }: EmployeeQuoteProps) {
  const desc = title ? truncateChars(title, SKILL_QUOTE_DESC_CHARS) : '';
  const tooltip = [title ? `${title} (@${id})` : `@${id}`, kernel ? `[${kernel}]` : '']
    .filter(Boolean)
    .join(' ');
  return (
    <span
      data-testid="employee-quote"
      data-employee={id}
      title={tooltip}
      className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-border-accent bg-accent-primary-10 py-[2px] pl-2 pr-2 text-[12px]"
    >
      <Briefcase size={12} className="shrink-0 text-accent-primary" />
      <span className="shrink-0 font-mono text-text-primary">@{id}</span>
      {desc ? <span className="min-w-0 truncate text-text-muted">{desc}</span> : null}
    </span>
  );
}

/** 记录流里那句话引用的几个员工语境块，一行排开。没有就什么都不画。 */
export function EmployeeQuotes({ employees }: { employees: EmployeeBlockItem[] }) {
  if (!employees.length) return null;
  return (
    <div data-testid="employee-quotes" className="mb-1.5 flex flex-wrap gap-1.5">
      {employees.map((emp, idx) => (
        <EmployeeQuote
          key={`${emp.id}-${idx}`}
          id={emp.id}
          title={emp.title}
          kernel={emp.kernel}
        />
      ))}
    </div>
  );
}
