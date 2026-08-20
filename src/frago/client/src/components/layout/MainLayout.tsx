/**
 * MainLayout Component
 *
 * Layout: TopBar across the top + left icon-rail Sidebar + content area.
 * Navigation lives in the left rail (collapsed to icons, expands on hover).
 */

import { ReactNode } from 'react';
import TopBar from './TopBar';
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

      {/* Top status bar */}
      <TopBar />

      <div className="main-layout">
        {/* Left icon-rail navigation */}
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
