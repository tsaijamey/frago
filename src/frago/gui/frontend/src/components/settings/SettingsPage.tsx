// 设置组件
import GeneralSettings from './GeneralSettings';
import SyncSettings from './SyncSettings';
import SecretsSettings from './SecretsSettings';
import AppearanceSettings from './AppearanceSettings';
import AboutSettings from './AboutSettings';

export default function SettingsPage() {
  return (
    <div className="h-full overflow-auto">
      <div className="page-scroll p-4 max-w-2xl mx-auto space-y-6">
        {/* 页面标题 */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">设置</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            配置 Frago 的各项功能
          </p>
        </div>

        {/* 通用配置 */}
        <section>
          <GeneralSettings />
        </section>

        {/* 多设备同步 */}
        <section>
          <SyncSettings />
        </section>

        {/* 密钥管理 */}
        <section>
          <SecretsSettings />
        </section>

        {/* 外观设置 */}
        <section>
          <AppearanceSettings />
        </section>

        {/* 关于 */}
        <section>
          <AboutSettings />
        </section>
      </div>
    </div>
  );
}
