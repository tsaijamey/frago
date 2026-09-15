/**
 * MainLayout Component
 *
 * 左侧一根常驻导航栏 + 右侧内容区，没有顶栏。
 *
 * 顶栏从前横贯整个窗口，装的是 logo、运行状态与时钟三样东西——三样都已经在左栏里
 * 有了位置（logo 在栏顶，状态在栏底），而它换走的是每一页顶上 48px 的垂直空间。
 * 会话页是三栏并排，那 48px 直接从记录流的可读高度里扣。
 *
 * 顶上那条「有新版可用」的横幅也已经撤掉。frago 的版本现在跟其余十几样东西一起，
 * 摆在左栏的环境检查里——同一件事出现在两个地方，人只会去问哪个才作数。何况那条
 * 横幅只会比版本号大小：开发机上的 frago 是自己构建的，比线上发布的新，它照样劝人
 * 「更新」，点下去是拿旧的盖掉新的。
 */

import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import MobileTabBar from './MobileTabBar';
import GitHubGuardBanner from '@/components/github/GitHubGuardBanner';
import RecipeAppHost from '@/components/recipes/RecipeAppHost';

interface MainLayoutProps {
  children: ReactNode;
}

export default function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="main-layout-wrapper">
      {/* GitHub CLI missing or logged out — no backup is running. Not dismissible. */}
      <GitHubGuardBanner />

      <div className="main-layout">
        {/* Left navigation rail */}
        <Sidebar />

        {/* Content Area */}
        <div className="content-area">
          <main className="main-content">
            {/* 打开过的配方页面常驻在这里，切到别的页面时只是藏起来——
                人在上面没保存的输入不会因为去点了一下运行就没了。 */}
            <RecipeAppHost />
            {children}
          </main>
        </div>
      </div>

      {/* Phone-only bottom tab bar (rail is hidden ≤640px) */}
      <MobileTabBar />
    </div>
  );
}
