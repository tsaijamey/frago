/**
 * 这张卡回答的是「我的主 agent 和我起的 worker，各自跑在哪条连接上」。
 * 它替掉的旧卡片只说得出一句「正在使用 Claude Code 官方 API」——单主语，
 * 而 worker 早就可以跑在别处，界面上却没有任何位置能看到、能改。
 *
 * 这里钉三件事：
 *
 * 1. 两个角色各是一行，各改各的——改 worker 那一行 NEVER 顺手动到主 agent；
 * 2. 厂商 CLI（跑自己账号的那类）在主 agent 那一行是列出来且禁用的，
 *    连同禁用的理由——选项直接消失会被读成 bug，而不是一个决定；
 * 3. 后端拒绝时把它那句话原样显示，因为那句话本来就是写给人看的。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const bindRole = vi.fn();

vi.mock('@/api', () => ({
  bindRole: (role: string, profileId: string, targets?: string[]) =>
    bindRole(role, profileId, targets),
}));

import ConnectionRolesCard from '../ConnectionRolesCard';
import type { ProfileItem, RoleBinding } from '@/api';

const official: ProfileItem = {
  id: 'official',
  name: 'Official subscription',
  kind: 'official',
  endpoint_type: 'official',
  api_key_masked: '',
  is_active: false,
  created_at: '',
  updated_at: '',
};

const deepseek: ProfileItem = {
  id: 'prof0001',
  name: 'DeepSeek',
  kind: 'endpoint',
  endpoint_type: 'deepseek',
  api_key_masked: 'sk-a****b',
  default_model: 'deepseek-v4-flash',
  is_active: false,
  created_at: '',
  updated_at: '',
};

const workbuddy: ProfileItem = {
  id: 'vend0001',
  name: 'WorkBuddy hy4',
  kind: 'vendor_cli',
  endpoint_type: 'vendor_cli',
  api_key_masked: '',
  agent_type: 'codebuddy',
  default_model: 'hy4-preview',
  is_active: false,
  created_at: '',
  updated_at: '',
};

const bindings: RoleBinding[] = [
  { role: 'main', profile_id: null, connection: official, targets: [] },
  { role: 'worker', profile_id: null, connection: official, targets: [] },
];

function renderCard(overrides: Partial<Parameters<typeof ConnectionRolesCard>[0]> = {}) {
  const onBindingChanged = vi.fn();
  render(
    <ConnectionRolesCard
      connections={[official, deepseek, workbuddy]}
      bindings={bindings}
      coreNames={{ codebuddy: 'CodeBuddy Code', claude: 'Claude Code' }}
      onManageProfiles={() => {}}
      onBindingChanged={onBindingChanged}
      {...overrides}
    />,
  );
  return { onBindingChanged };
}

describe('ConnectionRolesCard', () => {
  beforeEach(() => {
    bindRole.mockReset();
    bindRole.mockResolvedValue({ status: 'ok' });
  });

  it('每个角色一行，各自一个选择器', () => {
    renderCard();

    expect(screen.getByLabelText('settings.connections.mainRole')).toBeTruthy();
    expect(screen.getByLabelText('settings.connections.workerRole')).toBeTruthy();
  });

  it('改 worker 那一行只动 worker', async () => {
    const { onBindingChanged } = renderCard();

    fireEvent.change(screen.getByLabelText('settings.connections.workerRole'), {
      target: { value: 'vend0001' },
    });

    await waitFor(() => expect(bindRole).toHaveBeenCalledTimes(1));
    expect(bindRole).toHaveBeenCalledWith('worker', 'vend0001', undefined);
    await waitFor(() => expect(onBindingChanged).toHaveBeenCalled());
  });

  it('厂商 CLI 在主 agent 那一行列出但不可选', () => {
    renderCard();

    const mainRow = screen.getByLabelText('settings.connections.mainRole');
    const workerRow = screen.getByLabelText('settings.connections.workerRole');
    const inMain = Array.from(mainRow.querySelectorAll('option')).find(
      (o) => o.value === 'vend0001',
    );
    const inWorker = Array.from(workerRow.querySelectorAll('option')).find(
      (o) => o.value === 'vend0001',
    );

    expect(inMain?.disabled).toBe(true);
    expect(inMain?.textContent).toContain('settings.connections.vendorNotForMain');
    expect(inWorker?.disabled).toBe(false);
  });

  it('后端拒绝时原样显示它那句话', async () => {
    bindRole.mockResolvedValue({ status: 'error', error: 'runs on its own account' });
    renderCard();

    fireEvent.change(screen.getByLabelText('settings.connections.workerRole'), {
      target: { value: 'prof0001' },
    });

    await waitFor(() => expect(screen.getByText('runs on its own account')).toBeTruthy());
  });

  it('主 agent 那一行说得出这条连接写进了谁的配置', () => {
    renderCard({
      bindings: [
        { role: 'main', profile_id: 'prof0001', connection: deepseek, targets: ['claude'] },
        { role: 'worker', profile_id: null, connection: official, targets: [] },
      ],
    });

    expect(screen.getByText(/Claude Code/)).toBeTruthy();
  });

  it('worker 跑厂商 CLI 时，把模型和内核一起说出来', () => {
    renderCard({
      bindings: [
        { role: 'main', profile_id: null, connection: official, targets: [] },
        { role: 'worker', profile_id: 'vend0001', connection: workbuddy, targets: [] },
      ],
    });

    // 内核名在选项里也出现一次，这里只关心那一行说明确实带上了它。
    expect(screen.getByText(/hy4-preview/).textContent).toContain('CodeBuddy Code');
  });
});

describe('ConnectionRolesCard · frago-core 替它们问模型的两行', () => {
  const borrowed: ProfileItem = {
    id: 'wb000001',
    name: 'WorkBuddy flash',
    kind: 'workbuddy',
    endpoint_type: 'workbuddy',
    api_key_masked: '',
    default_model: 'deepseek-v4-flash',
    is_active: false,
    created_at: '',
    updated_at: '',
  };
  const four: RoleBinding[] = [
    { role: 'main', profile_id: null, connection: official, targets: [] },
    { role: 'worker', profile_id: null, connection: official, targets: [] },
    { role: 'lightagent', profile_id: null, connection: deepseek, targets: [] },
    { role: 'observer', profile_id: null, connection: null, targets: [] },
  ];
  const renderFour = (overrides: Partial<Parameters<typeof ConnectionRolesCard>[0]> = {}) =>
    renderCard({ connections: [official, deepseek, workbuddy, borrowed], bindings: four, ...overrides });
  const optionIn = (row: string, value: string) =>
    Array.from(screen.getByLabelText(row).querySelectorAll('option')).find((o) => o.value === value);

  beforeEach(() => {
    bindRole.mockReset();
    bindRole.mockResolvedValue({ status: 'ok' });
  });

  it('四个角色各一行', () => {
    renderFour();
    for (const role of ['main', 'worker', 'lightagent', 'observer']) {
      expect(screen.getByLabelText(`settings.connections.${role}Role`)).toBeTruthy();
    }
  });

  it('订阅不在这两行里，第一项是解除绑定', () => {
    renderFour();
    const row = screen.getByLabelText('settings.connections.observerRole') as HTMLSelectElement;
    const values = Array.from(row.querySelectorAll('option')).map((o) => o.value);
    expect(values[0]).toBe('');
    expect(values).not.toContain('official');
    expect(row.value).toBe('');
  });

  it('CLI 自带登录在这两行列出但不可选，并说明原因', () => {
    renderFour();
    const opt = optionIn('settings.connections.lightagentRole', 'vend0001');
    expect(opt?.disabled).toBe(true);
    expect(opt?.textContent).toContain('settings.connections.notForFragoCore');
  });

  it('借用 WorkBuddy 登录只在这两行可选', () => {
    renderFour();
    for (const row of ['settings.connections.mainRole', 'settings.connections.workerRole']) {
      const opt = optionIn(row, 'wb000001');
      expect(opt?.disabled).toBe(true);
      expect(opt?.textContent).toContain('settings.connections.fragoCoreOnly');
    }
    expect(optionIn('settings.connections.observerRole', 'wb000001')?.disabled).toBe(false);
  });

  it('选回第一项就是解除绑定', async () => {
    renderFour({
      bindings: [
        ...four.slice(0, 3),
        { role: 'observer', profile_id: 'wb000001', connection: borrowed, targets: [] },
      ],
    });
    fireEvent.change(screen.getByLabelText('settings.connections.observerRole'), {
      target: { value: '' },
    });
    await waitFor(() => expect(bindRole).toHaveBeenCalledWith('observer', '', undefined));
  });

  it('轻量 ai 没单独绑时说出它跟随的是哪一条', () => {
    renderFour();
    expect(screen.getByText(/settings.connections.followingDefault/).textContent).toContain(
      'deepseek-v4-flash',
    );
  });
});
