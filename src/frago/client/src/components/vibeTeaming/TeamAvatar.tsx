/**
 * 两侧的头像。归属靠整块说话：我这一侧是实心中性，队友那一侧是冷色。
 * 身份头、输入框标题行、请求卡、队友请求块都用这一个，两处长得不一样，人就对不上号。
 */

import { User, Users } from 'lucide-react';

export default function TeamAvatar({
  who,
  size = 'md',
}: {
  who: 'me' | 'peer';
  size?: 'md' | 'sm';
}) {
  const box = size === 'md' ? 'h-[26px] w-[26px]' : 'h-[18px] w-[18px]';
  const icon = size === 'md' ? 14 : 11;
  const tone =
    who === 'me'
      ? 'bg-text-primary text-bg-primary'
      : 'bg-[var(--peer-chip)] text-[var(--peer-ink)]';
  return (
    <span
      aria-hidden
      data-avatar={who}
      className={`flex shrink-0 items-center justify-center rounded-full ${box} ${tone}`}
    >
      {who === 'me' ? (
        <User size={icon} strokeWidth={1.75} />
      ) : (
        <Users size={icon} strokeWidth={1.75} />
      )}
    </span>
  );
}
