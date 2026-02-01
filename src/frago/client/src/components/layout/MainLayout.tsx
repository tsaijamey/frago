/**
 * MainLayout Component
 *
 * Main layout wrapper that combines:
 * - Collapsible left sidebar for navigation (includes system status)
 * - Content area for page rendering
 */

import { ReactNode } from 'react';
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

      <div className="main-layout">
        {/* Sidebar */}
        <Sidebar />

        {/* Content Area */}
        <div className="content-area">
          {/* Main Content */}
          <main className="main-content">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
