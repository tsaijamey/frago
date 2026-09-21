/**
 * 网格上的一个文件夹图标。
 *
 * 画成手机桌面那样：一个方块，里面是前四张配方的首字，底下是文件夹名和数量。点一
 * 下打开，再点一下收起——文件夹在这一页里就地展开，不换页，因为人往文件夹里摆东西
 * 时通常一口气摆好几张，每开一个就跳走一次会把这件事拆得很碎。
 *
 * 它同时是拖放的落点：把一张配方卡拖到这里松手就是放进去。拖着经过时描边变色，不
 * 变大不抖动——一排文件夹里只有一个该亮起来，其余的位置不许动。
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Folder, FolderOpen, Pencil, Trash2 } from 'lucide-react';
import type { RecipeFolder } from '@/types/api';
import type { RecipeItem } from '@/types/pywebview';
import { folderLabel, recipeTitle } from './recipeTitle';

interface Props {
  folder: RecipeFolder;
  /** 这个文件夹里那几张配方，按文件夹里的顺序，已经去掉装不回来的。 */
  items: RecipeItem[];
  open: boolean;
  onToggle: () => void;
  onDropRecipes: (names: string[]) => void;
  onRename: () => void;
  onRemove: () => void;
}

export default function RecipeFolderTile({
  folder,
  items,
  open,
  onToggle,
  onDropRecipes,
  onRename,
  onRemove,
}: Props) {
  const { t, i18n } = useTranslation();
  const [over, setOver] = useState(false);
  const label = folderLabel(folder, i18n.language);

  const preview = items.slice(0, 4);

  const takeDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setOver(false);
    const raw = e.dataTransfer.getData('application/x-frago-recipes');
    if (!raw) return;
    try {
      const names = JSON.parse(raw) as string[];
      if (Array.isArray(names) && names.length) onDropRecipes(names);
    } catch {
      // 拖进来的不是配方卡，当没发生过。
    }
  };

  return (
    <div
      className={`rl-folder ${open ? 'rl-folder--open' : ''} ${over ? 'rl-folder--over' : ''}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={takeDrop}
    >
      <button
        type="button"
        className="rl-folder-hit"
        onClick={onToggle}
        aria-expanded={open}
        title={t('recipes.folder.openHint', { name: label })}
      >
        <span className="rl-folder-box" aria-hidden="true">
          {preview.length === 0 ? (
            open ? <FolderOpen size={20} /> : <Folder size={20} />
          ) : (
            preview.map((r) => (
              <span key={r.name} className="rl-folder-chip">
                {recipeTitle(r, i18n.language).trim().charAt(0).toUpperCase()}
              </span>
            ))
          )}
        </span>
        <span className="rl-folder-name">{label}</span>
        <span className="rl-folder-count">{folder.recipes.length}</span>
      </button>
      {/* 改名和删除挂在图标上，不藏进另一层菜单：一共就两个动作，为它们再开一级
          菜单，等于让人多点一下才能看见本来就该看见的东西。 */}
      <span className="rl-folder-acts">
        <button
          type="button"
          className="rl-folder-act"
          onClick={onRename}
          title={t('recipes.folder.rename')}
          aria-label={`${t('recipes.folder.rename')} ${label}`}
        >
          <Pencil size={12} />
        </button>
        <button
          type="button"
          className="rl-folder-act"
          onClick={onRemove}
          title={t('recipes.folder.remove')}
          aria-label={`${t('recipes.folder.remove')} ${label}`}
        >
          <Trash2 size={12} />
        </button>
      </span>
    </div>
  );
}
