import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock the API layer so no real network / pywebview call happens.
vi.mock('@/api', () => ({
  getConfig: vi.fn(),
  getRecipes: vi.fn(),
  getSkills: vi.fn(),
  getSystemStatus: vi.fn(),
  getCommunityRecipes: vi.fn(),
  updateConfig: vi.fn(),
  checkGitHubStarred: vi.fn(),
  toggleGitHubStar: vi.fn(),
}));

// Mock i18n so setLanguage doesn't touch the real instance.
vi.mock('@/i18n', () => ({
  default: { changeLanguage: vi.fn(), language: 'en' },
}));

import * as api from '@/api';
import { useDataStore } from '../dataStore';
import { useUIStore } from '../uiStore';

const initial = useDataStore.getState();

function reset() {
  localStorage.clear();
  vi.clearAllMocks();
  useDataStore.setState({
    config: null,
    recipes: [],
    communityRecipes: [],
    skills: [],
    systemStatus: null,
    dataVersion: 0,
    dataInitialized: false,
    versionInfo: null,
    updateStatus: null,
    githubStarStatus: { isStarred: null, ghConfigured: false, isLoading: false },
  });
}

describe('dataStore — direct setters', () => {
  beforeEach(reset);

  it('setRecipes / setCommunityRecipes / setSkills replace the cached collection', () => {
    useDataStore.getState().setRecipes([{ name: 'r' } as never]);
    useDataStore.getState().setCommunityRecipes([{ name: 'c' } as never]);
    useDataStore.getState().setSkills([{ name: 's' } as never]);
    const s = useDataStore.getState();
    expect(s.recipes).toEqual([{ name: 'r' }]);
    expect(s.communityRecipes).toEqual([{ name: 'c' }]);
    expect(s.skills).toEqual([{ name: 's' }]);
  });

  it('setVersionInfo / setUpdateStatus store the value', () => {
    useDataStore.getState().setVersionInfo({ tag: '1' } as never);
    useDataStore.getState().setUpdateStatus({ status: 'idle' } as never);
    expect(useDataStore.getState().versionInfo).toEqual({ tag: '1' });
    expect(useDataStore.getState().updateStatus).toEqual({ status: 'idle' });
  });
});

describe('dataStore — load actions', () => {
  beforeEach(reset);

  it('loadRecipes stores the fetched list', async () => {
    vi.mocked(api.getRecipes).mockResolvedValue([{ name: 'a' } as never]);
    await useDataStore.getState().loadRecipes();
    expect(useDataStore.getState().recipes).toEqual([{ name: 'a' }]);
  });

  it('loadRecipes swallows errors and leaves state unchanged', async () => {
    vi.mocked(api.getRecipes).mockRejectedValue(new Error('boom'));
    await useDataStore.getState().loadRecipes();
    expect(useDataStore.getState().recipes).toEqual([]);
  });

  it('loadSkills / loadSystemStatus / loadCommunityRecipes store their fetched data', async () => {
    vi.mocked(api.getSkills).mockResolvedValue([{ name: 'sk' } as never]);
    vi.mocked(api.getSystemStatus).mockResolvedValue({ cpu_percent: 1 } as never);
    vi.mocked(api.getCommunityRecipes).mockResolvedValue([{ name: 'cr' } as never]);
    await useDataStore.getState().loadSkills();
    await useDataStore.getState().loadSystemStatus();
    await useDataStore.getState().loadCommunityRecipes();
    const s = useDataStore.getState();
    expect(s.skills).toEqual([{ name: 'sk' }]);
    expect(s.systemStatus).toEqual({ cpu_percent: 1 });
    expect(s.communityRecipes).toEqual([{ name: 'cr' }]);
  });
});

describe('dataStore — setDataFromPush version gating', () => {
  beforeEach(reset);

  it('applies a newer version and marks initialized', () => {
    useDataStore.getState().setDataFromPush({ version: 5, recipes: [{ name: 'x' } as never] });
    const s = useDataStore.getState();
    expect(s.dataVersion).toBe(5);
    expect(s.dataInitialized).toBe(true);
    expect(s.recipes).toEqual([{ name: 'x' }]);
  });

  it('ignores an older version', () => {
    useDataStore.setState({ dataVersion: 10 });
    useDataStore.getState().setDataFromPush({ version: 3, recipes: [{ name: 'y' } as never] });
    const s = useDataStore.getState();
    expect(s.dataVersion).toBe(10);
    expect(s.recipes).toEqual([]);
  });

  it('auto-increments the version when none is supplied', () => {
    useDataStore.setState({ dataVersion: 7 });
    useDataStore.getState().setDataFromPush({ skills: [{ name: 'z' } as never] });
    expect(useDataStore.getState().dataVersion).toBe(8);
  });
});

describe('dataStore — updateConfig', () => {
  beforeEach(reset);

  it('optimistically merges then keeps the change on success', async () => {
    useDataStore.setState({ config: { theme: 'dark', language: 'en' } as never });
    vi.mocked(api.updateConfig).mockResolvedValue({ status: 'ok' } as never);
    await useDataStore.getState().updateConfig({ language: 'zh' } as never);
    expect(useDataStore.getState().config).toMatchObject({ theme: 'dark', language: 'zh' });
  });

  it('rolls back and shows an error toast on failure', async () => {
    const original = { theme: 'dark', language: 'en' };
    useDataStore.setState({ config: original as never });
    useUIStore.setState({ toasts: [] });
    vi.mocked(api.updateConfig).mockRejectedValue(new Error('nope'));
    await useDataStore.getState().updateConfig({ language: 'zh' } as never);
    expect(useDataStore.getState().config).toEqual(original);
    expect(useUIStore.getState().toasts.some((t) => t.type === 'error')).toBe(true);
  });

  it('is a no-op when there is no config loaded', async () => {
    await useDataStore.getState().updateConfig({ language: 'zh' } as never);
    expect(api.updateConfig).not.toHaveBeenCalled();
    expect(useDataStore.getState().config).toBeNull();
  });
});

describe('dataStore — GitHub star', () => {
  beforeEach(reset);

  it('checkGitHubStar populates status from the API', async () => {
    vi.mocked(api.checkGitHubStarred).mockResolvedValue({
      is_starred: true,
      gh_configured: true,
    } as never);
    await useDataStore.getState().checkGitHubStar();
    expect(useDataStore.getState().githubStarStatus).toEqual({
      isStarred: true,
      ghConfigured: true,
      isLoading: false,
    });
  });

  it('toggleGitHubStar optimistically flips then confirms from the API', async () => {
    useDataStore.setState({
      githubStarStatus: { isStarred: false, ghConfigured: true, isLoading: false },
    });
    vi.mocked(api.toggleGitHubStar).mockResolvedValue({ is_starred: true } as never);
    await useDataStore.getState().toggleGitHubStar();
    expect(useDataStore.getState().githubStarStatus.isStarred).toBe(true);
    expect(useDataStore.getState().githubStarStatus.isLoading).toBe(false);
  });

  it('toggleGitHubStar reverts isStarred on failure', async () => {
    useDataStore.setState({
      githubStarStatus: { isStarred: false, ghConfigured: true, isLoading: false },
    });
    vi.mocked(api.toggleGitHubStar).mockRejectedValue(new Error('fail'));
    await useDataStore.getState().toggleGitHubStar();
    const s = useDataStore.getState();
    expect(s.githubStarStatus.isStarred).toBe(false);
    expect(s.githubStarStatus.isLoading).toBe(false);
  });

  it('toggleGitHubStar refuses to run when gh is not configured', async () => {
    useDataStore.setState({
      githubStarStatus: { isStarred: null, ghConfigured: false, isLoading: false },
    });
    await useDataStore.getState().toggleGitHubStar();
    expect(api.toggleGitHubStar).not.toHaveBeenCalled();
  });
});

// Sanity: the facade's getState merge relies on the store keeping its action identity.
it('exposes a stable initial action set', () => {
  expect(typeof initial.loadRecipes).toBe('function');
});
