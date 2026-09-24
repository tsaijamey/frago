/**
 * 左栏用例共用的替身。
 *
 * 左栏自己不再持有「看过没」与「For you」——那两份由页面那一层持有，页头也要读。用例里
 * 不关心这两件事时，照这里给的空替身摆：一场都没看过、一场都不挂 For you、没有可关的终端。
 */

import { vi } from 'vitest';
import SessionRail, { type SessionRailProps } from '../SessionRail';
import type { SessionViewsState } from '@/hooks/useSessionViews';
import type { ForYouInfo, ForYouState } from '@/hooks/useForYou';
import type { TmuxWaitingItem } from '@/types/api';

export function fakeViews(over: Partial<SessionViewsState> = {}): SessionViewsState {
  return {
    viewedAt: () => undefined,
    isInTmux: (s) => s.in_tmux === true,
    markViewed: vi.fn(),
    ...over,
  };
}

export function fakeForYou(
  infos: Record<string, ForYouInfo> = {},
  over: Partial<ForYouState> = {}
): ForYouState {
  return {
    infoOf: (id) => infos[id] ?? null,
    count: Object.keys(infos).length,
    closable: [] as TmuxWaitingItem[],
    rows: [],
    suppress: vi.fn(),
    refresh: vi.fn(),
    ...over,
  };
}

type RailProps = Omit<SessionRailProps, 'views' | 'forYou'> &
  Partial<Pick<SessionRailProps, 'views' | 'forYou'>>;

/** 带好两份替身的左栏。 */
export function TestRail({ views, forYou, ...rest }: RailProps) {
  return <SessionRail views={views ?? fakeViews()} forYou={forYou ?? fakeForYou()} {...rest} />;
}
