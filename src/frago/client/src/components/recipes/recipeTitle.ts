/**
 * 一张配方在界面上该显示的名字。
 *
 * `name` 一直在当两样东西用：它是标识——进目录名、进命令行、进依赖声明，只能是字
 * 母数字下划线；它又被这里拿去当标题，把下划线换成空格显示完事。作者写了 `title`
 * 之后，标题就有了自己的字段，改标题不再惊动任何引用 `name` 的地方；没写的照旧，
 * 存量配方一张都不用改。
 *
 * 回落顺序：当前语言 → 中文 → 英文 → `name` 换掉下划线。
 *
 * 服务端那边同一套规则写在 `frago.recipes.metadata.display_title`。两处都要有，是
 * 因为界面在本地切中英、不会为换一门语言回服务端要一次数据；两处必须一起改。
 */

import type { RecipeItem } from '@/types/pywebview';

const LANGS = ['zh-CN', 'en'] as const;

/** i18n 的语言码（`zh` / `en`）换成标题里用的键（`zh-CN` / `en`）。 */
export function titleLang(lang: string): string {
  return lang.startsWith('zh') ? 'zh-CN' : 'en';
}

export function recipeTitle(
  recipe: Pick<RecipeItem, 'name' | 'title'>,
  lang = 'zh-CN',
): string {
  const title = recipe.title ?? {};
  for (const key of [titleLang(lang), ...LANGS]) {
    const text = title[key];
    if (text) return text;
  }
  return recipe.name.replace(/_/g, ' ');
}

/** 文件夹的显示名，同一套回落，最后落到 id 上。 */
export function folderLabel(
  folder: { id: string; name: Record<string, string> },
  lang = 'zh-CN',
): string {
  for (const key of [titleLang(lang), ...LANGS]) {
    const text = folder.name[key];
    if (text) return text;
  }
  return folder.id;
}
