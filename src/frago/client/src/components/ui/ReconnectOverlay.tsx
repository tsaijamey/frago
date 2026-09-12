/**
 * 本机后台服务不在时盖在整页上的那张卡。
 *
 * 服务重启、升级、崩掉的那十几秒里，页面上的东西全是旧的：清单停在断开前那一刻，正在
 * 跑的会话看着像停了，点哪儿都不动。此前这套界面对这件事的说法是十几处零碎报错，人得
 * 自己拼出「是服务没了」。这张卡把话说全：不是这一页坏了，是本机服务还没回来。
 *
 * 底下的内容模糊掉而不是留清楚，是把注意力交给上面这句话——服务没回来之前，底下那些
 * 字一个都不能信，让它们清清楚楚地摆着等于邀请人照着旧数据做判断。
 *
 * 它不接点击、也没有关闭按钮：关掉它并不能让服务回来，只会让人对着一个哑掉的页面继续点。
 */

import { useTranslation } from 'react-i18next';
import { useConnectionStore } from '@/api/connection';

export default function ReconnectOverlay() {
  const reachable = useConnectionStore((state) => state.reachable);
  const { t } = useTranslation();

  if (reachable) return null;

  return (
    <div className="reconnect-overlay" data-testid="reconnect-overlay" role="status" aria-live="polite">
      <div className="reconnect-card">
        <div className="spinner" />
        <div className="reconnect-title">{t('reconnect.title')}</div>
        <div className="reconnect-hint">{t('reconnect.hint')}</div>
      </div>
    </div>
  );
}
