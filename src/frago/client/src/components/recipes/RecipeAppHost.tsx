/**
 * 配方页面，开在界面右侧，**离开了也不关**。
 *
 * 配方页面本来就是 `/app/<配方名>/` 发出来的一张独立网页，这里把它嵌进界面，左边
 * 菜单里 recipes 下面 pin 着一行指着它。
 *
 * **为什么它常驻而不是跟着页面切换挂上、卸下。** 从前人切去配方详情点一下运行、再
 * 切回来，那张页面已经被卸掉重新载入过——人在上面没保存的输入跟着没了。现在打开过
 * 的页面一直留着，切走时只是藏起来，切回来还是原来那一张；只有 × 摘掉才真正关掉。
 * 没打开过的 pin 不预先载入，进界面不会一口气把所有配方页面都跑一遍。
 *
 * 顶上只留一条细栏：名字、槽位、重新载入、去配方详情、摘掉。页面自己有自己的界面，
 * 这里再压一个大标题只会挤它的高度。
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, PinOff, RotateCw } from 'lucide-react';
import { recipeAppUrl } from '@/api/client';
import { writeLocationRoute, pathForPage } from '@/routes';
import { usePageStore } from '@/stores/pageStore';
import { splitRecipeAppId, useRecipeAppPins } from '@/stores/recipeAppPins';

function RecipeAppFrame({ id, active }: { id: string; active: boolean }) {
  const { t } = useTranslation();
  const switchPage = usePageStore((s) => s.switchPage);
  const unpin = useRecipeAppPins((s) => s.unpin);
  // 换一个值就换一个 iframe：重新载入只在人点那颗按钮时发生，别的任何事都不碰它。
  const [reloadKey, setReloadKey] = useState(0);

  const { name, slot } = splitRecipeAppId(id);
  const src = recipeAppUrl(name, slot);

  return (
    <div className="recipe-app-page" hidden={!active}>
      <div className="recipe-app-bar">
        <span className="recipe-app-name" title={name}>
          {name.replace(/_/g, ' ')}
        </span>
        {slot ? <span className="recipe-app-slot">{slot}</span> : null}
        <span className="recipe-app-bar-spacer" />
        <button
          type="button"
          className="recipe-app-action"
          onClick={() => setReloadKey((k) => k + 1)}
          title={t('recipes.app.reload')}
          aria-label={t('recipes.app.reload')}
        >
          <RotateCw size={14} strokeWidth={1.5} />
        </button>
        <button
          type="button"
          className="recipe-app-action"
          onClick={() => switchPage('recipe_detail', name)}
          title={t('recipes.app.detail')}
          aria-label={t('recipes.app.detail')}
        >
          <FileText size={14} strokeWidth={1.5} />
        </button>
        <button
          type="button"
          className="recipe-app-action"
          onClick={() => {
            unpin(id);
            switchPage('recipes');
          }}
          title={t('recipes.app.unpin')}
          aria-label={t('recipes.app.unpin')}
        >
          <PinOff size={14} strokeWidth={1.5} />
        </button>
      </div>
      <iframe key={reloadKey} className="recipe-app-frame" src={src} title={name} />
    </div>
  );
}

export default function RecipeAppHost() {
  const { t } = useTranslation();
  const currentPage = usePageStore((s) => s.currentPage);
  const currentId = usePageStore((s) => s.currentRecipeAppId);
  const applyRoute = usePageStore((s) => s.applyRoute);
  const pins = useRecipeAppPins((s) => s.pins);
  const pin = useRecipeAppPins((s) => s.pin);
  // 这一轮界面里打开过的页面。只增不减，摘掉的由下面按 pins 过滤掉。
  const [opened, setOpened] = useState<string[]>([]);

  const onAppPage = currentPage === 'recipe_app';

  // 进到某个配方页面：pin 上；这个配方已经开着别的地址，就回到已开的那一张，
  // 并把地址栏改成它（替换，不留历史），免得地址栏说的和屏幕上的不是同一份。
  useEffect(() => {
    if (!onAppPage || !currentId) return;
    const kept = pin(currentId);
    if (kept !== currentId) {
      writeLocationRoute(pathForPage('recipe_app', kept), true);
      applyRoute('recipe_app', kept);
      return;
    }
    setOpened((prev) => (prev.includes(kept) ? prev : [...prev, kept]));
  }, [onAppPage, currentId, pin, applyRoute]);

  const alive = opened.filter((id) => pins.includes(id));

  return (
    <>
      {onAppPage && !currentId ? (
        <div className="text-[var(--text-muted)] text-center py-scaled-8">{t('recipes.app.missing')}</div>
      ) : null}
      {alive.map((id) => (
        <RecipeAppFrame key={id} id={id} active={onAppPage && currentId === id} />
      ))}
    </>
  );
}
