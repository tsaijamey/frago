/**
 * 分段控件：一排同类档位装在浅底里，当前那一档浮起来。
 *
 * 分两层说话——底（`SEG_GROUP`）回答「这是一组、只能选一个」，浮起的那片
 * （`SEG_ON`：主底加一圈发丝描边）回答「你现在在这」。少了底，几个按钮就只是
 * 飘在页面底色上的几行字；少了描边，当前档和周围那片底糊在一起，边界没了。
 *
 * 左栏的时间范围、中栏的记录镜头是同一种东西，用同一套写法——长在不同地方也要
 * 长得一样。中栏比左栏窄，那边用 `SEG_TIGHT` 收一档字号与内边距，六档争取一排放下。
 *
 * 深浅两套只差选中片有没有落影：深色下主底比托底暗、自带分界；浅色下白片压在
 * 浅灰托底上，只靠一圈线分不出层次，那边再补一层极轻的落影。差异写在
 * `--seg-on-shadow`（globals.css 两套主题各一份），这里只引用，不判断主题。
 */
export const SEG_GROUP =
  'inline-flex shrink-0 max-w-full items-center gap-px overflow-x-auto rounded-[8px] bg-bg-hover p-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden';

export const SEG_ITEM =
  'inline-flex h-6 shrink-0 items-center gap-1 whitespace-nowrap rounded-[6px] transition-colors duration-200 disabled:opacity-40';

/** 左栏那一排：宽一档、字大一档。 */
export const SEG_ROOMY = 'px-[9px] text-[12px]';

/** 中栏记录镜头那一排：六档要争取一排放下，收一档。 */
export const SEG_TIGHT = 'px-[5px] text-[11.5px]';

export const SEG_ON = 'bg-bg-primary text-text-primary shadow-[var(--seg-on-shadow)]';
export const SEG_OFF = 'text-text-secondary hover:text-text-primary';
