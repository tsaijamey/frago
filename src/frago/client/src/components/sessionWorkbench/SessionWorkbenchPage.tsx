/**
 * SessionWorkbenchPage — 会话页的页面壳，三栏布局。
 *
 * 它是 webUI 里**唯一**的会话入口。旧的单栏会话页已经下线，那一页上还值钱的五件事
 * （搜索、时间范围、新建会话、复制恢复命令、用量月历）整个搬了进来，其余的按来源筛、
 * 重新扫描、PA 列表、未读徽章、后台保活一并去掉。导航上这一项叫「会话」，
 * `workbench` 只是内部代号，界面上不出现。
 *
 * | 栏 | 本质 | 本次做到哪 |
 * |---|---|---|
 * | 左 | 索引 | 真数据。两家会话都出现 |
 * | 中 | 流 | 真数据。十五种形态无损呈现 |
 * | 右 | 面 | 示意数据。速记员不在本次范围 |
 *
 * 中栏走 `minmax(0, …)`、三栏各自 `min-w-0`。这两条是页面不横向滚的地基——少任何一条，
 * 一条长命令就能把整个版面顶宽。
 */

import { useState } from 'react';
import { CalendarDays, ChevronLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import SessionRail from './SessionRail';
import RecordStream from './RecordStream';
import ReportPanel from './ReportPanel';
import Composer from './Composer';
import TokenCalendarModal from './TokenCalendarModal';
import { useWorkbenchSessions } from '@/hooks/useWorkbenchSessions';
import { useWorkbenchRecords } from '@/hooks/useWorkbenchRecords';

export default function SessionWorkbenchPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const { t } = useTranslation();
  const sessions = useWorkbenchSessions();
  const selected = sessions.sessions.find((s) => s.session_id === selectedId) ?? null;
  // 还在跑的会话让中栏自己活起来：文件一动服务端就推增量，轮询只是断连时的兜底。
  const {
    records,
    loading,
    loadingOlder,
    hasOlder,
    error,
    loadOlder,
    reload,
    awaitingAgent,
    deliveredAt,
    markSent,
    clearSent,
  } = useWorkbenchRecords(selectedId, { live: selected?.status === 'running' });

  return (
    <div className="grid h-full min-h-0 w-full flex-1 grid-cols-[232px_minmax(0,1fr)_280px] tablet:grid-cols-[232px_minmax(0,1fr)] phone:grid-cols-1 desktop:grid-cols-[302px_minmax(0,1fr)_346px]">
      {/* 手机上一次只放得下一栏：没选会话时给清单，选了就整屏让给记录流。 */}
      <div className={`min-h-0 min-w-0 ${selectedId ? 'phone:hidden' : ''}`}>
        <SessionRail state={sessions} selectedId={selectedId} onSelect={setSelectedId} />
      </div>

      <div
        className={`flex min-h-0 min-w-0 flex-col bg-bg-primary ${
          selectedId ? '' : 'phone:hidden'
        }`}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-border-color px-5 py-2.5">
          {selectedId ? (
            <button
              type="button"
              onClick={() => setSelectedId(null)}
              className="hidden shrink-0 text-text-muted hover:text-text-primary phone:block"
              aria-label={t('workbench.page.backToList')}
            >
              <ChevronLeft size={16} />
            </button>
          ) : null}
          <h1 className="min-w-0 truncate text-[14px] font-semibold text-text-primary">
            {selected ? selected.title : t('workbench.page.title')}
          </h1>
          {selected ? (
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-text-muted">
              {selected.directory}
            </span>
          ) : (
            <span className="min-w-0 flex-1 truncate text-[12px] text-text-muted">
              {t('workbench.page.subtitle')}
            </span>
          )}
          {/* 用量是跨全部会话的一件事，所以入口在顶部，而不是挂在某一场会话上。 */}
          <button
            type="button"
            onClick={() => setCalendarOpen(true)}
            title={t('tokenCalendar.open')}
            className="flex h-7 shrink-0 items-center gap-1.5 rounded-[6px] px-2 text-[12px] text-text-secondary transition-colors duration-200 hover:bg-bg-hover hover:text-text-primary"
          >
            <CalendarDays size={14} strokeWidth={1.5} />
            <span className="phone:hidden">{t('tokenCalendar.open')}</span>
          </button>
        </header>

        {calendarOpen ? <TokenCalendarModal t={t} onClose={() => setCalendarOpen(false)} /> : null}

        <div className="min-h-0 flex-1">
          <RecordStream
            sessionId={selectedId}
            records={records}
            loading={loading}
            loadingOlder={loadingOlder}
            hasOlder={hasOlder}
            error={error}
            onLoadOlder={loadOlder}
            awaitingAgent={awaitingAgent}
          />
        </div>

        {/* 分两刻做两件事。
            **出门那一刻**举起"在等 agent 开口"并转入快节拍（markSent）——发送这条接口
            要等整整一轮才回来，挂在回来那一刻等于整轮之内中栏一动不动。
            **回来那一刻**把自己刚说的那句拉进流里（reload），并让左栏状态跟着从"已完成"
            转成"在跑"、升到顶部。 */}
        <Composer
          sessionId={selectedId}
          family={selected?.family ?? null}
          onSendStart={markSent}
          onSendFailed={clearSent}
          deliveredAt={deliveredAt}
          onSent={() => {
            void reload();
            void sessions.reload();
          }}
        />
      </div>

      <div className="min-h-0 min-w-0 tablet:hidden phone:hidden">
        <ReportPanel />
      </div>
    </div>
  );
}
