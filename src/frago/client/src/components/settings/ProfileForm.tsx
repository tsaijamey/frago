import { Eye, EyeOff } from 'lucide-react';
import { agentReasonText } from '@/hooks/useAgentClients';
import type { ProfilesController } from './useProfiles';

export default function ProfileForm({ pm }: { pm: ProfilesController }) {
  const {
    t,
    presets,
    vendorCores,
    viewMode,
    formName,
    setFormName,
    formKind,
    setFormKind,
    formAgentType,
    setFormAgentType,
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
    formContextWindow,
    setFormContextWindow,
    formResponsesUrl,
    setFormResponsesUrl,
    formResponsesModel,
    setFormResponsesModel,
    showFormApiKey,
    setShowFormApiKey,
    formSubmitting,
    setViewMode,
    resetForm,
    handleFormSubmit,
  } = pm;

  // A preset already knows its URL and its models. Showing them as the field's
  // placeholder is what turns "Default Model" from a field you have to look up
  // elsewhere into one you can leave alone unless you mean to override it.
  const preset = presets.find((p) => p.id === formEndpointType);

  // A vendor CLI is a different set of questions, not a variant of the same
  // ones: no endpoint to reach, no key to hold, and a model list that comes
  // from that CLI's own service rather than from a preset table.
  const isVendorCli = formKind === 'vendor_cli';
  const core = vendorCores.find((c) => c.agent_type === formAgentType);

  // Borrowing the WorkBuddy login was retired 2026-10-09: the client began
  // encrypting its login file and kept the key to itself, so frago has nothing
  // to read. Rows written before then still open here, and the form says why
  // they can no longer be used rather than offering a model to pick.
  const isWorkbuddy = formKind === 'workbuddy';

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

      {/* What kind of connection this is. It decides which half of the form is
          even meaningful. The vendor CLI option only appears when frago knows
          of a core that runs on its own account. */}
      <div>
        <label htmlFor="profile-kind" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
          {t('settings.profiles.connectionKind')}
        </label>
        <select
          id="profile-kind"
          value={formKind}
          onChange={(e) => {
            const kind = e.target.value as typeof formKind;
            setFormKind(kind);
            // Land on a usable core straight away; an empty core is the one
            // thing the backend will refuse to save.
            if (kind === 'vendor_cli' && !formAgentType && vendorCores.length > 0) {
              setFormAgentType(vendorCores[0].agent_type);
            }
          }}
          className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
        >
          <option value="endpoint">{t('settings.profiles.kindEndpoint')}</option>
          {vendorCores.length > 0 && (
            <option value="vendor_cli">{t('settings.profiles.kindVendorCli')}</option>
          )}
          {/* 借 WorkBuddy 登录这条路 2026-10-09 下线。条目留着而不是摘掉，是让老记录
              还有一处读得出它为什么不能用了。 */}
          <option value="workbuddy" disabled>
            {t('settings.profiles.kindWorkbuddyRetired')}
          </option>
        </select>
        {isVendorCli && (
          <p className="text-xs text-[var(--text-muted)] mt-1">
            {t('settings.profiles.vendorCliHint')}
          </p>
        )}
        {isWorkbuddy && (
          <p className="text-xs text-[var(--accent-error)] mt-1">
            {t('settings.profiles.workbuddyRetired')}
          </p>
        )}
      </div>

      {/* A record saved before 2026-10-09 that borrowed the WorkBuddy login has
          nothing left to fill in — the notice under the kind picker says why.
          Showing the endpoint fields would invite someone to fill them in and
          hand the save button a connection that reaches nowhere. */}
      {isWorkbuddy ? null : isVendorCli ? (
        <>
          {/* Which core, and which of the models its own service offers. */}
          <div>
            <label htmlFor="profile-agent-core" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
              {t('settings.profiles.agentCore')}
            </label>
            <select
              id="profile-agent-core"
              value={formAgentType}
              onChange={(e) => setFormAgentType(e.target.value)}
              className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
            >
              {vendorCores.map((c) => (
                <option key={c.agent_type} value={c.agent_type}>
                  {c.display_name}
                  {c.installed ? '' : ` — ${t('settings.profiles.notInstalled')}`}
                </option>
              ))}
            </select>
            {core?.reason && (
              <p className="text-xs text-[var(--text-muted)] mt-1">{agentReasonText(core.reason)}</p>
            )}
          </div>

          <div>
            <label htmlFor="profile-vendor-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
              {t('settings.profiles.defaultModel')}
            </label>
            {/* A datalist rather than a plain select: the roster is what this
                CLI offered when frago last looked, and it moves. Typing a name
                that is not on it has to keep working. */}
            <input
              id="profile-vendor-model"
              type="text"
              list="profile-vendor-model-options"
              value={formDefaultModel}
              onChange={(e) => setFormDefaultModel(e.target.value)}
              placeholder={core?.known_models[0] ?? ''}
              className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
            />
            <datalist id="profile-vendor-model-options">
              {(core?.known_models ?? []).map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
            {core && core.known_models.length > 0 && (
              <p className="text-xs text-[var(--text-muted)] mt-1">
                {t('settings.profiles.modelCandidates')}: {core.known_models.join(', ')}
              </p>
            )}
          </div>
        </>
      ) : (
        <>
      {/* Which vendor this connection reaches. It decides the preset — the
          addresses and model names offered below as placeholders. */}
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
          {presets.map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name}
            </option>
          ))}
          <option value="custom">{t('settings.profiles.customEndpoint')}</option>
        </select>
      </div>

      {/* The credential. One key opens every protocol door below; it used to
          sit inside the Anthropic half, which read as if it belonged to that
          protocol alone. */}
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
        <p className="text-xs text-[var(--text-muted)] mt-1">
          {t('settings.profiles.apiKeySharedHint')}
        </p>
      </div>

      {/* Two protocol doors, same shape, neither named after an agent. A
          profile can carry one or both; which agent reads which is the
          picker's business, not the form's. */}
      <div className="rounded-md border border-[var(--border-color)] px-3 py-2.5 space-y-2">
        <div>
          <p className="text-xs font-medium text-[var(--text-secondary)]">
            {t('settings.profiles.anthropicTitle')}
          </p>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            {t('settings.profiles.anthropicHint')}
          </p>
        </div>
        {formEndpointType === 'custom' ? (
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
        ) : (
          preset && (
            <p className="text-xs text-[var(--text-muted)] font-mono break-all">
              {preset.base_url}
            </p>
          )
        )}
        <div>
          <label htmlFor="profile-default-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
            {t('settings.profiles.defaultModel')}
            {preset && <span className="ml-1 text-[var(--text-muted)]">- {t('settings.general.optionalOverride')}</span>}
          </label>
          <input
            id="profile-default-model"
            type="text"
            value={formDefaultModel}
            onChange={(e) => setFormDefaultModel(e.target.value)}
            placeholder={preset ? preset.default_model : 'e.g., gpt-4'}
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
              placeholder={preset ? preset.sonnet_model : t('settings.general.optionalOverride')}
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
              placeholder={preset ? preset.haiku_model : t('settings.general.optionalOverride')}
              className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
            />
          </div>
        </div>
      </div>

      <div className="rounded-md border border-[var(--border-color)] px-3 py-2.5 space-y-2">
        <div>
          <p className="text-xs font-medium text-[var(--text-secondary)]">
            {t('settings.profiles.responsesTitle')}
          </p>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            {preset?.responses_url
              ? t('settings.profiles.responsesPresetHint')
              : t('settings.profiles.responsesHint')}
          </p>
        </div>
        <div>
          <label htmlFor="profile-responses-url" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
            {t('settings.profiles.responsesUrl')}
          </label>
          <input
            id="profile-responses-url"
            type="text"
            value={formResponsesUrl}
            onChange={(e) => setFormResponsesUrl(e.target.value)}
            placeholder={preset?.responses_url || 'https://api.example.com/v1'}
            className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
          />
        </div>
        <div>
          <label htmlFor="profile-responses-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
            {t('settings.profiles.responsesModel')}
            <span className="ml-1 text-[var(--text-muted)]">- {t('settings.general.optionalOverride')}</span>
          </label>
          <input
            id="profile-responses-model"
            type="text"
            value={formResponsesModel}
            onChange={(e) => setFormResponsesModel(e.target.value)}
            placeholder={
              preset?.responses_models?.[0] ||
              formDefaultModel ||
              preset?.default_model ||
              t('settings.profiles.responsesModelSameAsDefault')
            }
            className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
          />
        </div>
      </div>
        </>
      )}

      {/* One window for every CLI this profile is activated on. Each target
          gets it in its own vocabulary when the profile is saved: Claude
          Code's pair of environment variables, Codex's two top-level TOML
          keys, opencode's per-model limit. */}
      {!isWorkbuddy && !isVendorCli && (
        <div className="rounded-md border border-[var(--border-color)] px-3 py-2.5 space-y-2">
          <div>
            <p className="text-xs font-medium text-[var(--text-secondary)]">
              {t('settings.profiles.contextWindow')}
            </p>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              {t('settings.profiles.contextWindowHint')}
            </p>
          </div>
          <div className="flex gap-2">
            <input
              id="profile-context-window"
              type="number"
              min={1000}
              max={10000000}
              step={1000}
              value={formContextWindow}
              onChange={(e) => setFormContextWindow(e.target.value)}
              placeholder={t('settings.profiles.contextWindowPlaceholder')}
              className="flex-1 px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
            />
            <button
              type="button"
              onClick={() => setFormContextWindow('200000')}
              className="btn btn-ghost btn-sm"
            >
              200K
            </button>
            <button
              type="button"
              onClick={() => setFormContextWindow('1000000')}
              className="btn btn-ghost btn-sm"
            >
              1M
            </button>
          </div>
        </div>
      )}

      {/* Form actions */}
      <div className="flex gap-2 pt-2">
        <button
          type="button"
          onClick={handleFormSubmit}
          disabled={formSubmitting || !formName.trim() || isWorkbuddy}
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
