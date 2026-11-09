/**
 * EmployeeQuote — 一枚点名的员工岗位引用（基于 DirectiveQuote 共享组件）。
 *
 * 与 SkillQuote 同属指令引用签体系（复用 DirectiveQuote）：
 * - 输入框上方：敲 `@`（或点选员工）选定的员工，带一个叉可去掉；
 * - 记录流气泡顶部：从 `<frago-employee>` 标签里认回岗位编号、名称与内核，只读展示。
 */

import { useTranslation } from 'react-i18next';
import type { EmployeeBlockItem } from '@/utils/employeeBlocks';
import DirectiveQuote from './DirectiveQuote';

export interface EmployeeQuoteProps {
  id: string;
  title?: string | null;
  kernel?: string | null;
  description?: string | null;
  onRemove?: () => void;
}

export function EmployeeQuote({ id, title, kernel, description, onRemove }: EmployeeQuoteProps) {
  const { t } = useTranslation();
  return (
    <DirectiveQuote
      prefix="@"
      name={id}
      title={title}
      badge={kernel}
      description={description}
      variant="accent"
      testId="employee-quote"
      dataAttrKey="data-employee"
      removeTestId="employee-quote-remove"
      removeAriaLabel={t('workbench.employees.remove', { name: id })}
      onRemove={onRemove}
    />
  );
}

export function EmployeeQuotes({ employees }: { employees: EmployeeBlockItem[] }) {
  if (!employees.length) return null;
  return (
    <div data-testid="employee-quotes" className="mb-1.5 flex flex-wrap gap-1.5">
      {employees.map((emp, i) => (
        <EmployeeQuote
          key={`${emp.id}-${i}`}
          id={emp.id}
          title={emp.title}
          kernel={emp.kernel}
        />
      ))}
    </div>
  );
}

export default EmployeeQuote;
