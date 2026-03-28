/**
 * ProfilesPanel — API Profiles management panel.
 *
 * Card-based layout showing each profile with provider, model, connection status.
 */

import { useEffect, useState } from 'react';
import { getProfiles, type ProfileItem } from '@/api';
import ProfileManager from './ProfileManager';
import { Plus } from 'lucide-react';

export default function ProfilesPanel() {
  const [profiles, setProfiles] = useState<ProfileItem[]>([]);
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showManager, setShowManager] = useState(false);

  const loadData = async () => {
    try {
      setLoading(true);
      const data = await getProfiles();
      setProfiles(data.profiles);
      setActiveProfileId(data.active_profile_id);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  if (loading) {
    return (
      <div>
        <h2 className="settings-panel-title">API Profiles</h2>
        <p style={{ color: 'var(--text-dim)', fontSize: '12px', padding: '20px 0' }}>加载中...</p>
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
        <h2 className="settings-panel-title">API Profiles</h2>
        <button
          className="recipe-card-run"
          onClick={() => setShowManager(true)}
          style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
        >
          <Plus size={14} /> 新建 Profile
        </button>
      </div>

      {/* Profile Cards */}
      {profiles.map((profile) => {
        const isActive = profile.id === activeProfileId;
        return (
          <div key={profile.id} className="profile-card">
            <div className="profile-card-header">
              <div className="profile-card-name">
                {isActive && <span className="profile-card-badge">默认</span>}
                {profile.name}
              </div>
              <div className={`profile-card-status ${isActive ? 'profile-card-status--connected' : 'profile-card-status--disconnected'}`}>
                {isActive ? '● 已连接' : '○ 未配置'}
              </div>
            </div>
            <div className="profile-card-field">
              <strong>Provider:</strong> {profile.endpoint_type}
            </div>
            {profile.default_model && (
              <div className="profile-card-field">
                <strong>Model:</strong> {profile.default_model}
              </div>
            )}
            <div className="profile-card-field">
              <strong>API Key:</strong> {profile.api_key_masked}
            </div>
            {profile.url && (
              <div className="profile-card-field">
                <strong>Base URL:</strong> {profile.url}
              </div>
            )}
          </div>
        );
      })}

      {profiles.length === 0 && (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-dim)', fontSize: '12px' }}>
          暂无 Profile，点击 "新建 Profile" 添加
        </div>
      )}

      {/* Profile Manager Modal */}
      <ProfileManager
        isOpen={showManager}
        onClose={() => setShowManager(false)}
        onProfileActivated={() => loadData()}
      />
    </div>
  );
}
