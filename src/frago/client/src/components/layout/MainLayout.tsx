/**
 * MainLayout Component
 *
 * 左侧一根常驻导航栏 + 右侧内容区，没有顶栏。
 *
 * 顶栏从前横贯整个窗口，装的是 logo、运行状态与时钟三样东西——三样都已经在左栏里
 * 有了位置（logo 在栏顶，状态在栏底），而它换走的是每一页顶上 48px 的垂直空间。
 * 会话页是三栏并排，那 48px 直接从记录流的可读高度里扣。
 */

import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import MobileTabBar from './MobileTabBar';
import VersionBanner from './VersionBanner';
import GitHubGuardBanner from '@/components/github/GitHubGuardBanner';

interface MainLayoutProps {
  children: ReactNode;
}

export default function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="main-layout-wrapper">
      {/* Version Update Banner */}
      <VersionBanner />

      {/* GitHub CLI missing or logged out — no backup is running. Not dismissible. */}
      <GitHubGuardBanner />

      <div className="main-layout">
        {/* Left navigation rail */}
        <Sidebar />

        {/* Content Area */}
        <div className="content-area">
          <main className="main-content">
            {children}
          </main>
        </div>
      </div>

      {/* Phone-only bottom tab bar (rail is hidden ≤640px) */}
      <MobileTabBar />
    </div>
  );
}
