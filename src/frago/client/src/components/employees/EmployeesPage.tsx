/**
 * 员工页 —— 这台机器上有哪些岗位，点一张卡片就能起一场带着他业务语境的会话。
 *
 * ## 页面只有一层：卡片网格
 *
 * 每张卡片表面只放四样东西：缩写、名字、一行职责、右边的编辑按钮。岗位说明与领地底账在
 * 编辑弹窗里。原型（`#teams` 的 minimal card）定下来的就是这个密度：卡片是**入口**，不是
 * 档案柜。
 *
 * ## 整卡点下去是起会话，不是进详情
 *
 * 这一页的存在理由就是「点一下就开始干活」。看详情是次要动作，所以它退到右边那颗铅笔上
 * ——两个动作各占一处，点错哪一处都还看得见另一处。
 *
 * ## 起完会话之后
 *
 * 弹窗把编号等到了才回调（要认领的那两家由它自己等），所以这里拿到的编号一定是真的。切到
 * 会话页并选中那一场，记录流由会话页自己拉——**NEVER 在这一页另起一套拉记录的路径**：同一
 * 场会话在两个地方各拉一份，两边看到的进度迟早不一样。
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Briefcase, Loader2, Pencil, Plus, RefreshCw } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import EmptyState from '@/components/ui/EmptyState';
import { usePageStore } from '@/stores/pageStore';
import { useEmployeeList, type EmployeePost } from '@/hooks/useEmployees';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import LaunchEmployeeDialog from './LaunchEmployeeDialog';
import EmployeeDetailDialog from './EmployeeDetailDialog';
import { employeeInitials, employeeSummary, employeeSummaryParts, resolveEmployeeColor } from './employeeMeta';

/** 这一页的数据是本机磁盘上的编制，变得不快。半分钟一次够用，切回来时另有一次。 */
const REFRESH_MS = 30_000;

export default function EmployeesPage() {
  const { t } = useTranslation();
  const launchWorkbenchSession = usePageStore((s) => s.launchWorkbenchSession);

  const { employees, loading, error, reload } = useEmployeeList(true);
  useAutoRefresh(reload, { intervalMs: REFRESH_MS });

  const [launchFor, setLaunchFor] = useState<EmployeePost | null>(null);
  const [detailFor, setDetailFor] = useState<EmployeePost | null>(null);
  const [creating, setCreating] = useState(false);

  const cards = employees;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title={t('employees.page.title')}
        meta={loading && !cards.length ? undefined : t('employees.page.count', { n: cards.length })}
        secondary={
          <button
            type="button"
            className="page-header-btn page-header-btn--icon"
            onClick={reload}
            title={t('common.refresh')}
            aria-label={t('common.refresh')}
          >
            <RefreshCw size={14} strokeWidth={1.5} />
          </button>
        }
        primary={{
          label: t('employees.page.new'),
          icon: <Plus size={14} strokeWidth={1.5} />,
          onClick: () => setCreating(true),
        }}
      />

      {error ? (
        <div className="mx-5 mt-3 break-words rounded-[8px] bg-accent-error-10 px-3 py-2 text-[12px] text-accent-error">
          {t('employees.page.loadFailed', { reason: error })}
        </div>
      ) : null}

      <div className="page-scroll">
        {loading && !cards.length && !error ? (
          <p className="flex items-center gap-2 px-5 py-4 text-[13px] text-text-muted">
            <Loader2 size={14} className="cs-spin" />
            {t('common.loading')}
          </p>
        ) : !cards.length && !error ? (
          <EmptyState
            Icon={Briefcase}
            title={t('employees.page.empty')}
            description={t('employees.page.emptyDesc')}
          />
        ) : (
          <div className="grid grid-cols-1 gap-2.5 p-[18px_22px] tablet:grid-cols-2 desktop:grid-cols-2">
            {cards.map((post) => (
              <EmployeeCard
                key={post.member_post_id}
                post={post}
                onLaunch={() => setLaunchFor(post)}
                onEdit={() => setDetailFor(post)}
              />
            ))}
          </div>
        )}
      </div>

      <LaunchEmployeeDialog
        post={launchFor}
        onClose={() => setLaunchFor(null)}
        onCreated={(launch, text) => {
          // 统一交由会话工作台的成熟启动管线（useSessionLaunch + SessionLaunchPanel + SessionRail）接管。
          launchWorkbenchSession(launch, text);
        }}
      />

      <EmployeeDetailDialog
        post={detailFor}
        creating={creating}
        onClose={() => {
          setDetailFor(null);
          setCreating(false);
        }}
        onSaved={reload}
        /**
         * 新建成功就当场换成这个员工的详情：服务端返回前已经跑完首次巡检，那份编制里带着
         * 刚认下的资源，人不用自己再找回来。清单由 `onSaved` 那边重取，这里只管切态。
         */
        onCreated={(created) => {
          setCreating(false);
          setDetailFor(created);
        }}
      />
    </div>
  );
}

/**
 * 一张员工卡片。整卡可点，右边那颗编辑胶囊是改配置。
 *
 * 编辑那颗按钮要 `stopPropagation`：不然点它先触发整卡的起会话，人会看见两个窗一起冒出来
 * ——一个是他要的，另一个是他刚点掉的。
 */
function EmployeeCard({
  post,
  onLaunch,
  onEdit,
}: {
  post: EmployeePost;
  onLaunch: () => void;
  onEdit: () => void;
}) {
  const { t } = useTranslation();
  const summaryParts = employeeSummaryParts(employeeSummary(post));
  const empColor = resolveEmployeeColor(post.color, post.member_post_id);

  return (
    <div
      role="button"
      tabIndex={0}
      /* 键盘焦点走全站同一套双环（外扩 3px + 内收 1px）。此前这里自己写了 `ring-2`，
         它比全局那条 `:focus-visible` 更具体，于是把内收那圈顶掉了——卡片一旦落进
         会裁剪的容器（窄屏滚动、外层 overflow），焦点环就只剩半圈。 */
      className="emp-card group focus:outline-none"
      onClick={onLaunch}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onLaunch();
        }
      }}
      title={t('employees.card.startWith', { name: post.title })}
      data-testid={`employee-card-${post.member_post_id}`}
      data-emp-color={empColor}
    >
      <span className="emp-card-badge">{employeeInitials(post.member_post_id)}</span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="min-w-0 truncate text-[13px] font-semibold text-text-primary">
            {post.title}
          </span>
        </div>
        {/* 摘要最多两行。没有摘要时这一行整个不渲染，不留占位灰字。
            里面被反引号圈起来的词渲染成代码词，卡面上不出现反引号字符。
            截断走 Tailwind 的 `line-clamp-2`，与全站其余多行截断同一写法。 */}
        {summaryParts.length > 0 ? (
          <div className="emp-card-summary line-clamp-2">
            {summaryParts.map((part, i) =>
              part.code ? <code key={i}>{part.text}</code> : <span key={i}>{part.text}</span>,
            )}
          </div>
        ) : null}
      </div>

      {/* 编辑动作：一枚轻量动作胶囊。静置时只有一枚弱色铅笔（没有底、没有边），
          鼠标停在卡上或键盘把焦点移进来时才长出一圈描边与底色。
          **不用 `opacity: 0` 藏起来**：那会在卡片右边缘留一块看不见却能点的区域，
          人想点整卡起会话，落到那里却开了详情窗。 */}
      <button
        type="button"
        className="emp-card-edit"
        title={t('employees.card.edit')}
        aria-label={`${t('employees.card.edit')} ${post.title}`}
        onClick={(e) => {
          e.stopPropagation();
          onEdit();
        }}
      >
        <Pencil size={13} strokeWidth={1.5} />
      </button>
    </div>
  );
}
