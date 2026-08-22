/**
 * 这个对话框是普通用户配 API 的唯一入口——CLI 那边 `frago profile` 明说了只读，
 * 增删改激活全在这儿。所以这里测的不是「组件渲染没渲染」，而是三件在真机上
 * 咬过人的事：
 *
 * 1. 端点清单曾经是手抄的，抄漏了腾讯两家，手里拿着腾讯 key 的人在界面上根本
 *    找不到位置可填；
 * 2. 保存时会把空字段整个丢掉，于是「删掉模型覆盖」这个动作提示保存成功、
 *    重新打开又原样躺在那儿；
 * 3. 从自定义地址切回预设端点后，那条旧地址没人清，继续挂在卡片上。
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('@/stores/appStore', () => ({
  useAppStore: (selector: (s: { showToast: () => void }) => unknown) =>
    selector({ showToast: () => {} }),
}));

const getProfiles = vi.fn();
const getEndpointPresets = vi.fn();
const updateProfile = vi.fn();
const createProfile = vi.fn();

vi.mock('@/api', () => ({
  getProfiles: () => getProfiles(),
  getEndpointPresets: () => getEndpointPresets(),
  createProfile: (data: unknown) => createProfile(data),
  updateProfile: (id: string, data: unknown) => updateProfile(id, data),
  deleteProfile: vi.fn(),
  activateProfile: vi.fn(),
  deactivateProfile: vi.fn(),
  saveCurrentAsProfile: vi.fn(),
}));

import ProfileManager from '../ProfileManager';

const PRESETS = [
  {
    id: 'deepseek',
    display_name: 'DeepSeek (deepseek-chat)',
    base_url: 'https://api.deepseek.com/anthropic',
    default_model: 'deepseek-reason',
    sonnet_model: 'deepseek-reason',
    haiku_model: 'deepseek-chat',
  },
  {
    id: 'tencent_maas',
    display_name: 'Tencent Cloud MaaS (Hunyuan)',
    base_url: 'https://tokenhub.tencentmaas.com',
    default_model: 'Hy3-dev0630',
    sonnet_model: 'Hy3-dev0630',
    haiku_model: 'Hy3-dev0630',
  },
];

const CUSTOM_PROFILE = {
  id: 'p1',
  name: 'OpenRouter',
  endpoint_type: 'custom',
  api_key_masked: 'sk-o****9048',
  url: 'https://openrouter.ai/api',
  default_model: 'xiaomi/mimo-v2-pro',
  sonnet_model: null,
  haiku_model: null,
  is_active: false,
  created_at: '2026-03-31T12:46:14',
  updated_at: '2026-03-31T12:46:14',
};

function open(onProfilesChanged = vi.fn()) {
  render(
    <ProfileManager isOpen onClose={() => {}} onProfilesChanged={onProfilesChanged} />,
  );
  return onProfilesChanged;
}

/** Walk from the list into the edit form of the one saved profile. */
async function openEditForm() {
  await screen.findByText('OpenRouter');
  fireEvent.click(screen.getByTitle('settings.profiles.edit'));
  return (await screen.findByLabelText(/settings\.profiles\.profileName/)) as HTMLInputElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  getEndpointPresets.mockResolvedValue({ presets: PRESETS });
  getProfiles.mockResolvedValue({ profiles: [CUSTOM_PROFILE], active_profile_id: null });
  updateProfile.mockResolvedValue({ status: 'ok' });
  createProfile.mockResolvedValue({ status: 'ok' });
});

describe('端点清单', () => {
  it('后端支持的端点都能在下拉里选到', async () => {
    open();
    await openEditForm();

    const options = Array.from(
      screen.getByLabelText('settings.profiles.endpointType').querySelectorAll('option'),
    ).map((o) => o.getAttribute('value'));

    expect(options).toEqual(['deepseek', 'tencent_maas', 'custom']);
  });

  it('预设端点把自己实际要用的模型摆在输入框里当提示', async () => {
    open();
    await openEditForm();

    fireEvent.change(screen.getByLabelText('settings.profiles.endpointType'), {
      target: { value: 'deepseek' },
    });

    expect(
      screen.getByLabelText(/settings\.profiles\.defaultModel/).getAttribute('placeholder'),
    ).toBe('deepseek-reason');
  });
});

describe('保存一次编辑', () => {
  it('清空模型覆盖真的会清空，而不是被当成没改', async () => {
    open();
    await openEditForm();

    fireEvent.change(screen.getByLabelText(/settings\.profiles\.defaultModel/), {
      target: { value: '' },
    });
    fireEvent.click(screen.getByText('settings.profiles.save'));

    await waitFor(() => expect(updateProfile).toHaveBeenCalled());
    expect(updateProfile.mock.calls[0][1]).toMatchObject({ default_model: null });
  });

  it('没填新密钥就不提密钥，保存的那把不会被空串顶掉', async () => {
    open();
    await openEditForm();
    fireEvent.click(screen.getByText('settings.profiles.save'));

    await waitFor(() => expect(updateProfile).toHaveBeenCalled());
    expect(updateProfile.mock.calls[0][1]).not.toHaveProperty('api_key');
  });

  it('从自定义地址切到预设端点，旧地址跟着清掉', async () => {
    open();
    await openEditForm();

    fireEvent.change(screen.getByLabelText('settings.profiles.endpointType'), {
      target: { value: 'tencent_maas' },
    });
    fireEvent.click(screen.getByText('settings.profiles.save'));

    await waitFor(() => expect(updateProfile).toHaveBeenCalled());
    expect(updateProfile.mock.calls[0][1]).toMatchObject({
      endpoint_type: 'tencent_maas',
      url: null,
    });
  });

  it('存完通知外面那一层，设置页不会继续显示旧的', async () => {
    const onProfilesChanged = open();
    await openEditForm();
    fireEvent.click(screen.getByText('settings.profiles.save'));

    await waitFor(() => expect(onProfilesChanged).toHaveBeenCalled());
  });
});
