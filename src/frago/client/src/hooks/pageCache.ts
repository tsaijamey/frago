/**
 * 最近一次从服务端拿到手的数据，记在网页级别，不跟着组件走。
 *
 * 哪个环节出事：会话页一切去别的菜单就整个卸掉，左栏的会话清单、分组、置顶、已读记录
 * 全跟着没了。回来时从空白开局，服务端那几份回来之前，左栏先摆出一张没有分组、没有置顶
 * 区的平铺清单，隔一会儿才重新归进各组——「未分组」那一区在人眼前消失又出现，正选着的
 * 那一场也在清单里跳位置。
 *
 * 所以回来时先摆上次那份，同时照常重取；取回来的替换它。刷新网页就清空，这不是本地存储。
 */

const registry = new Set<{ value: unknown }>();

export interface PageCache<T> {
  get: () => T | null;
  set: (value: T) => void;
}

export function pageCache<T>(): PageCache<T> {
  const slot: { value: unknown } = { value: null };
  registry.add(slot);
  return {
    get: () => slot.value as T | null,
    set: (value) => {
      slot.value = value;
    },
  };
}

/** 回到「网页刚打开、什么都还没取过」的样子。测试每个用例前调一次，用例之间不串。 */
export function resetPageCaches(): void {
  for (const slot of registry) slot.value = null;
}
