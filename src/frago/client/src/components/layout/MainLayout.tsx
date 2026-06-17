/**
 * MainLayout Component
 *
 * Layout: TopBar across the top + left icon-rail Sidebar + content area.
 * Navigation lives in the left rail (collapsed to icons, expands on hover).
 */

import { ReactNode } from 'react';
import TopBar from './TopBar';
import Sidebar from './Sidebar';
import VersionBanner from './VersionBanner';

interface MainLayoutProps {
  children: ReactNode;
}

export default function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="main-layout-wrapper">
      {/* Version Update Banner */}
      <VersionBanner />

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
    </div>
  );
}
