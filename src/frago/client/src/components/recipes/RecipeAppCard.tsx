/**
 * RecipeAppCard — Single app card in the Recipe Grid.
 *
 * Design: icon + status badge + title + description + run button.
 */

import type { RecipeItem } from '@/types/pywebview';

interface RecipeAppCardProps {
  recipe: RecipeItem;
  onRun: () => void;
  onClick: () => void;
}

// Map category/source to emoji icons
function getRecipeEmoji(recipe: RecipeItem): string {
  const name = recipe.name.toLowerCase();
  if (name.includes('etf') || name.includes('stock') || name.includes('finance')) return '📊';
  if (name.includes('feishu') || name.includes('webhook') || name.includes('notify')) return '📬';
  if (name.includes('web') || name.includes('scrape') || name.includes('crawl')) return '🌐';
  if (name.includes('email') || name.includes('mail')) return '📧';
  if (name.includes('screenshot') || name.includes('image') || name.includes('photo')) return '📸';
  if (name.includes('message') || name.includes('chat')) return '💬';
  if (name.includes('pdf') || name.includes('report') || name.includes('doc')) return '📄';
  if (name.includes('timer') || name.includes('schedule') || name.includes('cron')) return '⏰';
  return recipe.category === 'workflow' ? '🔄' : '⚡';
}

function getStatusInfo(_recipe: RecipeItem): { dot: string; text: string; color: string } {
  // For now, all loaded recipes are "ready"
  return { dot: '●', text: '就绪', color: 'var(--accent-primary)' };
}

export default function RecipeAppCard({ recipe, onRun, onClick }: RecipeAppCardProps) {
  const emoji = getRecipeEmoji(recipe);
  const status = getStatusInfo(recipe);
  const sourceTag = recipe.source;

  return (
    <div className="recipe-card" onClick={onClick}>
      {/* Top: Icon + Status */}
      <div className="recipe-card-header">
        <div className="recipe-card-icon">
          <span>{emoji}</span>
        </div>
        <div className="recipe-card-status">
          {sourceTag && (
            <span className="recipe-card-source">{sourceTag}</span>
          )}
          <span style={{ color: status.color, fontSize: '10px' }}>
            {status.dot} {status.text}
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
          ▶ 运行
        </button>
      </div>
    </div>
  );
}
