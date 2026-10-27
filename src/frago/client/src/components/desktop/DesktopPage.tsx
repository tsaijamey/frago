/**
 * 虚拟桌面（agent_os）常驻页。
 *
 * 从前虚拟桌面是独立打开的一张浏览器标签页（`/app/agent_os`），人在工作台看会话、
 * 看虚拟桌面得在两个标签之间来回切。现在它作为左侧菜单 `desktop` 项（紧跟 `sessions`
 * 下方）常驻在主界面右侧，与会话工作台等主视图并列，不再走临时标签页，也不挂到
 * `recipes` 的临时子项下面。
 *
 * 切去别的页面时，`PageHost` 把这一页保留在 DOM 中且不卸载 iframe，WebSocket 与画布
 * 帧流不断连。
 */

import { useTranslation } from 'react-i18next';
import { desktopAppUrl } from '@/api/client';
import { usePageStore } from '@/stores/pageStore';

export default function DesktopPage() {
  const { t } = useTranslation();
  const sessionId = usePageStore((s) => s.desktopSessionId);
  const src = desktopAppUrl(sessionId);

  return (
    <div className="desktop-page">
      <iframe
        className="desktop-page-frame"
        src={src}
        title={t('sidebar.nav.desktop')}
      />
    </div>
  );
}
