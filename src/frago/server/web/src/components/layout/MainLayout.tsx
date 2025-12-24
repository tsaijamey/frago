/**
 * MainLayout Component
 *
 * Main layout wrapper that combines:
 * - Collapsible left sidebar for navigation
 * - Content area for page rendering
 * - Status bar at the bottom
 */

import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import StatusBar from './StatusBar';

interface MainLayoutProps {
  children: ReactNode;
}

export default function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="main-layout">
      {/* Sidebar */}
      <Sidebar />

      {/* Content Area */}
      <div className="content-area">
        {/* Main Content */}
        <main className="main-content">
          {children}
        </main>

        {/* Status Bar */}
        <StatusBar />
      </div>
    </div>
  );
}
