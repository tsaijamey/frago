/**
 * ReportPanel — 右栏。**本次是示意数据**，界面上明写「速记员尚未接入」。
 *
 * 速记员（把会话实时填进这些槽位的那个模型）不在本次范围：填槽质量要先有真数据才能验，
 * 模型选型与静默窗口都定不了。所以这里摆的是槽位的形状，不是真值。
 *
 * 槽位分两型：
 *
 * - **覆盖型** 高度固定，新值把旧值盖掉。人的视线不用重新找位置。
 * - **增长型** 随内容长，默认只露最新三条，展开按钮写「展开更早的 N 条」——N 是已经
 *   发生的绝对数，没有分母。
 *
 * 全域禁令在这一栏同样成立：没有百分比、没有 X 比 Y 计数、没有进度条、没有预计剩余
 * 时间、没有还没发生的步骤名。允许出现的量只有已发生的绝对数。
 */

import { useState } from 'react';
import { FlaskConical } from 'lucide-react';

/** 强调位与左栏、中栏共用同一份品牌绿，走主题变量，NEVER 写死色值。 */
const ACCENT_TEXT = 'text-accent-primary';
const ACCENT_BG = 'bg-accent-primary-10';

/** 覆盖型槽位：高度固定，长文槽位高一档。固定不等于小。 */
function CoverSlot({
  label,
  value,
  tall = false,
}: {
  label: string;
  value: string;
  tall?: boolean;
}) {
  return (
    <section className="rounded-[10px] border border-border-color bg-bg-card p-3">
      <header className="mb-1.5 text-[12px] text-text-muted">{label}</header>
      <div
        className={`overflow-hidden text-[13px] leading-[1.72] text-text-primary ${
          tall ? 'h-[112px]' : 'h-[76px]'
        }`}
      >
        {value}
      </div>
    </section>
  );
}

/** 增长型槽位：只追加不覆盖，默认露最新三条。 */
function GrowSlot({ label, items }: { label: string; items: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? items : items.slice(0, 3);
  const hidden = items.length - shown.length;
  return (
    <section className="rounded-[10px] border border-border-color bg-bg-card p-3">
      <header className="mb-1.5 flex items-center gap-2 text-[12px] text-text-muted">
        <span>{label}</span>
        <span className="font-mono">{items.length} 条</span>
      </header>
      <ul className="space-y-1.5">
        {shown.map((item, i) => (
          <li key={i} className="text-[13px] leading-[1.72] text-text-secondary">
            {item}
          </li>
        ))}
      </ul>
      {hidden > 0 ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-2 text-[11px] text-text-muted hover:text-text-primary"
        >
          展开更早的 {hidden} 条
        </button>
      ) : null}
    </section>
  );
}

// 示意数据。这些字是写死的，不来自任何会话。
const DEMO_NOW = '正在把两家的会话记录归一成同一种形状，中栏已经能逐条铺开';
const DEMO_DECISION =
  '左栏的时间范围默认不限，一千多场一次铺开。要不要给它一个更窄的默认值，等看过几天使用情况再定。';
const DEMO_OUTPUT = '旧会话页上还值钱的五件事整个搬进了这一页，剩下的随页面一起下线';
const DEMO_HAPPENED = [
  '中栏接上了真接口，十五种形态各有各的样式',
  '报错卡去掉了取原文入口，服务端那一道也还在',
  '左栏把两家的会话合并成一份清单',
  '统一记录类型与两家翻译层落在核心数据层',
  '会话在导航上只剩一个入口',
];

export default function ReportPanel() {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-l border-border-color bg-bg-secondary">
      <div
        className={`flex shrink-0 items-center gap-2 border-b border-border-color px-3 py-2.5 text-[12px] ${ACCENT_BG} ${ACCENT_TEXT}`}
      >
        <FlaskConical size={13} />
        <span>速记员尚未接入，下面是示意数据</span>
      </div>

      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3 py-3">
        <CoverSlot label="此刻在做什么" value={DEMO_NOW} />
        <CoverSlot label="需要你决策" value={DEMO_DECISION} tall />
        <CoverSlot label="最近一次产出" value={DEMO_OUTPUT} />
        <GrowSlot label="已经发生的事" items={DEMO_HAPPENED} />
      </div>

      <div className="shrink-0 border-t border-border-color px-3 py-2 text-[11px] text-text-muted">
        槽位由速记员填写。接入之前，这里的字不来自任何一场会话。
      </div>
    </aside>
  );
}
