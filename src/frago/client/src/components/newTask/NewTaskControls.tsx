import { useTranslation } from 'react-i18next';
import { Plus, Square } from 'lucide-react';

interface NewTaskControlsProps {
  isRunning: boolean;
  /** 这一页是否已经有内容（发过至少一条）。没内容时它本身就是「新的」，不需要再开一个。 */
  hasContent: boolean;
  onNewSession: () => void;
  onStop: () => void;
}

/**
 * 新建会话页页头右侧的动作区。
 *
 * 此前这里常驻一枚 `+ New Session` 文字按钮：它和左侧导航那枚 `+` 是同一件事，
 * 一个页面里出现两个入口；位置又漂在内容区左上角、不在页头里，是这一页最扎眼的
 * 一处违和。现在两个动作各归其位——「开一场新的」只在已经聊过、确实需要重开时
 * 出现，「停下来」只在真跑着的时候出现；两个都不需要时，页头只剩标题。
 */
export default function NewTaskControls({
  isRunning,
  hasContent,
  onNewSession,
  onStop
}: NewTaskControlsProps) {
  const { t } = useTranslation();

  if (!isRunning && !hasContent) return null;

  return (
    <>
      {hasContent && (
        <button
          type="button"
          className="page-header-btn"
          onClick={onNewSession}
        >
          <Plus size={14} strokeWidth={1.75} />
          <span>{t('console.newSession')}</span>
        </button>
      )}
      {isRunning && (
        <button
          type="button"
          className="page-header-btn nt-stop"
          onClick={onStop}
        >
          <Square size={14} strokeWidth={1.75} />
          <span>{t('console.stop')}</span>
        </button>
      )}
    </>
  );
}
