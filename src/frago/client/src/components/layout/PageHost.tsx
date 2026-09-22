/**
 * 页面宿主：进过的页面切走时**不卸载，只藏起来**。
 *
 * 从前这里是 App 里一个 switch：当前是哪一页就渲染哪一个组件，切走的那一个连同它
 * 里面的全部东西一起被 React 卸掉。症状是人在会话输入框里写了一半的话，去待办页
 * 看一眼再回来，输入框空了；页面里选到哪一行、滚到哪儿、展开着哪一块，同样都没了。
 * 这些状态本来就不该跟着"看不看得见"走——它们记的是人在这一页上做到哪一步。
 *
 * 所以改成一页一份，一直留着：切走只是给那一个套上 `hidden`，切回来还是原来那一
 * 张。这与右侧配方页面那一套（`RecipeAppHost`）是同一个做法，理由也一样。区别在
 * 于配方页面是嵌进来的 iframe、开关由 pin 决定，这里的每一页是界面自己的组件。
 *
 * **只增不减。** 进过的页面留到这次会话结束，不做淘汰。页数就十来个，每一份占的
 * 内存远小于重新进一次要付的代价（重新拉数据、重新摆布局，人还得重新找位置）。
 *
 * **按"视图"留，不按页面编号留。** 待办清单与某一条待办的详情是同一个视图，配方
 * 清单与配方详情是两个。这样切页的行为与从前一致：同类型的详情之间来回（配方 A →
 * 配方 B）本来就不重新挂载，跨视图才需要另起一份。
 *
 * **页面里的定时器在藏起来的时候照跑。** 数据仓库的状态轮询、报告面板的刷新都还在
 * 走。这是有意的：切回来时看到的该是最新的数，不是离开那一刻的旧数。全局的数据同
 * 步本来就走 WebSocket 推给所有页面，不靠页面自己重进一次。
 */

import { useEffect, useState, type ReactElement } from 'react';
import { usePageStore, type PageType } from '@/stores/pageStore';

import SessionWorkbenchPage from '@/components/sessionWorkbench/SessionWorkbenchPage';
import RecipeList from '@/components/recipes/RecipeList';
import RecipeDetail from '@/components/recipes/RecipeDetail';
import DataRepoPage from '@/components/dataRepo/DataRepoPage';
import SkillList from '@/components/skills/SkillList';
import SettingsPage from '@/components/settings/SettingsPage';
import NewTaskPage from '@/components/newTask/NewTaskPage';
import { WorkspacePage } from '@/components/workspace';
import { TodoPage } from '@/components/todos';
import { SchedulePage } from '@/components/schedules';
import { GuidePage } from '@/components/guide';

/** 留状态的最小单位：同一个视图里的页面编号换来换去，还是这一份。 */
type ViewKey =
  | 'workbench'
  | 'recipes'
  | 'recipe_detail'
  | 'data_repo'
  | 'todos'
  | 'schedules'
  | 'skills'
  | 'guide'
  | 'settings'
  | 'newTask'
  | 'workspace';

/**
 * 哪一页属于哪个视图。
 *
 * `recipe_app` 是 null：配方页面由主布局里的 `RecipeAppHost` 自己管，它开不开由 pin
 * 决定，不归这里。地址认不出来的页面走 `workbench`——routes 里认不出的一律回首页，
 * 两边是同一个兜底。
 */
const VIEW_OF_PAGE: Record<PageType, ViewKey | null> = {
  live: 'workbench',
  session_workbench: 'workbench',
  dashboard: 'workbench',
  tasks: 'workbench',
  task_detail: 'workbench',
  recipes: 'recipes',
  recipe_detail: 'recipe_detail',
  recipe_app: null,
  data_repo: 'data_repo',
  todos: 'todos',
  todo_detail: 'todos',
  schedules: 'schedules',
  schedule_detail: 'schedules',
  skills: 'skills',
  guide: 'guide',
  settings: 'settings',
  newTask: 'newTask',
  workspace: 'workspace',
  project_detail: 'workspace',
};

const VIEWS: Record<ViewKey, () => ReactElement> = {
  workbench: () => <SessionWorkbenchPage />,
  recipes: () => <RecipeList />,
  recipe_detail: () => <RecipeDetail />,
  data_repo: () => <DataRepoPage />,
  todos: () => <TodoPage />,
  schedules: () => <SchedulePage />,
  skills: () => <SkillList />,
  guide: () => <GuidePage />,
  settings: () => <SettingsPage />,
  newTask: () => <NewTaskPage />,
  workspace: () => <WorkspacePage />,
};

export default function PageHost() {
  const currentPage = usePageStore((s) => s.currentPage);
  // 表里没有的页面回会话工作台（与 routes 认不出地址时的兜底同一条）。`recipe_app`
  // 在表里是明写的 null，那不是"认不出来"，是"不归这里管"——两者 MUST 分开，
  // 否则开一个配方页面会把会话页从底下顶出来。
  const view: ViewKey | null =
    currentPage in VIEW_OF_PAGE ? VIEW_OF_PAGE[currentPage] : 'workbench';
  // 这次界面里进过的视图。只增不减，顺序就是它们被打开的顺序。
  const [opened, setOpened] = useState<ViewKey[]>(view ? [view] : []);

  useEffect(() => {
    if (!view) return;
    setOpened((prev) => (prev.includes(view) ? prev : [...prev, view]));
  }, [view]);

  return (
    <>
      {opened.map((key) => {
        const Page = VIEWS[key];
        return (
          <div key={key} className="page-slot" hidden={key !== view}>
            <Page />
          </div>
        );
      })}
    </>
  );
}
