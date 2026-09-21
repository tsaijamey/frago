/**
 * 配方网格上的文件夹。
 *
 * 摆法记在服务端那张表里（`~/.frago/recipes/folders.json`），不在浏览器本地：pin
 * 那一排丢了只是菜单少几行，重新点开就行；文件夹摆法丢了是整个桌面归零。放在那边
 * 还跟着数据仓库一起备份走。
 *
 * 初装一个文件夹都没有，这是正常状态不是出错——配方接近 app，能拿来分类的角度太
 * 多，系统不替人预设一种看法，第一个文件夹由主人亲手建。没有文件夹时网格跟从前一
 * 样平铺一屏图标。
 *
 * 每一条写操作都拿整张表回来盖掉本地这份：摆一次图标要动好几处（从原文件夹拿出
 * 来、放进新的、顺序跟着变），各改各的容易让界面上的图标凭空多一个少一个。
 */

import { create } from 'zustand';
import * as httpApi from '@/api/client';
import type { RecipeFolder, RecipeFoldersPayload } from '@/types/api';

interface RecipeFoldersState {
  folders: RecipeFolder[];
  maxFolders: number;
  /** 表读坏了的那句人话。界面照常打开，但要把它显出来——不说的话人看到的是「我的
   *  文件夹全没了」，没有任何线索可查。 */
  trouble: string | null;
  loading: boolean;
  /** 上一次写操作被拒的理由，原样来自服务端，界面直接显示。 */
  error: string | null;

  load: () => Promise<void>;
  create: (body: {
    id: string;
    name_zh?: string;
    name_en?: string;
    icon?: string;
    recipes?: string[];
  }) => Promise<boolean>;
  rename: (id: string, nameZh: string, nameEn: string) => Promise<boolean>;
  move: (id: string, position: number) => Promise<boolean>;
  remove: (id: string) => Promise<boolean>;
  /** `folder` 传 null 就是拿出来、回到未分类。 */
  assign: (recipes: string[], folder: string | null) => Promise<boolean>;
  clearError: () => void;
}

export const useRecipeFolders = create<RecipeFoldersState>((set) => {
  /** 写操作共用的外壳：成功就把整张表换上，失败把服务端那句话留下。 */
  const write = async (run: () => Promise<RecipeFoldersPayload>): Promise<boolean> => {
    try {
      const payload = await run();
      set({
        folders: payload.folders,
        maxFolders: payload.max_folders,
        trouble: payload.trouble,
        error: null,
      });
      return true;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return false;
    }
  };

  return {
    folders: [],
    maxFolders: 0,
    trouble: null,
    loading: false,
    error: null,

    load: async () => {
      set({ loading: true });
      try {
        const payload = await httpApi.getRecipeFolders();
        set({
          folders: payload.folders,
          maxFolders: payload.max_folders,
          trouble: payload.trouble,
        });
      } catch (e) {
        // 取不到就是没有文件夹：网格照样平铺一屏图标，配方一个都不少。
        set({ error: e instanceof Error ? e.message : String(e) });
      } finally {
        set({ loading: false });
      }
    },

    create: (body) => write(() => httpApi.createRecipeFolder(body)),

    rename: (id, nameZh, nameEn) =>
      write(() => httpApi.updateRecipeFolder(id, { name_zh: nameZh, name_en: nameEn })),

    move: (id, position) => write(() => httpApi.updateRecipeFolder(id, { position })),

    remove: (id) => write(() => httpApi.deleteRecipeFolder(id)),

    assign: (recipes, folder) => write(() => httpApi.assignRecipeFolder(recipes, folder)),

    clearError: () => set({ error: null }),
  };
});

/**
 * 从一个中文名凑一个还没被占用的文件夹 id。
 *
 * 界面上建文件夹只问名字不问 id——问 id 等于要人在起名之外再想一个英文短词，而这
 * 个词他此后再也不会看见。中文名拼不出 id 的（全中文），退回 `folder-1` 这种；撞
 * 上已有的就往后数。
 */
export function suggestFolderId(name: string, taken: string[]): string {
  const base = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32);
  const used = new Set(taken);
  if (base && !used.has(base)) return base;
  const stem = base || 'folder';
  for (let i = 2; i < 999; i += 1) {
    const candidate = `${stem}-${i}`.slice(0, 32);
    if (!used.has(candidate)) return candidate;
  }
  return `${stem}-${Date.now()}`.slice(0, 32);
}
