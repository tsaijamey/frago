/**
 * 网格上的一个文件夹图标。
 *
 * 横排一张卡：左边小方块里一个文件夹图标，右边上行是名称和数量，下行是前 3 张配方
 * 的标题——卡片回答「里面是什么、有几张」。过去方块里摆的是前四张标题的首字母，本
 * 机配方标题多是英文大写开头，拼出来的「AA / VV」认不出任何一张，还把卡撑到 240px。
 * 点一下打开，再点一下收起——文件夹在这一页里就地展开，不换页，因为人往文件夹里摆
 * 东西时通常一口气摆好几张，每开一个就跳走一次会把这件事拆得很碎。
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

  // 空文件夹没有第二行，卡片只剩「名称 + 数量」。没起过名的配方，标题是标识名换掉
  // 下划线凑出来的，照配方卡的规矩把每个词首字母大写；作者写过的标题原样不动。
  const peek = items
    .slice(0, 3)
    .map((r) => {
      const shown = recipeTitle(r, i18n.language);
      const named = Object.keys(r.title ?? {}).length > 0;
      return named ? shown : shown.replace(/\b\w/g, (c) => c.toUpperCase());
    })
    .join(' · ');

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
        <span className="rl-folder-icon" aria-hidden="true">
          {open ? <FolderOpen size={16} /> : <Folder size={16} />}
        </span>
        <span className="rl-folder-text">
          <span className="rl-folder-line">
            <span className="rl-folder-name">{label}</span>
            <span className="rl-folder-count">{folder.recipes.length}</span>
          </span>
          {peek && <span className="rl-folder-peek">{peek}</span>}
        </span>
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
