import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import EmployeeAvatar from '../EmployeeAvatar';
import EmployeeAvatarModal from '../EmployeeAvatarModal';
import AboutSettings from '../../settings/AboutSettings';
import SettingsPage from '../../settings/SettingsPage';
import { useDataStore } from '@/stores/dataStore';
import {
  AVATAR_BG_PALETTE,
  defaultAvatarSpec,
  generateMicahDataUri,
  validateAvatarFileClient,
} from '@/utils/employeeAvatar';
import type { EmployeeItem } from '@/types/api';

const mockFetch = vi.fn();

function makeEmployee(overrides: Partial<EmployeeItem> = {}): EmployeeItem {
  const id = overrides.member_post_id ?? 'frago-pm';
  const def = defaultAvatarSpec(id);
  return {
    member_post_id: id,
    title: '产品负责人',
    agent_kernel: 'claude',
    description: '统筹人机协同演进',
    avatar: {
      kind: 'default',
      seed: def.seed,
      bg_color: def.bg_color,
      palette_id: def.palette_id,
      mime_type: null,
      updated_at: '',
    },
    avatar_resolved: {
      kind: 'default',
      effective_kind: 'default',
      seed: def.seed,
      bg_color: def.bg_color,
      palette_id: def.palette_id,
      mime_type: null,
      upload_url: null,
      fallback_reason: null,
      updated_at: '',
    },
    ...overrides,
  };
}

describe('EmployeeAvatar & DiceBear Micah system', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetch);
    mockFetch.mockReset();
    useDataStore.setState({ employees: [makeEmployee()] });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('generates deterministic offline Micah data URI and 8-color architectural palette', () => {
    expect(AVATAR_BG_PALETTE).toHaveLength(8);
    const s1 = defaultAvatarSpec('frago-dev');
    const s2 = defaultAvatarSpec('frago-dev');
    expect(s1).toEqual(s2);
    expect(AVATAR_BG_PALETTE.some((p) => p.hex === s1.bg_color)).toBe(true);

    const uri = generateMicahDataUri(s1.seed, s1.bg_color);
    expect(uri.startsWith('data:image/svg+xml;utf8,')).toBe(true);
    expect(decodeURIComponent(uri)).toContain('<svg');
  });

  it('renders isolated <img> data URI and falls back cleanly on broken upload image error', () => {
    const brokenEmp = makeEmployee({
      member_post_id: 'broken-bot',
      avatar_resolved: {
        kind: 'upload',
        effective_kind: 'upload',
        seed: 'broken-bot',
        bg_color: '#e8edf3',
        palette_id: 'mist-blue',
        mime_type: 'image/png',
        upload_url: '/api/employees/broken-bot/avatar/file?v=bad',
        fallback_reason: null,
        updated_at: '2026-11-28T00:00:00Z',
      },
    });
    useDataStore.setState({ employees: [brokenEmp] });

    render(<EmployeeAvatar employeeId="broken-bot" size={48} testId="emp-av-broken" />);
    const container = screen.getByTestId('emp-av-broken');
    const img = container.querySelector('img') as HTMLImageElement;
    expect(img).toBeTruthy();
    expect(img.getAttribute('src')).toContain('/api/employees/broken-bot/avatar/file');

    // Simulate broken image load failure -> automatically falls back to deterministic Micah data URI
    fireEvent.error(img);
    expect(img.getAttribute('src')?.startsWith('data:image/svg+xml;utf8,')).toBe(true);
  });

  it('modal supports 4x2 shuffle, 4-size live preview, client validation, cancel/ESC/backdrop isolation, and 3-way store sync on save', async () => {
    const emp = makeEmployee({ member_post_id: 'frago-pm', title: '产品负责人' });
    useDataStore.setState({ employees: [emp] });
    const onClose = vi.fn();

    render(
      <div>
        {/* Simulated 3 locations across WebUI: rail 24px, header 28px, employee card 48px */}
        <EmployeeAvatar employeeId="frago-pm" size={24} statusBadge="running" testId="loc-rail" />
        <EmployeeAvatar employeeId="frago-pm" size={28} testId="loc-header" />
        <EmployeeAvatar employeeId="frago-pm" size={48} testId="loc-card" />
        <EmployeeAvatarModal
          employee={{
            member_post_id: emp.member_post_id,
            title: emp.title ?? emp.member_post_id,
            avatar_resolved: emp.avatar_resolved,
          }}
          onClose={onClose}
        />
      </div>
    );

    const railImg = () => screen.getByTestId('loc-rail').querySelector('img') as HTMLImageElement;
    const headerImg = () => screen.getByTestId('loc-header').querySelector('img') as HTMLImageElement;
    const cardImg = () => screen.getByTestId('loc-card').querySelector('img') as HTMLImageElement;
    const initialSrc = railImg().getAttribute('src');
    expect(headerImg().getAttribute('src')).toBe(initialSrc);
    expect(cardImg().getAttribute('src')).toBe(initialSrc);

    // 4-size live preview elements exist (72 / 48 / 28 / 24px)
    expect(screen.getByTestId('avatar-preview-main')).toBeTruthy();
    expect(screen.getByTestId('avatar-preview-48')).toBeTruthy();
    expect(screen.getByTestId('avatar-preview-28')).toBeTruthy();
    expect(screen.getByTestId('avatar-preview-24')).toBeTruthy();

    // 4x2 grid has 8 candidates; shuffle changes batch & candidate keys
    const grid = screen.getByTestId('avatar-candidate-grid');
    expect(grid.getAttribute('data-batch')).toBe('0');
    const firstKeyBatch0 = screen.getByTestId('avatar-cand-0').getAttribute('data-cand-key');
    fireEvent.click(screen.getByTestId('avatar-shuffle-btn'));
    expect(grid.getAttribute('data-batch')).toBe('1');
    const firstKeyBatch1 = screen.getByTestId('avatar-cand-0').getAttribute('data-cand-key');
    expect(firstKeyBatch1).not.toBe(firstKeyBatch0);

    // Pick candidate 2 -> updates all 4 previews immediately, but does NOT mutate the 3 live page locations yet
    fireEvent.click(screen.getByTestId('avatar-cand-2'));
    const chosenCandKey = screen.getByTestId('avatar-cand-2').getAttribute('data-cand-key')!;
    const [chosenSeed, chosenBg] = chosenCandKey.split('|');

    const preview72Src = screen.getByTestId('avatar-preview-main').querySelector('img')?.getAttribute('src');
    const preview48Src = screen.getByTestId('avatar-preview-48').querySelector('img')?.getAttribute('src');
    const preview28Src = screen.getByTestId('avatar-preview-28').querySelector('img')?.getAttribute('src');
    const preview24Src = screen.getByTestId('avatar-preview-24').querySelector('img')?.getAttribute('src');
    expect(preview72Src).toBe(preview48Src);
    expect(preview48Src).toBe(preview28Src);
    expect(preview28Src).toBe(preview24Src);
    expect(preview72Src).not.toBe(initialSrc);
    expect(railImg().getAttribute('src')).toBe(initialSrc);

    // Client-side upload validation blocks SVG & oversized files
    const svgFile = new File(['<svg></svg>'], 'evil.svg', { type: 'image/svg+xml' });
    expect(validateAvatarFileClient(svgFile).ok).toBe(false);
    const hugeFile = new File([new Uint8Array(2 * 1024 * 1024 + 10)], 'huge.png', { type: 'image/png' });
    expect(validateAvatarFileClient(hugeFile).ok).toBe(false);

    const fileInput = screen.getByTestId('avatar-file-input') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [svgFile] } });
    expect(await screen.findByTestId('avatar-modal-error')).toBeTruthy();

    // Cancel / ESC / backdrop trigger onClose without mutating store or calling fetch
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('avatar-modal-backdrop'));
    expect(onClose).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByTestId('avatar-cancel-btn'));
    expect(onClose).toHaveBeenCalledTimes(3);
    expect(mockFetch).not.toHaveBeenCalled();

    // Save built-in Micah selection -> PUT persists & updates all 3 page locations live via store
    const savedEmployee = makeEmployee({
      member_post_id: 'frago-pm',
      avatar: {
        kind: 'micah',
        seed: chosenSeed,
        bg_color: chosenBg,
        palette_id: 'oat',
        mime_type: null,
        updated_at: '2026-11-28T12:00:00Z',
      },
      avatar_resolved: {
        kind: 'micah',
        effective_kind: 'micah',
        seed: chosenSeed,
        bg_color: chosenBg,
        palette_id: 'oat',
        mime_type: null,
        upload_url: null,
        fallback_reason: null,
        updated_at: '2026-11-28T12:00:00Z',
      },
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => savedEmployee,
    });

    fireEvent.click(screen.getByTestId('avatar-save-btn'));
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/employees/frago-pm/avatar',
        expect.objectContaining({ method: 'PUT' })
      );
    });

    await waitFor(() => {
      expect(railImg().getAttribute('src')).toBe(preview72Src);
      expect(headerImg().getAttribute('src')).toBe(preview72Src);
      expect(cardImg().getAttribute('src')).toBe(preview72Src);
    });
  });

  it('renders compliance attribution in both Settings bottom bar and About card', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        current_frago_version: '0.1.50',
        resources_version: '1.0.0',
      }),
    });

    const { unmount } = render(<AboutSettings />);
    const aboutCard = screen.getByTestId('settings-avatar-attribution');
    expect(aboutCard.textContent).toContain('Avatar Illustration System by Micah Lanier (CC BY 4.0)');
    expect(aboutCard.textContent).toContain('DiceBear (MIT)');
    unmount();

    render(<SettingsPage />);
    const snavAttr = screen.getByTestId('settings-snav-attribution');
    expect(snavAttr.textContent).toContain('Avatar Illustration System by Micah Lanier (CC BY 4.0)');
    expect(snavAttr.textContent).toContain('DiceBear (MIT)');
  });
});
