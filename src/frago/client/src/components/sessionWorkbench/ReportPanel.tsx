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
import { useTranslation } from 'react-i18next';
import { FlaskConical } from 'lucide-react';

/**
 * 槽位标题的写法。四个槽位共用一套：11px、次级灰、字重加一档、字距略开。
 *
 * 这一栏是四段并置的短文，彼此之间没有从属关系。标题要能一眼与正文分开，但不该比正文
 * 更抢眼——所以走的是"更小更淡但更紧"，而不是"更大更重"。
 */
const SLOT_LABEL = 'text-[11px] font-medium tracking-wide text-text-muted';

/**
 * 覆盖型槽位：高度固定，长文槽位高一档。固定不等于小。
 *
 * **不再是一张带边框的卡。** 四个槽位各套一圈边、外面还有一层栏底，一眼看过去是四个
 * 方框而不是四段话；而这一栏的内容本来就是要被读的。现在改成发丝线分段：段与段之间
 * 一条线，最后一段不带线。
 */
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
    <section className="border-b border-border-color px-3 py-3 last:border-b-0">
      <header className={`mb-1.5 ${SLOT_LABEL}`}>{label}</header>
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
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? items : items.slice(0, 3);
  const hidden = items.length - shown.length;
  return (
    <section className="border-b border-border-color px-3 py-3 last:border-b-0">
      <header className={`mb-1.5 flex items-center gap-2 ${SLOT_LABEL}`}>
        <span>{label}</span>
        <span className="font-mono opacity-70">
          {t('workbench.report.itemCount', { n: items.length })}
        </span>
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
          {t('workbench.report.expandOlder', { n: hidden })}
        </button>
      ) : null}
    </section>
  );
}

// 示意数据的词条名。这些字不来自任何会话，取字在渲染时做——摆在模块级会把它锁死在
// 开局那一种语言上。
const DEMO_HAPPENED_KEYS = [
  'workbench.report.demoHappened1',
  'workbench.report.demoHappened2',
  'workbench.report.demoHappened3',
  'workbench.report.demoHappened4',
  'workbench.report.demoHappened5',
];

export default function ReportPanel() {
  const { t } = useTranslation();
  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-l border-border-color bg-bg-secondary">
      {/* 「尚未接入」是一句提醒，不是一次告警。
          从前这条横带铺满品牌绿，一进会话页最先跳进眼里的就是它——而它说的事既不紧急、
          也没人能立刻做点什么。现在按提醒的分量给：中性底，只有那颗烧瓶图标带一点绿，
          够认出"这一栏跟别处不一样"就行。 */}
      <div className="flex shrink-0 items-center gap-2 border-b border-border-color bg-bg-subtle px-3 py-2 text-[11px] text-text-secondary">
        <FlaskConical size={13} className="shrink-0 text-accent-primary" />
        <span>{t('workbench.report.notWired')}</span>
      </div>

      {/* 滚动容器的内距契约：分段自带上下内距，容器只在最底下补一段留白，
          最后一段滚到底时不会被硬切在边框上。 */}
      <div className="min-h-0 flex-1 overflow-y-auto pb-6">
        <CoverSlot label={t('workbench.report.slotNow')} value={t('workbench.report.demoNow')} />
        <CoverSlot
          label={t('workbench.report.slotDecision')}
          value={t('workbench.report.demoDecision')}
          tall
        />
        <CoverSlot
          label={t('workbench.report.slotOutput')}
          value={t('workbench.report.demoOutput')}
        />
        <GrowSlot
          label={t('workbench.report.slotHappened')}
          items={DEMO_HAPPENED_KEYS.map((key) => t(key))}
        />
      </div>

      <div className="shrink-0 border-t border-border-color px-3 py-2 text-[11px] leading-[1.6] text-text-muted">
        {t('workbench.report.footer')}
      </div>
    </aside>
  );
}
