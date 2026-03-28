/**
 * MainLayout Component
 *
 * New layout: TopBar + full-width content + floating BottomDock.
 * No sidebar — navigation lives in the dock.
 */

import { ReactNode } from 'react';
import TopBar from './TopBar';
import BottomDock from './BottomDock';
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

      <div className="main-layout main-layout--no-sidebar">
        {/* Content Area — full width */}
        <div className="content-area content-area--full">
          <main className="main-content">
            {children}
          </main>
        </div>
      </div>

      {/* Floating bottom navigation */}
      <BottomDock />
    </div>
  );
}
