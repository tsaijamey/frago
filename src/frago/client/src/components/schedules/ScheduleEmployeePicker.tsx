import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Search } from 'lucide-react';
import type { EmployeeItem } from '@/types/api';
import { empColorToken, employeeInitials } from './scheduleMeta';

export type EmpPickerFilter = 'all' | 'claude' | 'nonclaude' | 'has_domains';

interface ScheduleEmployeePickerProps {
  employees: EmployeeItem[];
  selectedId: string;
  onSelect: (emp: EmployeeItem) => void;
}

export default function ScheduleEmployeePicker({
  employees,
  selectedId,
  onSelect,
}: ScheduleEmployeePickerProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<EmpPickerFilter>('all');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return employees.filter((emp) => {
      const kernel = (emp.agent_kernel ?? 'claude').toLowerCase();
      if (filter === 'claude' && kernel !== 'claude') return false;
      if (filter === 'nonclaude' && kernel === 'claude') return false;
      if (filter === 'has_domains' && (!emp.knowledge_domains || emp.knowledge_domains.length === 0)) {
        return false;
      }
      if (!q) return true;
      return [
        emp.member_post_id,
        emp.title ?? '',
        emp.description ?? '',
        emp.work_scope ?? '',
        ...(emp.recipes ?? []),
        ...(emp.knowledge_domains ?? []),
      ]
        .join(' ')
        .toLowerCase()
        .includes(q);
    });
  }, [employees, query, filter]);

  const filterChips: { key: EmpPickerFilter; label: string }[] = [
    { key: 'all', label: t('schedules.picker.all') },
    { key: 'claude', label: t('schedules.picker.claude') },
    { key: 'nonclaude', label: t('schedules.picker.nonclaude') },
    { key: 'has_domains', label: t('schedules.picker.hasDomains') },
  ];

  return (
    <div className="sc-picker" data-testid="sc-emp-picker">
      <div className="sc-picker-bar">
        <div className="sc-picker-search">
          <Search size={13} aria-hidden="true" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('schedules.picker.searchPlaceholder')}
            aria-label={t('schedules.picker.searchPlaceholder')}
            data-testid="sc-emp-search"
          />
        </div>
        {filterChips.map((chip) => (
          <button
            key={chip.key}
            type="button"
            className={`sc-fchip ${filter === chip.key ? 'on' : ''}`}
            onClick={() => setFilter(chip.key)}
            aria-pressed={filter === chip.key}
            data-testid={`sc-emp-filter-${chip.key}`}
          >
            {chip.label}
          </button>
        ))}
      </div>

      <div className="sc-picker-list">
        {filtered.length === 0 ? (
          <div className="td-hint py-4 text-center">{t('schedules.picker.empty')}</div>
        ) : (
          filtered.map((emp) => {
            const color = empColorToken(emp.member_post_id, emp.color);
            const active = emp.member_post_id === selectedId;
            return (
              <button
                key={emp.member_post_id}
                type="button"
                className={`sc-emp-row ${active ? 'on' : ''}`}
                onClick={() => onSelect(emp)}
                data-testid={`sc-emp-row-${emp.member_post_id}`}
              >
                <span className="sc-emp-av sm" data-emp-color={color}>
                  {employeeInitials(emp.member_post_id, emp.title)}
                </span>
                <div className="sc-emp-row-main">
                  <div className="sc-emp-row-line1">
                    <span className="sc-chip emp" data-emp-color={color}>
                      @{emp.member_post_id}
                    </span>
                    <strong className="text-[12.5px] text-[var(--text-primary)]">
                      {emp.title || emp.member_post_id}
                    </strong>
                    <span className="sc-chip">{emp.agent_kernel || 'claude'}</span>
                  </div>
                  {(emp.description || emp.work_scope) && (
                    <div className="sc-emp-row-line2 truncate">
                      {emp.description || emp.work_scope}
                    </div>
                  )}
                </div>
                <div className="sc-emp-row-right">
                  {emp.recipes && emp.recipes.length > 0 && (
                    <span className="sc-chip">{emp.recipes[0]}</span>
                  )}
                  {emp.knowledge_domains && emp.knowledge_domains.length > 0 && (
                    <span className="sc-chip">{emp.knowledge_domains.length} domains</span>
                  )}
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
