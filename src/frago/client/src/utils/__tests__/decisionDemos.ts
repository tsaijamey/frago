/**
 * 决定卡片的测试样例：原型「第五轮」演示的 10 张卡，区块原文逐字照搬。
 * 解析的单测与卡片的组件测试共用这一份。
 */

const FENCE = '```';

/** 拼成一条以区块结尾的 agent 回复。 */
export const wrap = (say: string, yaml: string) =>
  `${say}\n\n${FENCE}answer-needed-by-human\n${yaml.trim()}\n${FENCE}`;

export const DEMOS: Record<string, string> = {
  'single-choice': `
type: single-choice
question: "导航已改叫 Teams，地址要不要也从 #/teaming 改成 #/teams？"
why: 名字和地址对不上，分享出去的链接看着像旧页面；留跳转的话旧书签不受影响
options:
  - key: A
    label: 一起改，旧地址自动跳转
    effect: "路由改成 #/teams，打开 #/teaming 自动跳到新地址，旧书签照常能用"
    recommended: true
  - key: B
    label: 只改名字，地址不动
    effect: "地址保持 #/teaming，路由和手册里的链接都不改"
  - key: C
    label: 一起改，不留跳转
    effect: 旧地址打开是空白页，书签和手册里的链接要逐个改`,
  'single-choice-irreversible': `
type: single-choice
question: 1.4.111 要发到 PyPI 吗？
why: 版本比较的崩溃已修，测试全过
options:
  - key: A
    label: 发布
    effect: 打 v1.4.111 tag 并上传 PyPI，发出去收不回
    reversible: false
    recommended: true
  - key: B
    label: 先不发
    effect: 改动留在 main，不打 tag`,
  'single-choice-teammate': `
type: single-choice
from: teammate
question: 队友请你这边的 agent 改一条 hook 规则，批不批？
request: 把你那边 Stop 收尾提醒那条 hook 规则改成：只在收尾话里有问句时才提醒
changes: ~/.frago/hook/builtin-rules.json 里「收尾提醒」一条，触发条件从「每次收尾」改成「收尾话里有问句」
why: 属于「会改动本机」那一档；你定的是这一档先问你
options:
  - key: A
    label: Approve
    effect: 我照请求改这一条，下一轮生效；改完把改动原文转给队友
  - key: B
    label: Decline
    effect: 回复队友「主人没批」，本机不动`,
  'single-choice-done-or-cant': `
type: single-choice
question: "请在终端里跑 \`! gcloud auth login\`，登好了回来点一下"
why: 部署要用你的 Google 账号授权，登录只能你本人做；浏览器弹出后选工作账号、点允许，终端出现 You are now logged in 就好了
options:
  - key: A
    label: I've done it
    effect: 我接着把服务部署到 Cloud Run
  - key: B
    label: I can't
    effect: 部署停在这里，等你说卡在哪一步`,
  'multi-choice': `
type: multi-choice
question: 这三个问题要记哪几条 todo？
why: 泄露 key 那条越晚处理风险越大，另外两条不急
options:
  - key: A
    label: 轮换 57b060f7 里推上去的两个 Lenovo API key
    effect: frago todo add 一条，优先级 high
    recommended: true
  - key: B
    label: .gitignore 补上 4 个凭据目录
    effect: frago todo add 一条，普通优先级
  - key: C
    label: 补完 todo 清理的遗留
    effect: frago todo add 一条，附 29 条未写、4 条存疑、2 条重复的清单`,
  'text-answer-suggestions': `
type: text-answer
question: 这个项目的正式域名是哪个？
why: 要写进 CORS 白名单和登录回调地址，填错会让线上登录跳回失败；nginx 配置里写的是第一个，部署脚本里的 SIT 地址是第二个
suggestions:
  - zenith.example.com
  - zenith-sit.example.com`,
  'choice-and-text-draft': `
type: choice-and-text
question: 这条新规则照这样写行不行？
why: 「要人拍板就写区块」的提醒这周重复了 4 次
draft: |
  触发：Stop（agent 收尾时）
  条件：收尾话在等人拍板，却没有 answer-needed-by-human 区块
  提醒：要人拍板就把全部选项写进 answer-needed-by-human 区块，放在回复最末尾，写完就停
options:
  - key: A
    label: 就这样
    effect: 照草稿原文写进 ~/.frago/hook/builtin-rules.json，下一轮生效
    recommended: true
  - key: B
    label: 改一下
    effect: 按你在框里改过的文字写进 builtin-rules.json
  - key: C
    label: 不加这条
    effect: 草稿作废，规则文件不动`,
  'choice-and-text-multi': `
type: choice-and-text
multi: true
question: 发版前要顺手带上哪几件？没列到的写在下面
options:
  - key: A
    label: 重建界面资源
    effect: 跑一次 webui 构建，把产物更新进 src/frago/server/assets
  - key: B
    label: 补 CHANGELOG
    effect: 在 CHANGELOG.md 加 1.4.111 一节，列这次的 3 个修复
  - key: C
    label: 跑一遍端到端测试
    effect: 跑 tests/e2e 全套，大约 6 分钟`,
  broken: `
type: approve-irreversible
question: 1.4.111 要发到 PyPI 吗？
why: 版本比较的崩溃已修，测试全过
options:
  - key: A
    label: 发布
    effect: 打 v1.4.111 tag 并上传 PyPI，发出去收不回
    reversible: false
  - key: B
    label: 先不发
    effect: 改动留在 main，不打 tag`,
  'broken-yaml': `
type: single-choice
question: 1.4.111 要发到 PyPI 吗？
why: 版本比较的崩溃已修，测试全过
options:
  - key: A
    label: 发布
    effect: 打 v1.4.111 tag 并上传 PyPI，发出去收不回
    reversible: false
   - key: B
    label: 先不发
    effect: 改动留在 main，不打 tag`,
};
