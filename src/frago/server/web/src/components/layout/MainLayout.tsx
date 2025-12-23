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
    <div
      className="main-layout"
      style={{
        display: 'flex',
        height: '100%',
        width: '100%',
        overflow: 'hidden',
      }}
    >
      {/* Sidebar */}
      <Sidebar />

      {/* Content Area */}
      <div
        className="content-area"
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          minWidth: 0, // Allow flex item to shrink below content size
        }}
      >
        {/* Main Content */}
        <main
          className="main-content"
          style={{
            flex: 1,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {children}
        </main>

        {/* Status Bar */}
        <StatusBar />
      </div>
    </div>
  );
}
