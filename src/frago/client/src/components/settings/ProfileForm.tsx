import { Eye, EyeOff } from 'lucide-react';
import type { ProfilesController } from './useProfiles';

export default function ProfileForm({ pm }: { pm: ProfilesController }) {
  const {
    t,
    viewMode,
    formName,
    setFormName,
    formEndpointType,
    setFormEndpointType,
    formApiKey,
    setFormApiKey,
    formUrl,
    setFormUrl,
    formDefaultModel,
    setFormDefaultModel,
    formSonnetModel,
    setFormSonnetModel,
    formHaikuModel,
    setFormHaikuModel,
    showFormApiKey,
    setShowFormApiKey,
    formSubmitting,
    setViewMode,
    resetForm,
    handleFormSubmit,
  } = pm;

  return (
    <div className="space-y-3">
      {/* Profile name */}
      <div>
        <label htmlFor="profile-name" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
          {t('settings.profiles.profileName')}
        </label>
        <input
          id="profile-name"
          type="text"
          value={formName}
          onChange={(e) => setFormName(e.target.value)}
          placeholder={t('settings.profiles.profileNamePlaceholder')}
          className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
          autoFocus
        />
      </div>

      {/* Endpoint type */}
      <div>
        <label htmlFor="profile-endpoint-type" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
          {t('settings.profiles.endpointType')}
        </label>
        <select
          id="profile-endpoint-type"
          value={formEndpointType}
          onChange={(e) => setFormEndpointType(e.target.value)}
          className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
        >
          <option value="deepseek">DeepSeek API</option>
          <option value="aliyun">Aliyun API</option>
          <option value="kimi">Kimi API</option>
          <option value="minimax">MiniMax API</option>
          <option value="custom">Custom URL</option>
        </select>
      </div>

      {/* Custom URL */}
      {formEndpointType === 'custom' && (
        <div>
          <label htmlFor="profile-url" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
            {t('settings.profiles.apiUrl')}
          </label>
          <input
            id="profile-url"
            type="text"
            value={formUrl}
            onChange={(e) => setFormUrl(e.target.value)}
            placeholder="https://api.example.com/anthropic"
            className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
          />
        </div>
      )}

      {/* API Key */}
      <div>
        <label htmlFor="profile-api-key" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
          {t('settings.profiles.apiKey')}
          {viewMode === 'edit' && (
            <span className="ml-2 text-[var(--text-muted)]">({t('settings.general.leaveEmptyToKeep')})</span>
          )}
        </label>
        <div className="flex gap-2">
          <input
            id="profile-api-key"
            type={showFormApiKey ? 'text' : 'password'}
            value={formApiKey}
            onChange={(e) => setFormApiKey(e.target.value)}
            placeholder={viewMode === 'edit' ? t('settings.general.leaveEmptyToKeep') : t('settings.general.enterApiKey')}
            className="flex-1 px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
          />
          <button
            type="button"
            onClick={() => setShowFormApiKey(!showFormApiKey)}
            className="btn btn-ghost btn-sm p-2"
            aria-label={showFormApiKey ? t('settings.general.hideApiKey') : t('settings.general.showApiKey')}
          >
            {showFormApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
      </div>

      {/* Model overrides */}
      <div>
        <label htmlFor="profile-default-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
          {t('settings.profiles.defaultModel')}
          {formEndpointType !== 'custom' && <span className="ml-1 text-[var(--text-muted)]">- {t('settings.general.optionalOverride')}</span>}
        </label>
        <input
          id="profile-default-model"
          type="text"
          value={formDefaultModel}
          onChange={(e) => setFormDefaultModel(e.target.value)}
          placeholder={formEndpointType === 'custom' ? 'e.g., gpt-4' : t('settings.general.leaveEmptyDefault')}
          className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="profile-sonnet-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
            {t('settings.profiles.sonnetModel')}
          </label>
          <input
            id="profile-sonnet-model"
            type="text"
            value={formSonnetModel}
            onChange={(e) => setFormSonnetModel(e.target.value)}
            placeholder={t('settings.general.optionalOverride')}
            className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
          />
        </div>
        <div>
          <label htmlFor="profile-haiku-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
            {t('settings.profiles.haikuModel')}
          </label>
          <input
            id="profile-haiku-model"
            type="text"
            value={formHaikuModel}
            onChange={(e) => setFormHaikuModel(e.target.value)}
            placeholder={t('settings.general.optionalOverride')}
            className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
          />
        </div>
      </div>

      {/* Form actions */}
      <div className="flex gap-2 pt-2">
        <button
          type="button"
          onClick={handleFormSubmit}
          disabled={formSubmitting || !formName.trim()}
          className="btn btn-primary btn-sm disabled:opacity-50"
        >
          {formSubmitting
            ? viewMode === 'add'
              ? t('settings.profiles.creating')
              : t('settings.profiles.updating')
            : t('settings.profiles.save')}
        </button>
        <button
          type="button"
          onClick={() => {
            setViewMode('list');
            resetForm();
          }}
          className="btn btn-ghost btn-sm"
        >
          {t('settings.profiles.cancel')}
        </button>
      </div>
    </div>
  );
}
