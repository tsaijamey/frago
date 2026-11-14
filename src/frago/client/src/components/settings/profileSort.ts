import type { ProfileItem } from '@/api';

export type ProfileSortOrder = 'asc' | 'desc';

export const PROFILE_SORT_STORAGE_KEY = 'frago.settings.profiles.sortOrder';

export function readProfileSortOrder(): ProfileSortOrder {
  try {
    const raw = window.localStorage.getItem(PROFILE_SORT_STORAGE_KEY);
    return raw === 'desc' ? 'desc' : 'asc';
  } catch {
    return 'asc';
  }
}

export function writeProfileSortOrder(order: ProfileSortOrder): void {
  try {
    window.localStorage.setItem(PROFILE_SORT_STORAGE_KEY, order);
  } catch {
    // Ignore storage unavailable / quota errors
  }
}

/**
 * Compare two profiles by their user-visible name with case-insensitive,
 * natural numeric, and locale-aware collation, using `id` as a deterministic
 * tie-breaker.
 */
export function compareProfileNames(
  a: Pick<ProfileItem, 'name' | 'id'>,
  b: Pick<ProfileItem, 'name' | 'id'>,
  order: ProfileSortOrder = 'asc',
): number {
  const nameA = (a.name ?? '').trim();
  const nameB = (b.name ?? '').trim();
  const cmp = nameA.localeCompare(nameB, undefined, {
    numeric: true,
    sensitivity: 'base',
  });
  const resolved =
    cmp !== 0
      ? cmp
      : (a.id ?? '').localeCompare(b.id ?? '', undefined, {
          numeric: true,
          sensitivity: 'base',
        });
  return order === 'desc' ? -resolved : resolved;
}

export function sortProfilesByName<T extends Pick<ProfileItem, 'name' | 'id'>>(
  profiles: readonly T[],
  order: ProfileSortOrder = 'asc',
): T[] {
  return [...profiles].sort((a, b) => compareProfileNames(a, b, order));
}

/**
 * Extract a concise endpoint label (host[:port]) for `custom` providers so
 * rows do not all collapse to an indistinguishable `custom` tag.
 */
export function formatProviderMetaEndpoint(profile: Pick<ProfileItem, 'endpoint_type' | 'url' | 'channels'>): string {
  if (profile.endpoint_type !== 'custom') {
    return profile.endpoint_type;
  }
  const rawUrl =
    profile.url ||
    profile.channels?.find((ch) => Boolean(ch.url))?.url ||
    null;
  if (!rawUrl) {
    return profile.endpoint_type;
  }
  try {
    const parsed = new URL(rawUrl);
    return parsed.host || profile.endpoint_type;
  } catch {
    return profile.endpoint_type;
  }
}
