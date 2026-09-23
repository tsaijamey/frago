import { Coins, Eye, EyeOff, Loader2, Radar } from 'lucide-react';
import { agentReasonText } from '@/hooks/useAgentClients';
import type { ProfilesController } from './useProfiles';

export default function ProfileForm({ pm }: { pm: ProfilesController }) {
  const {
    t,
    presets,
    vendorCores,
    workbuddy,
    probingWorkbuddy,
    startWorkbuddyProbe,
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

  // Borrowing the WorkBuddy login: no endpoint and no key again, but here it is
  // frago-core that calls the gateway, so the model can only be one the last
  // probe found answering. Half the names WorkBuddy hands out do not answer.
  const isWorkbuddy = formKind === 'workbuddy';
  // The backend hands these back cheapest-first, so the order here is the order
  // to show. What a call costs is the thing to pick on; how fast the first token
  // arrives is still measured, it just no longer leads.
  const usableModels = (workbuddy?.models ?? []).filter((m) => m.ok);
  // On the client's menu but never probed. Whether they answer through the
  // gateway is unknown until a round runs, which is why they are named rather
  // than offered.
  const unprobedModels = workbuddy?.catalog_new ?? [];
  const balance = workbuddy?.balance;

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
            // Same for a WorkBuddy model: anything the probe did not find
            // answering is refused on save.
            if (kind === 'workbuddy' && !usableModels.some((m) => m.id === formDefaultModel)) {
              setFormDefaultModel(usableModels[0]?.id ?? '');
            }
          }}
          className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
        >
          <option value="endpoint">{t('settings.profiles.kindEndpoint')}</option>
          {vendorCores.length > 0 && (
            <option value="vendor_cli">{t('settings.profiles.kindVendorCli')}</option>
          )}
          <option value="workbuddy">{t('settings.profiles.kindWorkbuddy')}</option>
        </select>
        {isVendorCli && (
          <p className="text-xs text-[var(--text-muted)] mt-1">
            {t('settings.profiles.vendorCliHint')}
          </p>
        )}
        {isWorkbuddy && (
          <>
            <p className="text-xs text-[var(--text-muted)] mt-1">
              {t('settings.profiles.workbuddyHint')}
            </p>
            {/* 选了这种连接就会花到积分。花在哪、花多少，不该等点下按钮才知道，更不该
                跟普通说明混成同一级灰字——那等于没说。 */}
            <div className="flex gap-2 mt-2 px-3 py-2 rounded-md bg-[var(--accent-warning-10)] border border-[var(--accent-warning)]">
              <Coins size={16} className="shrink-0 mt-0.5 text-[var(--accent-warning)]" />
              <p className="text-xs leading-relaxed text-[var(--text-primary)]">
                {t('settings.profiles.workbuddyProbeNotice')}
              </p>
            </div>
          </>
        )}
      </div>

      {isWorkbuddy ? (
        <>
          {/* A client that quit its session leaves its login file behind, so
              "logged out" has to read differently from "never installed" —
              they are different things for the person to go and do. */}
          {workbuddy && workbuddy.login_state !== 'ok' && (
            <p className="text-xs text-[var(--accent-error)]">
              {workbuddy.login_state === 'logged_out'
                ? t('settings.profiles.workbuddyLoggedOut')
                : t('settings.profiles.workbuddyNotLoggedIn')}
            </p>
          )}
          {usableModels.length === 0 && unprobedModels.length === 0 ? (
            <p className="text-xs text-[var(--text-muted)]">
              {t('settings.profiles.workbuddyNotProbed')}
            </p>
          ) : (
            <div>
              <label htmlFor="profile-workbuddy-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
                {t('settings.profiles.workbuddyModel')}
              </label>
              {/* 客户端菜单上的模型全部列在这里，分两组。还没探过的也进下拉，置灰不可
                  选、名字后面写明「要先探测」——把它们留在下拉外面的一行说明里，人在
                  下拉里找不到那个名字，也看不出下一步该点什么。 */}
              <select
                id="profile-workbuddy-model"
                value={formDefaultModel}
                onChange={(e) => setFormDefaultModel(e.target.value)}
                className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
              >
                {usableModels.length > 0 && (
                  <optgroup label={t('settings.profiles.workbuddyGroupUsable')}>
                    {usableModels.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.id}
                        {m.credits ? ` · ${m.credits}` : ''}
                        {m.thinks ? ` · ${t('settings.profiles.thinks')}` : ''}
                      </option>
                    ))}
                  </optgroup>
                )}
                {unprobedModels.length > 0 && (
                  <optgroup
                    label={t('settings.profiles.workbuddyGroupUnprobed', {
                      count: unprobedModels.length,
                    })}
                  >
                    {unprobedModels.map((m) => (
                      <option key={m.id} value={m.id} disabled>
                        {m.id}
                        {m.credits ? ` · ${m.credits}` : ''}
                        {` — ${t('settings.profiles.workbuddyNeedsProbe')}`}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
            </div>
          )}

          {/* What is left to spend. A total on its own would mislead: the lots
              are burnt earliest-expiry-first, so the nearest date matters as
              much as the number. */}
          {balance && (
            <p className="text-xs text-[var(--text-secondary)]">
              {t('settings.profiles.workbuddyBalance', { credits: balance.remaining })}
              {balance.expires_at && (
                <span className="ml-2 text-[var(--text-muted)]">
                  {t('settings.profiles.workbuddyBalanceExpiring', {
                    credits: balance.expiring,
                    date: balance.expires_at,
                  })}
                </span>
              )}
            </p>
          )}

          {/* Nothing refreshes the list on its own, so the page has to say how
              old it is and what the client has added since. */}
          <div className="rounded-md bg-[var(--bg-subtle)] px-3 py-2 space-y-1.5">
            {workbuddy?.probed_at && (
              <p className="text-xs text-[var(--text-muted)]">
                {t('settings.profiles.workbuddyProbedAtPlain', {
                  time: workbuddy.probed_at.slice(0, 16).replace('T', ' '),
                })}
                {workbuddy.stale && (
                  <span className="ml-2 text-[var(--accent-warning)]">
                    {t('settings.profiles.workbuddyStale', { days: workbuddy.stale_after_days })}
                  </span>
                )}
              </p>
            )}
            {/* 名字已经在下拉里置灰列着了，这里不再重复念一遍，只说清还差几个、
                以及点下面那个按钮就能把它们变成可选。 */}
            {unprobedModels.length > 0 && (
              <p className="text-xs text-[var(--text-muted)]">
                {t('settings.profiles.workbuddyUnprobed', { count: unprobedModels.length })}
              </p>
            )}
            {/* 这个按钮一按就花积分，跟「保存」「取消」不是一类动作，长得也不该一样：
                带上警示色的描边和一枚图标，把代价写在按钮自己身上，而不是旁边一行灰字。 */}
            <div className="flex items-center gap-2 pt-0.5">
              <button
                type="button"
                onClick={startWorkbuddyProbe}
                disabled={probingWorkbuddy || workbuddy?.login_state !== 'ok'}
                className="btn btn-sm inline-flex items-center gap-1.5 border border-[var(--accent-warning)] bg-[var(--accent-warning-10)] text-[var(--text-primary)] hover:bg-[var(--accent-warning)] hover:text-[var(--bg-base)] disabled:opacity-50"
              >
                {probingWorkbuddy ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Radar size={14} />
                )}
                {probingWorkbuddy
                  ? t('settings.profiles.workbuddyProbing')
                  : t('settings.profiles.workbuddyProbeNow', {
                      count: unprobedModels.length,
                    })}
              </button>
              <span className="text-xs text-[var(--text-muted)]">
                {t('settings.profiles.workbuddyProbeCost')}
              </span>
            </div>
          </div>
        </>
      ) : isVendorCli ? (
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
          {presets.map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name}
            </option>
          ))}
          <option value="custom">{t('settings.profiles.customEndpoint')}</option>
        </select>
      </div>

      {/* Where requests will actually go. A custom endpoint has to be told;
          a preset already knows, and says so instead of staying silent. */}
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

      {/* Model overrides. Left empty, a preset uses the model in its
          placeholder; a custom endpoint has nothing to fall back on. */}
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
        </>
      )}

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
