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
 * | 右 | 面 | 真数据。旁路 AI 每轮在服务端填，切换会话打断不了它 |
 *
 * 中栏走 `minmax(0, …)`、三栏各自 `min-w-0`。这两条是页面不横向滚的地基——少任何一条，
 * 一条长命令就能把整个版面顶宽。
 */

import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { ChevronLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import SessionRail from './SessionRail';
import RecordStream from './RecordStream';
import ReportPanel from './ReportPanel';
import Composer from './Composer';
import SessionLaunchPanel from './SessionLaunchPanel';
import StopRunButton from './StopRunButton';
import DeleteSessionButton from './DeleteSessionButton';
import { useWorkbenchSessions } from '@/hooks/useWorkbenchSessions';
import { useWorkbenchRecords } from '@/hooks/useWorkbenchRecords';
import { useSessionLaunch } from '@/hooks/useSessionLaunch';
import { useReportWidth } from '@/hooks/useReportLayout';
import { usePageStore } from '@/stores/pageStore';

export default function SessionWorkbenchPage() {
  // 选中记在页面导航状态里，切去别的菜单再回来还停在那一场上。
  const selectedId = usePageStore((s) => s.workbenchSessionId);
  const setWorkbenchSessionId = usePageStore((s) => s.setWorkbenchSessionId);
  const { t } = useTranslation();
  const sessions = useWorkbenchSessions();
  // 右栏多宽由人拖出来，记在这个浏览器里；没拖过就用下面网格里写的默认列宽。
  const report = useReportWidth();
  const selected = sessions.sessions.find((s) => s.session_id === selectedId) ?? null;
  // 还在跑的会话让中栏自己活起来：文件一动服务端就推增量，轮询只是断连时的兜底。
  const {
    records,
    recordsSessionId,
    loading,
    loadingOlder,
    hasOlder,
    error,
    loadOlder,
    reload,
    awaitingAgent,
    outbound,
    deliveredAt,
    markSent,
    clearSent,
    settleSent,
  } = useWorkbenchRecords(selectedId, { live: selected?.status === 'running' });

  /**
   * 人从记录流里引过来的那段话，等着落进输入框。
   *
   * 编号用自增的次数而不是时间：同一段话连引两次，时间戳可能一模一样，输入区会以为
   * 是同一件事而把第二次吃掉。
   */
  const [quote, setQuote] = useState<{ text: string; at: number } | null>(null);
  const quoteSeq = useRef(0);
  // 换会话把没落地的引用收掉——那段话是从上一场的记录里圈的。
  useEffect(() => setQuote(null), [selectedId]);

  /**
   * 新建那一场从「点了创建」到「界面上真的有它」之间的那段路。
   *
   * 从前这段路上什么都没有：对话框一关，人要盯着一片空白等将近十秒。现在它有两个去处——
   * 左栏清单上方一行，中栏一块启动面板，两处说的是同一件事的同一档。
   *
   * 接过来那一刻先把中栏腾空（`setWorkbenchSessionId(null)`），启动面板才占得住位置；编号一到
   * 就切进那一场，但**人这中间自己挑了别的会话就不抢**——他已经改看别处了。
   */
  const { launch, begin, dismiss } = useSessionLaunch({
    sessions: sessions.sessions,
    reload: sessions.reload,
    onReady: (sid) => {
      if (usePageStore.getState().workbenchSessionId === null) setWorkbenchSessionId(sid);
    },
    recordsSessionId,
    recordCount: records.length,
  });

  // 中栏此刻该让给启动面板：正在起，而且人没有把中栏切到别的会话上去。
  const showLaunch = Boolean(launch) && (selectedId === null || selectedId === launch?.sessionId);

  return (
    <div className="grid h-full min-h-0 w-full flex-1 grid-cols-[232px_minmax(0,1fr)_var(--report-w,280px)] tablet:grid-cols-[232px_minmax(0,1fr)] phone:grid-cols-1 desktop:grid-cols-[302px_minmax(0,1fr)_var(--report-w,346px)]"
      style={report.width ? ({ '--report-w': `${report.width}px` } as CSSProperties) : undefined}
    >
      {/* 手机上一次只放得下一栏：没选会话时给清单，选了就整屏让给记录流。 */}
      <div className={`min-h-0 min-w-0 ${selectedId || showLaunch ? 'phone:hidden' : ''}`}>
        <SessionRail
          state={sessions}
          selectedId={selectedId}
          onSelect={setWorkbenchSessionId}
          launch={launch}
          onDismissLaunch={dismiss}
          onCreated={(pending, text) => {
            setWorkbenchSessionId(null);
            begin(pending, text);
          }}
        />
      </div>

      <div
        className={`flex min-h-0 min-w-0 flex-col bg-bg-primary ${
          selectedId || showLaunch ? '' : 'phone:hidden'
        }`}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-border-color px-5 py-2.5">
          {selectedId ? (
            <button
              type="button"
              onClick={() => setWorkbenchSessionId(null)}
              className="hidden shrink-0 text-text-muted hover:text-text-primary phone:block"
              aria-label={t('workbench.page.backToList')}
            >
              <ChevronLeft size={16} />
            </button>
          ) : null}
          <h1 className="min-w-0 truncate text-[14px] font-semibold text-text-primary">
            {selected
              ? selected.title
              : showLaunch
                ? t('workbench.launch.railTitle')
                : t('workbench.page.title')}
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
          {/* 用量月历的入口搬去了左栏底部：那里是「我还剩多少」的位置，与额度条并排。
              它本来就不是会话页专属的东西，挂在这一页的标题栏上只是它当初落脚的地方。 */}
          {/* 这一行的最右留给「关闭 tmux 会话」：人认为这一场暂时谈完了，按它把 tmux 里那具
              还占着几百兆的壳收掉。会话本身不动——记录还在，还能翻。只在清单说这一场此刻
              开在 tmux 里时出现：tmux 里没有了还挂着按钮，按下去只得到一句「没在跑」。 */}
          {selected?.in_tmux ? (
            <StopRunButton session={selected} onStopped={() => void sessions.reload()} />
          ) : null}
          {/* 三家都摆。删法三家不一样（Claude Code 删文件，另两家借引擎自己的命令），
              那层差别由弹窗里的话交代，不靠"有没有这个按钮"来暗示。删成之后中栏要退回
              清单态——再停在那一场上，记录流对着一个已经不存在的编号接着问。 */}
          {selected ? (
            <DeleteSessionButton
              session={selected}
              onDeleted={() => {
                setWorkbenchSessionId(null);
                void sessions.reload();
              }}
            />
          ) : null}
        </header>

        <div className="min-h-0 flex-1">
          {showLaunch && launch ? (
            <SessionLaunchPanel launch={launch} onDismiss={dismiss} />
          ) : (
            <RecordStream
              sessionId={selectedId}
              records={records}
              loading={loading}
              loadingOlder={loadingOlder}
              hasOlder={hasOlder}
              error={error}
              onLoadOlder={loadOlder}
              awaitingAgent={awaitingAgent}
              onQuote={(text) => setQuote({ text, at: (quoteSeq.current += 1) })}
            />
          )}
        </div>

        {/* 分两刻做两件事。
            **出门那一刻**举起"在等 agent 开口"、给那句话开一个信封并转入快节拍
            （markSent）——发送这条接口要等整整一轮才回来，挂在回来那一刻等于整轮之内
            中栏一动不动。
            **回来那一刻**把自己刚说的那句拉进流里（reload），并让左栏状态跟着从"已完成"
            转成"在跑"、升到顶部。
            信封由记录流照着真记录判档：还找不到它就是"已发送"，找到的是一张还在队列上的
            插话卡就是"已入队列"。输入区只管画，不自己猜。 */}
        {/* CoreAgent 那一家没有输入区：它每次运行都是一个跑完就退出的进程，接不上话。
            摆一个输入框在那儿等于请人打一段字进去，而那一句必定被服务端拒掉——不如
            当场说清这场只能回看。 */}
        {selected?.family === 'coreagent' ? (
          <div className="sw-readonly-note">{t('workbench.composer.readOnlyCoreagent')}</div>
        ) : showLaunch ? null : (
        <Composer
          sessionId={selectedId}
          family={selected?.family ?? null}
          // 上沿那条线上的小人跟着这一场走：会话在跑、或者刚发出去还没等到 agent 开口，
          // 他就在线上踱步；两样都落下他才坐下。
          running={selected?.status === 'running' || awaitingAgent}
          onSendStart={markSent}
          onSendFailed={clearSent}
          deliveredAt={deliveredAt}
          outbound={outbound}
          quote={quote}
          onSent={(outboundId) => {
            void reload();
            void sessions.reload();
            // 接口回来了就说明这一轮已经说完，那句话必定在会话里了：信封该收，
            // 不必等记录流认出它长什么样。
            settleSent(outboundId);
          }}
        />
        )}
      </div>

      <div className="min-h-0 min-w-0 tablet:hidden phone:hidden">
        <ReportPanel
          sessionId={selectedId}
          width={report.width}
          onWidthChange={report.setWidth}
        />
      </div>
    </div>
  );
}
