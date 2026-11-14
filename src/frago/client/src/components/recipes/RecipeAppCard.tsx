/**
 * RecipeAppCard — Single app card in the Recipe Grid.
 *
 * Design: icon + status badge + title + description + run button.
 */

import { Play, Workflow, Box } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { RecipeItem } from '@/types/pywebview';

interface RecipeAppCardProps {
  recipe: RecipeItem;
  onRun: () => void;
  onClick: () => void;
}

/**
 * 图标按类型分，不按名字猜。
 *
 * 从前这里挂着十来条 `name.includes('etf')` 之类的判断，命中就配一个彩色 Emoji
 * （📊 📬 🌐 📧 …）。两个毛病：一是英文标识名里出现某个子串纯属偶然，猜错的比猜对
 * 的多；二是 Emoji 自带一套跟主题无关的配色，一屏卡片看下来像一板贴纸。
 * 现在只按 `category` 给一个 Lucide 线性图标——工作流是分支，原子是方块。
 */
function RecipeIcon({ recipe }: { recipe: RecipeItem }) {
  return recipe.category === 'workflow' ? <Workflow size={18} /> : <Box size={18} />;
}

export default function RecipeAppCard({ recipe, onRun, onClick }: RecipeAppCardProps) {
  const { t } = useTranslation();
  const sourceTag = recipe.source;

  return (
    <div className="recipe-card" onClick={onClick}>
      {/* Top: Icon + Status */}
      <div className="recipe-card-header">
        <div className="recipe-card-icon">
          <RecipeIcon recipe={recipe} />
        </div>
        <div className="recipe-card-status">
          {sourceTag && (
            <span className="recipe-card-source">{sourceTag}</span>
          )}
          <span className="text-xs text-[var(--text-muted)]">
            {t('recipes.readyToRun')}
          </span>
        </div>
      </div>

      {/* Middle: Title + Description */}
      <div className="recipe-card-body">
        <h3 className="recipe-card-title">{recipe.name.replace(/_/g, ' ')}</h3>
        <p className="recipe-card-desc">
          {recipe.description || ''}
        </p>
      </div>

      {/* Bottom: Meta + Run */}
      <div className="recipe-card-footer">
        <span className="recipe-card-meta">
          {recipe.runtime || recipe.category}
        </span>
        <button
          className="recipe-card-run"
          onClick={(e) => { e.stopPropagation(); onRun(); }}
        >
          <Play size={13} />
          {t('recipes.run')}
        </button>
      </div>
    </div>
  );
}
