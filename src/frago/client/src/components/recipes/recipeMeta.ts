/**
 * 配方卡底那一行：类型 → 运行时 → 标签。
 *
 * 卡上不再出现标识名（`name`）和来源（User / System）：标识名与标题几乎逐字相同，
 * 只是空格换成了下划线；来源在详情页里有。这一页的读者要知道的是「它是哪一类、在
 * 什么上面跑、跟什么有关」。标识名仍参与搜索，卡上不显示也照样搜得到。
 *
 * 类型在工作流、原子两段里与段标题重复，但文件夹展开后两类是混放的，那时它是唯一
 * 能区分两类的地方，所以每张都挂，不按所在位置增减。
 */

import type { RecipeItem } from '@/types/pywebview';

/** 卡底最多摆几个标签。放不下的截断，不显示「+N」。 */
export const CARD_TAG_LIMIT = 3;

export interface RecipeCardMeta {
  kindLabel: string;
  /** 没有运行时就是 null，这一项不占位。 */
  runtime: string | null;
  tags: string[];
}

export function recipeCardMeta(
  recipe: Pick<RecipeItem, 'category' | 'runtime' | 'tags'>,
  t: (key: string) => string,
): RecipeCardMeta {
  return {
    kindLabel: recipe.category === 'workflow' ? t('recipes.workflow') : t('recipes.atomic'),
    runtime: recipe.runtime?.trim() || null,
    tags: (recipe.tags ?? []).slice(0, CARD_TAG_LIMIT),
  };
}
