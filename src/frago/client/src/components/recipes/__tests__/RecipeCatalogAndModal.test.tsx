import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import i18n from '@/i18n';
import { useRecipeAppPins } from '@/stores/recipeAppPins';
import RecipeList from '../RecipeList';
import RecipeRunModal from '../RecipeRunModal';

const loadRecipes = vi.fn();
const loadCommunityRecipes = vi.fn();
const switchPage = vi.fn();
const showToast = vi.fn();
const getRecipeDetail = vi.fn();
const runRecipe = vi.fn();
const runRecipeAsync = vi.fn();

const mockStoreState = {
  recipes: [
    {
      name: 'daily_brief',
      title: { en: 'Daily Brief', 'zh-CN': '每日简报' },
      description: 'Interactive briefing app',
      category: 'workflow' as const,
      runtime: 'python',
      tags: ['interactive', 'report'],
      has_page: true,
    },
    {
      name: 'fetch_news',
      title: { en: 'Fetch News', 'zh-CN': '抓取新闻' },
      description: 'Atomic fetcher',
      category: 'atomic' as const,
      runtime: 'node',
      tags: ['web'],
    },
  ],
  communityRecipes: [
    {
      name: 'community_demo',
      title: { en: 'Community Demo' },
      description: 'Shared recipe',
      category: 'atomic' as const,
      runtime: 'python',
      tags: [],
      installed: false,
    },
  ],
  loadRecipes,
  loadCommunityRecipes,
  switchPage,
  showToast,
};

vi.mock('@/stores/appStore', () => ({
  useAppStore: (selector?: (s: typeof mockStoreState) => unknown) =>
    selector ? selector(mockStoreState) : mockStoreState,
}));

vi.mock('@/stores/recipeFolders', () => ({
  useRecipeFolders: () => ({
    folders: [],
    error: null,
    trouble: null,
    load: vi.fn(),
    create: vi.fn(),
    rename: vi.fn(),
    remove: vi.fn(),
    assign: vi.fn(),
    clearError: vi.fn(),
  }),
  suggestFolderId: (name: string) => name.toLowerCase(),
}));

vi.mock('@/api', () => ({
  getRecipeDetail: (name: string) => getRecipeDetail(name),
  runRecipe: (name: string, params?: Record<string, unknown>) => runRecipe(name, params),
  runRecipeAsync: (name: string, params?: Record<string, unknown>) => runRecipeAsync(name, params),
  checkGhCli: vi.fn().mockResolvedValue({ installed: true, authenticated: true }),
}));

vi.mock('../CommunityRecipeList', () => ({
  default: ({ search }: { search: string }) => (
    <div data-testid="community-recipe-list">community:{search}</div>
  ),
}));

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

beforeEach(() => {
  vi.clearAllMocks();
  useRecipeAppPins.setState({ pins: ['daily_brief'] });
});

describe('P2-2 Recipes Catalog vs Pinned Apps & Schema Form Modal', () => {
  it('页头提供 Catalog (含 Local/Community) 与 Pinned Apps 顶层分段切换', () => {
    render(<RecipeList />);

    expect(screen.getByTestId('recipes-view-catalog').getAttribute('aria-selected')).toBe('true');
    expect(screen.getByTestId('recipe-source-local').getAttribute('aria-selected')).toBe('true');
    expect(screen.getByText('Daily Brief')).toBeTruthy();

    fireEvent.click(screen.getByTestId('recipe-source-community'));
    expect(screen.getByTestId('community-recipe-list')).toBeTruthy();

    fireEvent.click(screen.getByTestId('recipes-view-pinned'));
    expect(screen.getByTestId('recipes-pinned-view')).toBeTruthy();
    expect(screen.getByTestId('pinned-app-daily_brief')).toBeTruthy();
  });

  it('RecipeRunModal 使用 .rcp-run-modal 与 .rcp-form-row 渲染多类型表单并提交结构化参数', async () => {
    getRecipeDetail.mockResolvedValue({
      name: 'demo_recipe',
      description: 'Test schema form',
      category: 'atomic',
      runtime: 'python',
      tags: [],
      inputs: {
        mode: {
          type: 'enum',
          required: true,
          description: 'Run mode',
          options: ['fast', 'deep'],
        },
        retries: {
          type: 'integer',
          required: false,
          default: 2,
          description: 'Retry count',
        },
        dry_run: {
          type: 'boolean',
          required: false,
          default: false,
        },
        api_token: {
          type: 'secret',
          required: true,
          description: 'Secret token',
        },
        targets: {
          type: 'array',
          required: false,
          default: ['alpha'],
        },
        headers: {
          type: 'object',
          required: false,
          default: { env: 'prod' },
        },
      },
    });
    runRecipe.mockResolvedValue({ status: 'ok' });

    const onClose = vi.fn();
    const { container } = render(<RecipeRunModal recipeName="demo_recipe" onClose={onClose} />);

    await screen.findByText('Test schema form');
    expect(container.querySelector('.rcp-run-modal')).toBeTruthy();
    expect(container.querySelectorAll('.rcp-form-row').length).toBe(6);
    expect(container.querySelectorAll('.rcp-form-row .tp').length).toBeGreaterThanOrEqual(6);
    expect(container.querySelectorAll('.rcp-form-row .req').length).toBe(2);

    fireEvent.click(screen.getByRole('radio', { name: 'deep' }));
    fireEvent.change(screen.getByLabelText(/api_token/i), { target: { value: 'tok-123' } });
    fireEvent.click(screen.getByRole('switch'));

    fireEvent.click(screen.getByRole('button', { name: /run/i }));

    await waitFor(() =>
      expect(runRecipe).toHaveBeenCalledWith('demo_recipe', {
        mode: 'deep',
        retries: 2,
        dry_run: true,
        api_token: 'tok-123',
        targets: ['alpha'],
        headers: { env: 'prod' },
      }),
    );
    expect(onClose).toHaveBeenCalled();
  });
});
