/* 标签手术的回归用例：拼进去、原样撤掉、组内换掉、人写的字一个不动。
 *
 * 委托方那次是七个风格标签全被点亮、取消不掉、也还原不了。
 * 修完之后最要紧的一条不是「能取消」，而是**取消时不许碰他自己写的字**——
 * 他写了三行、点了下标签又取消，回头少了半句，这种错比点不亮严重得多。
 *
 * 跑：node test_prompt_draft.mjs
 */

import * as PD from './assets/js/promptdraft.js';

const fails = [];
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
  if (!ok) fails.push(name);
};

const STYLE = [
  { group: '风格', label: '写实摄影', text: '写实摄影质感，35mm 镜头，浅景深' },
  { group: '风格', label: '水彩', text: '水彩手绘，湿画法晕染，纸纹可见' },
  { group: '风格', label: '油画', text: '油画质感，厚涂笔触，颜料堆叠' },
];
const TIME = [
  { group: '时间', label: '黄昏', text: '黄昏，暖金色的斜光' },
  { group: '时间', label: '夜', text: '夜晚，暗部占大面积' },
];
const ALL = [...STYLE, ...TIME];

const MINE = '海边的卡夫卡，少年站在图书馆前，他的行李箱放在脚边';

console.log('=== 1. 点一下拼进去，再点一下原样撤掉 ===');
let t = PD.togglePresetText(MINE, STYLE[0], STYLE);
check('拼进去了', PD.hasSegment(t, STYLE[0].text), t);
check('人写的那句原封不动在最前', t.startsWith(MINE), t.slice(0, 30) + '…');

t = PD.togglePresetText(t, STYLE[0], STYLE);
check('再点一次撤掉了', !PD.hasSegment(t, STYLE[0].text));
check('撤完之后跟原文一模一样', t === MINE, `实得 ${JSON.stringify(t)}`);

console.log('\n=== 2. 组内单选：点第二个，第一个自动灭 ===');
t = PD.togglePresetText(MINE, STYLE[0], STYLE);
t = PD.togglePresetText(t, STYLE[1], STYLE);
check('新的在', PD.hasSegment(t, STYLE[1].text));
check('旧的没了', !PD.hasSegment(t, STYLE[0].text), t);
check('人写的还在', t.startsWith(MINE));

console.log('\n=== 3. 跨组可以叠加 ===');
t = PD.togglePresetText(t, TIME[0], TIME);
check('风格和时间同时在', PD.hasSegment(t, STYLE[1].text) && PD.hasSegment(t, TIME[0].text), t);

console.log('\n=== 4. 一键清掉：只撤标签，人写的一个字不少 ===');
const cleared = PD.clearPresetText(t, ALL);
check('标签全撤干净', ALL.every((i) => !PD.hasSegment(cleared, i.text)));
check('人写的一字不差', cleared === MINE, `实得 ${JSON.stringify(cleared)}`);

console.log('\n=== 5. 七个全点亮也出得来（他卡住的那个状态）===');
let stuck = MINE;
for (const it of ALL) stuck = stuck + '，' + it.text;      // 硬拼成全亮
check('确实全在里面', ALL.every((i) => PD.hasSegment(stuck, i.text)));
check('清一下就回到原文', PD.clearPresetText(stuck, ALL) === MINE,
      JSON.stringify(PD.clearPresetText(stuck, ALL)));

console.log('\n=== 6. 空框起步也不会多出分隔符 ===');
let empty = PD.togglePresetText('', STYLE[0], STYLE);
check('空框拼一个，前面不带逗号', empty === STYLE[0].text, JSON.stringify(empty));
check('撤掉之后是空的', PD.clearPresetText(empty, ALL) === '', JSON.stringify(PD.clearPresetText(empty, ALL)));

console.log('\n=== 7. 人手工改过那段话，就不再当它是标签 ===');
const edited = MINE + '，黄昏时分的暖光';          // 跟预设不完全一样
check('对不上就不算点亮', !PD.hasSegment(edited, TIME[0].text));
check('撤不着也不会误伤', PD.clearPresetText(edited, ALL) === edited);

console.log('\n=== 8. 标签文字里有正则元字符也不炸 ===');
const tricky = { group: '风格', label: '怪', text: '35mm (f/1.4) 镜头 [浅景深]' };
let odd = PD.togglePresetText(MINE, tricky, [tricky]);
check('拼得进去', PD.hasSegment(odd, tricky.text));
check('也撤得干净', PD.togglePresetText(odd, tricky, [tricky]) === MINE,
      JSON.stringify(PD.togglePresetText(odd, tricky, [tricky])));

console.log();
console.log('FAILED:', fails.length ? fails : '无');
process.exit(fails.length ? 1 : 0);
