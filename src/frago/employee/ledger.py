"""frago employee — 员工账本的主动巡检：以职责范围为锚点，在 ``~/.frago`` 下认领资源并增量记账。

这个模块回答一个问题：一个新员工刚被立起来、除了「我负责什么」之外一无所知的时候，
它怎么自己把家底盘清。盘的对象是四类：数据目录、配方、知识域、会话。

三条纪律贯穿全篇：

1. **以职责范围为锚点。** 认领的判据是岗位的 ``title`` / ``description`` / ``work_scope``
   里出现的职责词，不是「目录里有什么就记什么」。记一堆与岗位无关的东西，账本就从
   「秒懂」变成了「还得再筛一遍」，反而比没有更贵。
2. **增量。** 每类资源都先比指纹，指纹没变的直接跳过。全量重扫会把一次巡检变成一次
   全盘遍历，而账本要的是「自上次以来新出现了什么」。
3. **防自指。** 账本自己写在 ``~/.frago/employees/`` 下，巡检扫不到它；巡检自己起的
   会话按标题标记排除。少了这一条，巡检产出会被下次巡检当成新发现，账本自己长自己。

Layer: domain service — imports ``frago.employee.store``; NEVER imports ``frago.server``
or ``frago.cli``。排程那一段需要用到服务端的调度器，走的是调用方注入的回调，不在这里
直接 import。
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.employee.store import (
    EmployeeLedger,
    EmployeePostRecord,
    LedgerCursor,
    digest_path_entry,
    digest_text,
    frago_home,
    get_post,
    is_employee_ledger_path,
    is_resource_excluded,
    load_ledger,
    merge_ledger_entries,
    save_ledger,
    save_post,
)

#: 认领判据里忽略的词：它们在任何岗位的描述里都出现，拿它们匹配等于把什么都认领下来。
_STOPWORDS: frozenset[str] = frozenset(
    {
        "负责",
        "工作",
        "任务",
        "相关",
        "一切",
        "全部",
        "以及",
        "包括",
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "员工",
        "岗位",
        "数据",
        "文件",
        "目录",
        "使用",
        "处理",
        "管理",
        "支持",
        "进行",
        "完成",
        "持续",
        # 文件系统与 frago 自身的词。岗位描述里常带着 ``~/.frago/data/<主体>`` 这样的
        # 路径，路径里的这些词一旦进了关键词表，``~/.frago/data/`` 下每个目录都会被
        # 认领一遍——「主动认领」当场变成「全都要」。
        "frago",
        "data",
        "users",
        "default",
        "home",
        "recipe",
        "recipes",
        "slot",
        "slots",
        "page",
        "local",
        # 路径模板里的词：岗位描述常写着「按 ~/.frago/data/stock/<YYYYMMDD>-<语义-slug>/
        # 归档，方法与纪律写进 notebook.md」。这些是归档格式的占位符，不是职责词。
        "yyyymmdd",
        "slug",
        "notebook",
        "readme",
        # 通用英文虚词与高频操作动词
        "are",
        "was",
        "were",
        "been",
        "have",
        "has",
        "had",
        "not",
        "but",
        "all",
        "any",
        "can",
        "will",
        "just",
        "more",
        "also",
        "only",
        "other",
        "some",
        "such",
        "than",
        "then",
        "them",
        "they",
        "their",
        "there",
        "these",
        "those",
        "through",
        "under",
        "over",
        "after",
        "before",
        "between",
        "about",
        "against",
        "during",
        "without",
        "within",
        "along",
        "across",
        "behind",
        "beyond",
        "plus",
        "except",
        "around",
        "down",
        "off",
        "above",
        "near",
        "how",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "via",
        "per",
        "use",
        "used",
        "using",
        "make",
        "made",
        "get",
        "set",
        "put",
        "run",
        "runs",
        "running",
        "start",
        "stop",
        "restart",
        "open",
        "close",
        "read",
        "write",
        "create",
        "update",
        "delete",
        "remove",
        "add",
        "list",
        "show",
        "find",
        "search",
        "check",
        "test",
        "build",
        "builder",
        "plan",
        "plans",
        "spec",
        "specs",
        "validate",
        "install",
        "sync",
        "save",
        "load",
        # 代理内核、命令行与通用技术栈词：几乎所有岗位的手段描述里都会提，不指向特定业务领域
        "agent",
        "agents",
        "kernel",
        "claude",
        "codex",
        "opencode",
        "gemini",
        "cursor",
        "agy",
        "coreagent",
        "skill",
        "skills",
        "prompt",
        "prompts",
        "session",
        "sessions",
        "schedule",
        "schedules",
        "domain",
        "domains",
        "cli",
        "webui",
        "web",
        "api",
        "app",
        "url",
        "http",
        "https",
        "port",
        "json",
        "yaml",
        "yml",
        "html",
        "htm",
        "css",
        "markdown",
        "txt",
        "csv",
        "pdf",
        "png",
        "jpg",
        "jpeg",
        "svg",
        "bash",
        "shell",
        "zsh",
        "tmux",
        "docker",
        "container",
        "linux",
        "macos",
        "darwin",
        "windows",
        "git",
        "commit",
        "commits",
        "branch",
        "repo",
        "workspace",
        "workdir",
        "cwd",
        "path",
        "paths",
        "file",
        "files",
        "dir",
        "folder",
        "folders",
        "server",
        "client",
        "service",
        "route",
        "routes",
        "config",
        "status",
        "error",
        "errors",
        "log",
        "logs",
        "info",
        "true",
        "false",
        "none",
        "null",
        "utf",
        "ascii",
        "env",
        "var",
        "vars",
        "arg",
        "args",
        "opt",
        "opts",
        "flag",
        "flags",
        "cmd",
        "command",
        "commands",
        "script",
        "scripts",
        "node",
        "npm",
        "npx",
        "python",
        "pip",
        "pipx",
        "support",
        "record",
        "records",
    }
)

#: 中文泛化词：单看都有意义，放进认领判据里却指向「任何岗位都成立」。
#:
#: 与 ``_STOPWORDS`` 分开是因为它还兼一份差事——当复合词的前后缀剥离器。
#: 「个人生活」剥成空，整条丢掉；「家庭事务」剥掉「事务」后留下「家庭」，那正是
#: 要拿去认领的词。只靠整词相等去过滤，「家庭事务」这种黏着写法一条都留不下。
_CJK_STOPWORDS: frozenset[str] = frozenset(
    {
        "个人",
        "工作",
        "生活",
        "私人",
        "一切",
        "问题",
        "方法",
        "结论",
        "数据",
        "知识",
        "工具",
        "工具链",
        "报告",
        "分析",
        "研究",
        "目录",
        "归档",
        "管理",
        "系统",
        "平台",
        "日常",
        "其他",
        "其它",
        "场景",
        "任务",
        "处理",
        "支持",
        "解决",
        "包括",
        "限于",
        "事务",
        "相关",
        "负责",
        "员工",
        "岗位",
        "文件",
        "使用",
        "进行",
        "完成",
        "持续",
        "全部",
        "以及",
        "东西",
        "事情",
        "内容",
        # 抽象名词：在中文长句里出现频率极高，字面却没有任何领域指向。
        # 这一批是实机跑出来的——它们进了判据之后，股票岗位的账本从 4 个数据目录涨到 36 个，
        # 认领进 ``codex``、``frago-dev``、``video-narration`` 这些跟股票毫无关系的目录：
        # ``codex`` 的用途里写着「代码结构」，``frago-dev`` 写着「目录结构」，``video-narration``
        # 写着「结构与策略」。这几条命中的不是领域，是「结构」这两个字本身。
        "结构",
        "策略",
        "语义",
        "区分",
        "不因",
        "沉淀",
        "泛化",
        "观察",
        "预期",
        "验证",
        "职责",
        "新型",
        "底账",
        "归因",
        "收益",
        "组合",
        "持仓",
        "行业",
        "行情",
        "信号",
        "量化",
        "日线",
        "板块",
        "调研",
        "解读",
        # 「操作」「交易」这类词在任何一段讲工作流的文字里都会出现，字面不指向任何领域。
        # 它们误命中的是摘要那一层：``agent-os/tasks`` 里写着「操作步骤」、
        # ``model/20260703-meetup-talk`` 里写着「交易盲测」，两个目录就凭这两个字被认领了。
        # 去掉它们，股票岗位的认领回到它真正绑定的那四个目录。
        "操作",
        "交易",
        # 通用动作、工作流状态与工程泛称：在任何岗位的职责或步骤说明里都会出现，不指向特定业务域。
        "配方",
        "代码",
        "源码",
        "特性",
        "功能",
        "模块",
        "功能模块",
        "组件",
        "提交",
        "界面",
        "页面",
        "终端",
        "浏览器",
        "窗口",
        "命令",
        "命令行",
        "脚本",
        "参数",
        "配置",
        "环境",
        "容器",
        "端口",
        "服务",
        "服务器",
        "客户端",
        "宿主机",
        "本机",
        "本地",
        "后台",
        "前台",
        "前端",
        "后端",
        "权限",
        "定义",
        "把控",
        "校验",
        "生效",
        "直通",
        "访问",
        "外部",
        "状态",
        "结果",
        "结果落定",
        "详情",
        "列表",
        "清单",
        "卡片",
        "按钮",
        "弹窗",
        "样式",
        "主题",
        "暗色",
        "暗色主题",
        "英文",
        "中文",
        "自动",
        "手动",
        "实时",
        "当前",
        "最新",
        "历史",
        "初始",
        "默认",
        "标准",
        "规范",
        "步骤",
        "流程",
        "阶段",
        "模式",
        "机制",
        "架构",
        "能力",
        "信息",
        "记录",
        "汇总",
        "统计",
        "核验",
        "检查",
        "自检",
        "测试",
        "启动",
        "停止",
        "重启",
        "刷新",
        "打开",
        "关闭",
        "安装",
        "打包",
        "构建",
        "同步",
        "更新",
        "创建",
        "删除",
        "清理",
        "还原",
        "恢复",
        "清理还原",
        "结束后清理还原",
        "执行",
        "调用",
        "通过",
        "根据",
        "借助",
        "结合",
        "提炼",
        "拆解",
        "唤醒",
        "生成",
        "合成",
        "确保",
        "必须",
        "严禁",
        "避免",
        "防止",
        "按需",
        "只读",
        "挂载",
        "写入",
        "并写入",
        "将已",
        "将已提交",
        "根据已提交",
        "成果",
        "成果归档",
        "交付",
        "协同",
        "实操",
        "策划",
        "编排",
        "准备",
        "干净",
        "核心",
        "用户",
        "价值",
        "直观",
        "看懂",
    }
)

#: 剥前后缀时认的词：泛化词 + 结构连接词，两样都要剥。
#:
#: 分开列是为了各管一段：``_CJK_STOPWORDS`` 还兼着「整词过滤」的差事（一个候选词若是它，
#: 直接不算职责词），而结构连接词只在剥的时候有用——「的」不会单独成为一个候选词。
_CJK_TRIMMERS: frozenset[str] = _CJK_STOPWORDS | frozenset(
    {
        "包括但不限于",
        "包括不限于",
        "一切问题或事务",
        "问题或事务",
        "解决跟我",
        "专门负责",
        "工作台",
        "解决与",
        "不限于",
        "等私人",
        "相关的",
        "包括",
        "相关",
        "事务",
        "助理",
        "专员",
        "以及",
        "或者",
        "跟我",
        "关系",
        "语义",
        "或",
        "与",
        "及",
        "和",
        "的",
        "等",
        "等等",
    }
)

#: 剥的时候长词优先：先认「一切问题或事务」再认「问题」，否则长词被切一半、剩下半截
#: 又成了一个新的噪声词。
_CJK_TRIMMERS_BY_LENGTH: tuple[str, ...] = tuple(
    sorted(_CJK_TRIMMERS, key=len, reverse=True)
)

_ASCII_TOKEN = re.compile(r"[a-z][a-z0-9_]{2,}")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")

#: 配方根目录下的三个约定子目录，与 ``frago.recipes.registry`` 保持一致。
_RECIPE_SUBDIRS: tuple[str, ...] = ("workflows", "atomic/chrome", "atomic/system")

#: 「执行配方」这条意图的通用触发词：与具体领域无关，任何岗位都成立。
_GENERIC_RECIPE_TRIGGERS: tuple[str, ...] = ("跑一下", "执行", "运行配方")

#: 配方名里出现率极高、当触发词等于没写的通用段。
_RECIPE_NAME_NOISE: frozenset[str] = frozenset(
    {"engine", "feed", "data", "console", "board", "signal", "signals", "dashboard", "lab"}
)


def _ascii_tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _ASCII_TOKEN.finditer(text.lower())}


def _cjk_words(text: str) -> set[str]:
    """从中文串里取有业务区分度的职责词：以标点/换行分隔的整段为单位，剥掉两头的虚词。

    这件事有两头堵，中间那条线是实机试出来的：

    **一、不剥不行。** 中文没有空格，一整段职责里领域词常被虚词包着——「家庭等私人相关的
    一切问题或事务」十五个字，落在长度窗口之外，一丢就是一整条职责，岗位当场变成
    「什么都没负责」。个人助理这个岗位因此一个字都没提取出来，本机明摆着的
    ``family-health``、``relationships`` 一个都认领不到。剥掉两头的虚词，剩下的「家庭」
    才是能拿去认领的词。

    **二、从中间切开更不行。** 试过按结构词把整段切碎，实机结果是碎片跨词边界：股票岗位的
    工作范畴里「市场微观结构调研」「收益与回撤拆解」被切成 ``结构``、``收益``、``策略``，
    而 ``~/.frago/books`` 下 ``codex``、``frago-dev``、``video-narration`` 的用途里正好
    写着「结构」「策略」，当场被认领进来。一个岗位的账本从 4 个数据目录涨到 38 个，
    里面全是 ``lenovo``、``codex``、``webui`` 这种跟股票毫无关系的目录。切得越碎，命中
    越随机——碎片的字面太短，撞上任何一段中文都有可能。

    所以只剥两头的虚词，绝不从中间切开：``存款等`` 剥成 ``存款``、``家庭事务`` 剥成
    ``家庭``、``解决跟我个人生活`` 剥成空，而 ``市场微观结构调研`` 原样留着（它自己就是
    一个完整的说法，切碎只会掉出噪声）。

    长度窗口 ``2 <= len <= 10``：2 字是中文里最小的领域单位（「家庭」「社保」「债务」
    「存款」全是 2 字，卡在 3 字上等于把这一整类词全丢掉），10 字封顶拦住没剥干净的整句。
    2 字词的泛化风险交给词表办，不交给长度办——长度一刀切会把领域词和噪声一起切掉。
    """
    words: set[str] = set()
    for run in _CJK_RUN.finditer(text):
        cleaned = _strip_cjk_noise(run.group(0))
        if 2 <= len(cleaned) <= 10:
            words.add(cleaned)
    return words


def _strip_cjk_noise(chunk: str) -> str:
    """把一段中文两头粘着的虚词与泛化词剥掉，留下有业务区分度的那一截。

    「个人生活」剥成空（两个词都是泛化的），整条丢掉；「家庭事务」剥掉「事务」留下
    「家庭」；「商业保险」两个词都有区分度，原样留下。剥的判据是词表，不是长度。

    只剥前后两端、不剥中间：中间的词是构词成分，「社保基金」里的「社保」不能因为
    「基金」不在表里就整条丢掉，也不能把中间切开——切了就把一个词拆成两个都不是词的段。
    """
    cleaned = chunk
    while True:
        for word in _CJK_TRIMMERS_BY_LENGTH:
            if len(cleaned) > len(word) and cleaned.startswith(word):
                cleaned = cleaned[len(word) :]
                break
            if len(cleaned) > len(word) and cleaned.endswith(word):
                cleaned = cleaned[: -len(word)]
                break
        else:
            return cleaned


def extract_scope_keywords(record: EmployeePostRecord) -> set[str]:
    """从岗位的职责定义里提取关键词集合——只取人写的那几栏。

    提取的是「词根」而不是精确词：岗位描述写「证券投研全场景」，目录叫 ``stock``，
    两边字面上一个词都不重合，靠 ``stock`` / ``etf`` / ``投研`` 这些词根才能对上。

    只读 ``title`` / ``description`` / ``work_scope`` / ``member_post_id``，不读
    ``knowledge_domains`` / ``recipes`` / ``data_slots``，理由有三条，每条都是实机跑出来的：

    - **路径不能当判据。** ``data_slots`` 里写着 ``~/.frago/data/stock``，那是「已经绑定的
      领地」，不是「该去认领哪些别的目录」的依据。把路径喂进来，``frago`` / ``data`` 这类
      词就进了关键词表，``~/.frago/data/`` 下每个目录都会被认领一遍。
    - **认领结果不能当判据，否则会滚雪球。** 巡检会把新认领的配方反哺回岗位，下一轮又从
      岗位的配方名里提词，于是「认领了 ``video_clip_annotator``」变成「``video`` 是职责词」，
      再下一轮把 ``~/.frago/data/ai-video``、``video-production`` 一并认领进来。一个股票
      员工的账本里长出视频目录，就是这么来的。
    - **锚点就该是职责定义。** 「以职责范围定义为初始锚点」的字面意思：锚点是岗位立起来时
      人写下的那段话，巡检自己产出什么，都不该把这个锚点挪走。
    """
    parts = [
        record.title,
        record.description,
        record.work_scope,
        record.member_post_id,
    ]
    text = "\n".join(p for p in parts if p)
    tokens = _ascii_tokens(text) | _cjk_words(text)
    return {t for t in tokens if _is_scope_keyword(t)}


def _is_scope_keyword(token: str) -> bool:
    """一个候选词够不够格当认领判据。

    中文与 ASCII 走两条线，因为两者的「最短有意义的词」不一样：ASCII 资源名是
    ``stock`` / ``etf`` / ``dma``，三个字符起（``_ASCII_TOKEN`` 的正则已经卡住这一条）；
    中文的领域词大量是两个字——「家庭」「人际」「社保」「保险」「债务」「存款」全在这里，
    统一按 3 字卡等于把整个中文领域的短词一次性丢干净，岗位描述里写满了也没用。

    2 字词的泛化风险由 ``_CJK_STOPWORDS`` 兜，不由长度兜：长度一刀切会连领域词一起切掉，
    词表只切噪声。
    """
    if not token or token in _STOPWORDS:
        return False
    if _CJK_RUN.fullmatch(token):
        return token not in _CJK_STOPWORDS and 2 <= len(token) <= 10
    return len(token) >= 3


def _matches_scope(name: str, keywords: set[str]) -> bool:
    """资源名是否与职责范围相关。

    ASCII 词根按「词根是名字的一部分」判（``stock`` 命中 ``a_stock_dma``）；3～4 字母的
    短缩写（如 ``etf`` / ``dma`` / ``tts``）要求落在词段边界上，避免 ``tts`` 误命中
    ``https``、``act`` 误命中 ``extract``。

    中文按「谁含谁」双向判：资源名可能是中文（``~/.frago/data/双色球``），而关键词是
    一段整句（``负责双色球走势分析``），单向的「关键词是名字的子串」永远不成立。
    中文名本身很短、领域性强，双向包含不会像碎片滑窗那样随机命中。
    """
    lowered = name.lower()
    if not lowered:
        return False
    for keyword in keywords:
        if _CJK_RUN.fullmatch(keyword):
            if keyword in lowered:
                return True
            if len(lowered) >= 2 and lowered in keyword:
                return True
            continue
        if len(keyword) <= 4:
            if re.search(rf"(?:^|[^a-z0-9]){re.escape(keyword)}s?(?:$|[^a-z0-9])", lowered):
                return True
        elif keyword in lowered:
            return True
    return False


def _read_text_head(path: Path, limit: int = 4096) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return ""


#: 事务目录里常见的网页产物。``~/.frago/data/health-report-reading/`` 下全是这种：
#: 体检报告与就医准备指南都是给人看的 HTML，一个 ``.md`` 都没有。
_HTML_SUFFIXES: frozenset[str] = frozenset({".html", ".htm"})


def _html_to_text(markup: str) -> str:
    """把一段 HTML 折成可读纯文本，够摘要用。

    摘要要的是「这一份是什么」那一句，而 HTML 的正文被标签包着。不折的话，
    一个只有网页产物的事务目录，摘要要么是空的、要么退回一串文件名
    （``cairongqing-mobile.png、report.html、session-id.yaml``）——读的人
    从中读不出这一目录在办什么事，认领判据也拿不到任何中文词。

    脚本与样式整段丢掉：它们是代码，不是内容，混进来会顶掉真正的正文。收尾标签允许
    缺失（``(?:</\\1>|$)``）：正文只读了开头 4096 字节，一份内联样式表很容易长到收尾
    标签落在读取范围之外，只认配对标签的话，整段 CSS 会原样留在「摘要」里，读的人
    看到的第一句成了 ``* { margin:0; padding:0 }``。

    折完按空白重排成一行，与 ``_headline_and_body`` 的输入形状对齐。
    """
    without_scripts = re.sub(
        r"<(script|style)\b[^>]*>.*?(?:</\1>|$)",
        " ",
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = html.unescape(re.sub(r"<[^>]+>", " ", without_scripts))
    return " ".join(text.split())


def _entry_summary(directory: Path) -> str:
    """一个事务目录的业务摘要。

    先找 ``notebook.md`` / ``README.md``；都没有时，退回从目录里的文件名与首个
    ``.md`` 标题里提炼。``~/.frago/data/stock/`` 下大部分事务目录根本没有
    ``notebook.md``，只认它的话摘要会全是空的——账本记了 15 个目录，一个都说不出
    是干什么的，等于没记。

    标题下的第一行正文优先于标题本身：``# 回测报告`` 说的是「这是什么」，紧跟的
    ``口径与复核步骤，结论：信号在震荡市失效`` 说的才是「现在到哪了」。账本里的
    事项结论要跟着工作推进走，取标题的话，正文改了结论也不会变，那这一栏就成了摆设。

    没有 ``.md`` 时退一步读网页产物（``.html``）。这一步不是为了凑数：网页产物在
    事务目录里是常见形态，不读它，这类目录的摘要永远是文件名清单。
    """
    for name in ("notebook.md", "README.md", "readme.md"):
        candidate = directory / name
        if candidate.is_file():
            summary = _headline_and_body(_read_text_head(candidate))
            if summary:
                return summary
    try:
        children = sorted(
            (p for p in directory.iterdir() if not p.name.startswith(".")),
            key=lambda p: p.name,
        )
    except OSError:
        return ""
    for candidate in children:
        if candidate.is_file() and candidate.suffix.lower() == ".md":
            summary = _headline_and_body(_read_text_head(candidate))
            if summary:
                return summary
    for candidate in children:
        if candidate.is_file() and candidate.suffix.lower() in _HTML_SUFFIXES:
            text = _html_to_text(_read_text_head(candidate))
            if text:
                return text[:400]
    # 没有 markdown 也没有网页时用文件名凑一句：``20260818-dma-daily-buy-signals`` 里放着
    # ``a_shares_main_board_signals.csv``，光看目录名读不出这一目录干了什么。
    names = [p.name for p in children if p.is_file()][:4]
    return "、".join(names)


def _headline_and_body(text: str) -> str:
    """从一段 markdown 里取出「这一目录是什么、现在到哪了」那一句。

    两截都要：标题答「这是什么」（``回测报告``），紧跟的正文答「现在到哪了」
    （``结论：信号在震荡市失效``）。只留标题，正文改了结论也不会变，事项那一栏就
    永远停在原地；只留正文，读的人不知道这条目叫什么。
    """
    headline = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        is_heading = stripped.startswith("#")
        cleaned = stripped.lstrip("#").strip()
        if not cleaned:
            continue
        if is_heading:
            if not headline:
                headline = cleaned
            continue
        body = cleaned
        if headline and body != headline:
            return f"{headline}：{body}"
        return body
    return headline


def _date_prefix(name: str) -> str:
    match = re.match(r"^(\d{8})", name)
    return match.group(1) if match else ""


# --- 四类资源的扫描 ---


def _entry_summary_matches(subject: Path, keywords: set[str]) -> str:
    """主体目录名对不上职责词时，退一步看它里面最近几件事的摘要对不对得上。

    这一条是为「目录名是英文、内容全是中文」的岗位加的。个人助理的职责词是「家庭」
    「人际」「社保」，而本机对应的目录叫 ``family-health``、``relationships``、
    ``health-report-reading``——名字里一个中文都没有，职责词一个都匹配不上。而这三个
    目录里面的东西恰恰是中文的：体检报告解读、就医准备、人际关系看板需求。不看内容，
    这些目录永远认领不到；看名字，永远认不出它们属于谁。

    只看最近 3 个子目录，不递归、不全读：一个主体目录下可能有几十件事，逐件读摘要是
    一笔真开销，而判据只需要「这里有几件事跟我的职责对得上」。最新那几件是岗位当下
    在办的事，代表性最强。

    返回命中的那段摘要（空串表示没命中）。把命中的原话交回去而不是只回布尔值，
    是因为页面要把「它凭什么被认领」摆给人看——人凭一句话就能判断这是不是误伤，
    凭一个词则判断不了。
    """
    try:
        transactions = sorted(
            (p for p in subject.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name,
            reverse=True,
        )
    except OSError:
        return ""
    for transaction in transactions[:3]:
        summary = _entry_summary(transaction)
        if summary and _matches_scope(summary, keywords):
            return summary
    return ""


def _with_tilde(path: str) -> str:
    """把绝对路径写成 ``~/`` 开头，与岗位编制里的写法对齐。

    岗位编制里人写的是 ``~/.frago/data/stock``，巡检发现的是 ``/Users/<人>/.frago/data/stock``。
    两种写法指向同一处而字面不同，混着写回编制，同一个槽位会以两种写法各占一行，之后
    每读一次岗位都要人去判断它们是不是一回事。
    """
    home = str(Path.home())
    return f"~{path[len(home):]}" if path.startswith(home) else path


def _domain_evidence_keywords(domains: Sequence[dict[str, Any]]) -> set[str]:
    """已认领知识域的用途里，那些**中文**业务词也算这个岗位的职责证据。

    为什么需要这一条：知识域的用途栏是人给这个领域写下的一句自述，比岗位描述更贴具体
    业务，而本机数据目录里放的东西常常只跟这句自述对得上、跟岗位描述对不上。

    实机例子：个人助理的职责词里有「家庭」，据此认领到知识域 ``family-health``，它的用途
    写着「家庭成员健康与体检知识：体检报告解读结论、异常指标、随访待办、就医建议」。
    本机有个数据目录 ``health-report-reading``，里面全是体检报告解读与就医准备——它讲的是
    「体检」「就医」，一个「家庭」字都没有，按岗位职责词永远匹配不上。可它是这个岗位管的
    那个知识域的产出，认领它是对的。不看这一层，这类目录就一直漏在外面。

    **只取中文词，绝不取 ASCII 词。** 这一条是实机撞出来的：``etf-research`` 的用途里写着
    「agent 工作流最佳实践」，`agent` 就这么进了判据，于是 ``data-agent-lite``、
    ``prod-rec-agent-service``、``rea-agent`` 这些跟股票毫无关系的目录全被认领进来，股票
    岗位的账本从 4 个数据目录涨到 23 个。用途是中文业务语言，ASCII 词在中文句子里多半是
    泛指（``agent``、``api``、``web``），拿它当领域判据只会把整台机器认领一遍。

    只走一跳，不递归：这里产出的词不再拿去认领新的知识域，否则「认领了 A → A 的用途词
    又认领 B → B 的用途词再认领 C」会一路滚下去，账本最后变成「全都要」。
    """
    if not domains:
        return set()
    blob = " ".join(str(d.get("purpose", "")) for d in domains if d.get("purpose"))
    if not blob:
        return set()
    return {t for t in _cjk_words(blob) if _is_scope_keyword(t)}


def list_available_resources() -> dict[str, list[dict[str, Any]]]:
    """本机此刻有哪些资源可以绑给员工：数据目录、知识域、配方。

    与巡检是两件事，判据正好相反：巡检拿职责词去**筛**，猜「这个岗位大概管什么」；这里
    一条都不筛，答「这台机器上有什么」，由人在页面上挑。筛过的那份给不出「还有哪些没绑上」，
    而人补绑、改判、撤销上次剔除，靠的正是这份全量清单。

    三类各自只读最浅的一层：数据目录与知识域只列名字，知识域多带一句注册表里的用途，
    配方读 ``recipe.md`` 的 frontmatter 取中文标题与描述。页面要的是「这是什么」，
    不是资源全文——把配方正文读进来，一屏几百条的清单会变得没法扫。
    """
    return {
        "data_slots": _list_available_data_slots(),
        "knowledge_domains": _list_available_knowledge_domains(),
        "recipes": _list_available_recipes(),
    }


def _list_available_data_slots() -> list[dict[str, Any]]:
    """``~/.frago/data/`` 下的一级主体目录，路径统一写成 ``~/`` 形式。

    与巡检写回编制用的是同一串字，页面选中后原样存进编制，不需要在三个地方各做一次
    绝对路径与 ``~`` 的换算。
    """
    data_root = frago_home() / "data"
    if not data_root.is_dir():
        return []
    try:
        subjects = sorted(
            (p for p in data_root.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name,
        )
    except OSError:
        return []
    return [{"path": _with_tilde(str(p.resolve())), "name": p.name} for p in subjects]


def _list_available_knowledge_domains() -> list[dict[str, Any]]:
    """``~/.frago/books/`` 下的一级知识域，带上注册表里写的那句用途。

    用途就是给人做判断用的：域名多半是英文（``family-health``），光看名字判断不出
    它该归谁管，而注册表里那句「家庭成员健康与体检知识」一眼就够。
    """
    books_root = frago_home() / "books"
    if not books_root.is_dir():
        return []
    purposes = _read_books_registry_purposes()
    try:
        domains = sorted(
            (p for p in books_root.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name,
        )
    except OSError:
        return []
    return [
        {"name": p.name, "purpose": purposes.get(p.name, "")} for p in domains
    ]


def _read_books_registry_purposes() -> dict[str, str]:
    """``books/registry.json`` 里每个知识域写的那句用途。读不动就按「没写」处理。"""
    registry_path = frago_home() / "books" / "registry.json"
    if not registry_path.is_file():
        return {}
    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(k): str((v or {}).get("purpose", ""))
        for k, v in raw.items()
        if isinstance(v, dict)
    }


def _recipe_candidates() -> list[Path]:
    """本机所有配方的 ``recipe.md``，按路径排序。

    配方在磁盘上的目录约定与配方系统自己的注册表一致（``frago.recipes.registry``）：
    顶层三个子目录各放一层，``workflows/<配方>/recipe.md`` 是两层，而
    ``atomic/chrome/<配方>/recipe.md`` 与 ``atomic/system/<配方>/recipe.md`` 是三层。
    只 glob ``*/*/recipe.md`` 会把 atomic 下的配方整类漏掉——漏得没有声音，账本里
    本岗位真在用的工具就这么少了一批。这里按约定逐个扫，同时保留原来那条通配，
    免得约定之外的目录布局（用户自己放在顶层别的目录下）反而被新写法丢掉。
    """
    recipes_root = frago_home() / "recipes"
    if not recipes_root.is_dir():
        return []
    candidates: set[Path] = set(recipes_root.glob("*/*/recipe.md"))
    for subdir in _RECIPE_SUBDIRS:
        candidates.update((recipes_root / subdir).glob("*/recipe.md"))
    return sorted(candidates)


def _read_recipe_frontmatter(metadata_path: Path) -> dict[str, Any]:
    """读一个 ``recipe.md`` 的 frontmatter：名字、类型、描述、中文标题、标签。

    只看顶层键（缩进为 0）。配方文件里 ``description:`` 出现很多次——顶层一次，
    底下每个 mode 与参数各一次。逐行扫而不判缩进，最后读到的是某个参数的说明，
    账本里那条配方的「是什么意思」就变成了一句 ``mode=detail 用，stock | etf``。
    """
    name = metadata_path.parent.name
    head = _read_text_head(metadata_path, 8192)
    description = ""
    recipe_type = ""
    display_title = ""
    tags: list[str] = []
    if head.startswith("---"):
        end = head.find("\n---", 3)
        front = head[3:end] if end != -1 else head[3:]
        in_title_block = False
        for line in front.splitlines():
            if line and not line[0].isspace():
                stripped = line.strip()
                in_title_block = stripped.startswith("title:")
                if stripped.startswith("description:"):
                    description = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                elif stripped.startswith("type:"):
                    recipe_type = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("tags:"):
                    tags = [
                        t.strip().strip('"').strip("'")
                        for t in stripped.split(":", 1)[1].strip("[]").split(",")
                        if t.strip()
                    ]
                continue
            # ``title:`` 块里的中文名是缩进写的，唯一一处需要往下看的缩进行。
            if in_title_block:
                stripped = line.strip()
                if stripped.startswith("zh-CN:"):
                    display_title = (
                        stripped.split(":", 1)[1].strip().strip('"').strip("'")
                    )
    return {
        "name": name,
        "type": recipe_type,
        "description": description,
        "display_title": display_title,
        "tags": tags,
    }


def _list_available_recipes() -> list[dict[str, Any]]:
    """本机配方清单：名字、中文标题、一句话描述。"""
    return [
        {
            "name": meta["name"],
            "display_title": meta["display_title"],
            "description": meta["description"],
        }
        for meta in (_read_recipe_frontmatter(p) for p in _recipe_candidates())
    ]


def _scan_data_slots(
    record: EmployeePostRecord,
    keywords: set[str],
    cursor: LedgerCursor,
    *,
    excluded: EmployeeLedger | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """扫 ``~/.frago/data/`` 下与职责相关的主体目录及其事务目录。

    返回 ``(认领的槽位, 新增/变化的事务条目, 活跃事项, 本轮指纹)``。

    主体目录的认领不只看岗位已绑定的 ``data_slots``：岗位描述里写着「股票与 ETF 投研」，
    而 ``data_slots`` 是空的（新建岗位的常态），这时按职责词主动去找 ``data/stock``、
    ``data/a_stock_dma``、``data/etf`` 才是「主动资源查找」本身。

    三条判据依次试，任一成立即认领，``discovered_by`` 记下是哪一条成立的：

    1. ``bound``：岗位编制里已经绑着它；
    2. ``scope_keywords``：目录名对得上职责词；
    3. ``entry_summary``：目录名对不上，但里面最近几件事的摘要对得上。

    第三条是关键补充。只看目录名的话，「名字是英文、内容是中文」的目录整类认不到——
    个人助理的职责词是「家庭」「人际」，而 ``family-health``、``relationships`` 这些
    目录名里一个中文都没有。

    人否决过的槽位（``excluded``）直接跳过：职责词匹配天然会误伤，人能删一次却删不干净，
    这个删除动作就是假的。
    """
    data_root = frago_home() / "data"
    claimed_slots: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    digests: dict[str, str] = {}
    if not data_root.is_dir():
        return claimed_slots, entries, topics, digests

    bound = {
        Path(slot).expanduser().resolve()
        for slot in record.data_slots
        if str(slot).strip()
    }

    try:
        subjects = sorted(p for p in data_root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return claimed_slots, entries, topics, digests

    for subject in subjects:
        resolved = subject.resolve()
        canonical = _with_tilde(str(resolved))
        if is_resource_excluded(excluded, "data_slots", canonical) or is_resource_excluded(
            excluded, "data_slots", str(subject)
        ):
            continue
        is_bound = resolved in bound
        discovered_by = "bound"
        evidence = ""
        if not is_bound:
            if _matches_scope(subject.name, keywords):
                discovered_by = "scope_keywords"
            else:
                evidence = _entry_summary_matches(subject, keywords)
                if not evidence:
                    continue
                discovered_by = "entry_summary"
        claimed_slots.append(
            {
                # 路径统一写成 ``~/`` 开头：编制、账本、页面三处看到的必须是同一串字，
                # 否则同一个目录会以两种写法各占一行。
                "path": canonical,
                "name": subject.name,
                "bound": is_bound,
                "discovered_by": discovered_by,
                "evidence": evidence,
            }
        )
        try:
            transactions = sorted(
                (p for p in subject.iterdir() if p.is_dir() and not p.name.startswith(".")),
                key=lambda p: p.name,
            )
        except OSError:
            continue
        for transaction in transactions:
            digest = digest_path_entry(transaction)
            # 指纹与游标里记的一致 ⇒ 自上次记账以来没动过，跳过不重记。
            if cursor.processed_data_entries.get(str(transaction)) == digest:
                continue
            digests[str(transaction)] = digest
            summary = _entry_summary(transaction)
            entry = {
                "path": str(transaction),
                "name": transaction.name,
                "slot": str(subject),
                "date_prefix": _date_prefix(transaction.name),
                "summary": summary,
                "digest": digest,
            }
            entries.append(entry)
            topics.append(
                {
                    "topic_key": f"data:{transaction}",
                    "title": transaction.name,
                    "status": "archived",
                    "latest_conclusion": summary or "（未写出结论摘要）",
                    "artifacts": [str(transaction)],
                }
            )
    return claimed_slots, entries, topics, digests


def _scan_recipes(
    keywords: set[str],
    cursor: LedgerCursor,
    *,
    excluded: EmployeeLedger | None = None,
    record: EmployeePostRecord | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """扫本机配方，认领与职责相关的那些。

    读的是 ``recipe.md`` 的 frontmatter（名字、类型、描述、标签），不是注册表：
    领域层不许 import 服务端，而配方文件本身就在 ``~/.frago/recipes/`` 下，直接读它
    反而少一层依赖。指纹取描述与标签的哈希，改过描述才重记。
    """
    recipes_root = frago_home() / "recipes"
    claimed: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    digests: dict[str, str] = {}
    if not recipes_root.is_dir():
        return claimed, topics, digests

    bound_recipes = (
        {str(r).strip() for r in record.recipes if str(r).strip()}
        if record is not None
        else set()
    )
    is_meta_author_post = (
        record is not None and record.member_post_id in ("recipe-builder", "hr")
    )

    for metadata_path in _recipe_candidates():
        meta = _read_recipe_frontmatter(metadata_path)
        name = meta["name"]
        description = meta["description"]
        if is_resource_excluded(excluded, "recipes", name):
            continue
        is_bound = name in bound_recipes
        blob = " ".join([name, description, *meta["tags"]])
        if not is_bound and (is_meta_author_post or not _matches_scope(blob, keywords)):
            continue
        digest = digest_text(blob)
        if cursor.recipe_digests.get(name) == digest:
            continue
        digests[name] = digest
        claimed.append(
            {
                "name": name,
                "type": meta["type"],
                "description": description,
                "display_title": meta["display_title"],
                "tags": meta["tags"],
                "digest": digest,
                "path": str(metadata_path),
            }
        )
        topics.append(
            {
                "topic_key": f"recipe:{name}",
                "title": name,
                "status": "available",
                "latest_conclusion": description or "（配方未写描述）",
                "artifacts": [str(metadata_path)],
            }
        )
    return claimed, topics, digests


def _scan_domains(
    keywords: set[str],
    cursor: LedgerCursor,
    *,
    excluded: EmployeeLedger | None = None,
    record: EmployeePostRecord | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """扫 ``~/.frago/books/`` 下的知识域，认领与职责相关的那些。

    指纹取「文档数 + 最近更新的那篇」的组合：知识域是持续往里加条目的，条数变了说明
    有新内容；条数没变但最近那篇换人了，说明有人在修订，两种都值得重记一次。

    认领判据看两处：域名的英文标识（``family-health``）与注册表里写的用途
    （「家庭成员健康与体检知识」）。只看名字的话，英文域名对不上中文职责词，一整批
    本机真实存在的知识域永远认领不到——而那正是「员工自己去找家底」最该找到的东西。
    """
    books_root = frago_home() / "books"
    claimed: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    digests: dict[str, str] = {}
    if not books_root.is_dir():
        return claimed, topics, digests

    registry_purposes = _read_books_registry_purposes()
    bound_domains = (
        {str(d).strip() for d in record.knowledge_domains if str(d).strip()}
        if record is not None
        else set()
    )

    try:
        domains = sorted(p for p in books_root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return claimed, topics, digests

    for domain in domains:
        if is_resource_excluded(excluded, "knowledge_domains", domain.name):
            continue
        purpose = registry_purposes.get(domain.name, "")
        is_bound = domain.name in bound_domains
        if not is_bound and not _matches_scope(f"{domain.name} {purpose}", keywords):
            continue
        try:
            docs = sorted(
                (p for p in domain.iterdir() if p.is_file() and not p.name.startswith(".")),
                key=lambda p: p.name,
            )
        except OSError:
            docs = []
        newest = docs[-1].name if docs else ""
        digest = digest_text(f"{len(docs)}:{newest}")
        if cursor.domain_digests.get(domain.name) == digest:
            continue
        digests[domain.name] = digest
        claimed.append(
            {
                "name": domain.name,
                "purpose": purpose,
                "doc_count": len(docs),
                "path": str(domain),
            }
        )
        topics.append(
            {
                "topic_key": f"domain:{domain.name}",
                "title": domain.name,
                "status": "available",
                "latest_conclusion": purpose or f"共 {len(docs)} 篇文档",
                "artifacts": [str(domain)],
            }
        )
    return claimed, topics, digests


_SESSION_EMPLOYEE_BLOCK_RE = re.compile(
    r'<frago-employee\s+id="([^"]+)"[^>]*>[\s\S]*?</frago-employee>\s*',
    re.IGNORECASE,
)
_SESSION_SKILL_BLOCK_RE = re.compile(
    r"<must-use-skill\b[^>]*>[\s\S]*?</must-use-skill>\s*",
    re.IGNORECASE,
)
_SESSION_SYSTEM_REMINDER_RE = re.compile(
    r"<system-reminder>[\s\S]*?</system-reminder>\s*",
    re.IGNORECASE,
)
_SESSION_USER_REQUEST_BLOCK_RE = re.compile(
    r"<USER_REQUEST>([\s\S]*?)</USER_REQUEST>",
    re.IGNORECASE,
)
_SESSION_PROMPT_FILE_BLOCK_RE = re.compile(
    r'<frago-prompt-file\s+path="([^"]+)"[^>]*>[\s\S]*?</frago-prompt-file>(?:\r?\n([^\n]*))?',
    re.IGNORECASE,
)
_SESSION_CORES: tuple[str, ...] = (
    "claude",
    "agy",
    "codex",
    "opencode",
    "coreagent",
    "claude-misc",
)
_SESSION_TAIL_BYTES = 64 * 1024


def _restore_prompt_file_in_text(text: str) -> str:
    """还原 `agy` 驱动压缩的 `<frago-prompt-file path="...">` 块原文。"""
    if "<frago-prompt-file" not in text:
        return text

    def _replace(match: re.Match[str]) -> str:
        raw_path = (match.group(1) or "").strip()
        preview = (match.group(2) or "").strip()
        if raw_path:
            try:
                p = Path(raw_path).expanduser()
                if p.is_file():
                    loaded = p.read_text(encoding="utf-8", errors="replace").strip()
                    if loaded:
                        return loaded
            except OSError:
                pass
        return preview

    return _SESSION_PROMPT_FILE_BLOCK_RE.sub(_replace, text).strip()


def strip_injected_session_blocks(text: str) -> tuple[str | None, str]:
    """剥离会话首句中的 `<USER_REQUEST>` 外层元数据、`<frago-prompt-file>`、`<frago-employee>`、`<must-use-skill>` 与 `<system-reminder>`，返回 `(employee_id, 真实用户原话)`。"""
    if not text:
        return None, ""
    req_match = _SESSION_USER_REQUEST_BLOCK_RE.search(text)
    cleaned = req_match.group(1).strip() if req_match is not None else text.strip()
    cleaned = _restore_prompt_file_in_text(cleaned)
    emp_id: str | None = None
    match = _SESSION_EMPLOYEE_BLOCK_RE.search(cleaned)
    if match:
        emp_id = match.group(1).strip() or None
        cleaned = (cleaned[: match.start()] + cleaned[match.end() :]).strip()
    cleaned = _SESSION_SKILL_BLOCK_RE.sub("", cleaned)
    cleaned = _SESSION_SYSTEM_REMINDER_RE.sub("", cleaned)
    return emp_id, cleaned.strip()


def _extract_record_role_and_text(record: dict[str, Any]) -> tuple[str, str, str]:
    """从一条 `raw.jsonl` 或 `steps.jsonl` 记录中提取 `(role, text, iso_timestamp)`。"""
    stamp = ""
    raw_ts = record.get("timestamp")
    if isinstance(raw_ts, str) and raw_ts.strip():
        stamp = raw_ts.strip()
    elif "step_index" in record and isinstance(record.get("created_at"), str):
        stamp = str(record["created_at"]).strip()
    else:
        moment = record.get("time")
        if isinstance(moment, dict):
            ms = moment.get("end") or moment.get("start")
            if isinstance(ms, (int, float)) and ms > 0:
                try:
                    stamp = datetime.fromtimestamp(ms / 1000).isoformat(timespec="seconds")
                except (OSError, OverflowError, ValueError):
                    stamp = ""

    # 1. steps.jsonl 加工副本
    rtype = record.get("type")
    if rtype in ("user", "assistant") and "content_summary" in record:
        return str(rtype), str(record.get("content_summary") or "").strip(), stamp

    # 2. agy raw.jsonl
    if "step_index" in record:
        if rtype == "USER_INPUT":
            return "user", str(record.get("content") or "").strip(), stamp
        if rtype == "PLANNER_RESPONSE":
            return "assistant", str(record.get("content") or "").strip(), stamp
        return "", "", stamp

    # 3. claude / coreagent raw.jsonl
    msg = record.get("message")
    role = (msg.get("role") or rtype) if isinstance(msg, dict) else rtype
    if role in ("user", "assistant"):
        content = msg.get("content") if isinstance(msg, dict) else record.get("content")
        if isinstance(content, str):
            return str(role), content.strip(), stamp
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") in (None, "text"):
                    val = block.get("text")
                    if isinstance(val, str) and val.strip():
                        parts.append(val.strip())
            return str(role), "\n".join(parts).strip(), stamp

    # 4. codex raw.jsonl
    payload = record.get("payload")
    if isinstance(payload, dict):
        if rtype == "event_msg" and payload.get("type") == "user_message":
            return "user", str(payload.get("message") or "").strip(), stamp
        p_role = payload.get("role")
        if rtype == "response_item" and p_role in ("user", "assistant"):
            blocks = payload.get("content")
            if isinstance(blocks, str):
                return str(p_role), blocks.strip(), stamp
            if isinstance(blocks, list):
                c_parts = [
                    str(b.get("text") or "").strip()
                    for b in blocks
                    if isinstance(b, dict) and isinstance(b.get("text"), str)
                ]
                return str(p_role), "\n".join(p for p in c_parts if p).strip(), stamp

    # 5. opencode 片段
    if isinstance(record.get("text"), str) and record.get("text", "").strip():
        oc_role = str(record.get("role") or ("user" if rtype == "user" else "assistant"))
        return oc_role, str(record["text"]).strip(), stamp

    return "", "", stamp


_DEFAULT_CONTEXT_WINDOW = 500_000
_CONTEXT_AMPLE_LIMIT = 500_000


def _extract_record_context_tokens(record: dict[str, Any]) -> tuple[int | None, int | None]:
    """从单条转录记录中提取 `(context_tokens, context_window)`，无用量字段时返回 `(None, None)`。"""
    import contextlib

    with contextlib.suppress(Exception):
        from frago.session.usage_tick import (
            PROMPT_FIELDS,
            breakdown_from_agy_record,
            breakdown_from_claude_usage,
            breakdown_from_codex_usage,
            breakdown_from_opencode_tokens,
        )

        if isinstance(record.get("context_tokens"), int | float) and record["context_tokens"] > 0:
            win = record.get("context_window")
            return (
                int(record["context_tokens"]),
                int(win) if isinstance(win, int | float) and win > 0 else None,
            )

        msg = record.get("message")
        usage = msg.get("usage") if isinstance(msg, dict) else record.get("usage")
        if isinstance(usage, dict):
            bd = breakdown_from_claude_usage(usage)
            ctx = sum(bd.get(f, 0) for f in PROMPT_FIELDS)
            if ctx > 0:
                win = (
                    (msg.get("context_window") if isinstance(msg, dict) else None)
                    or usage.get("context_window")
                    or record.get("context_window")
                )
                return ctx, int(win) if isinstance(win, int | float) and win > 0 else None

        if "step_index" in record:
            bd_agy = breakdown_from_agy_record(record)
            if bd_agy:
                ctx = sum(bd_agy.get(f, 0) for f in PROMPT_FIELDS)
                if ctx > 0:
                    return ctx, None

        payload = record.get("payload")
        if (
            record.get("type") == "event_msg"
            and isinstance(payload, dict)
            and payload.get("type") == "token_count"
        ):
            info = payload.get("info")
            if isinstance(info, dict):
                last = info.get("last_token_usage")
                if isinstance(last, dict):
                    bd_cdx = breakdown_from_codex_usage(last)
                    ctx = sum(bd_cdx.get(f, 0) for f in PROMPT_FIELDS)
                    win = info.get("model_context_window")
                    if ctx > 0:
                        return (
                            ctx,
                            int(win) if isinstance(win, int | float) and win > 0 else None,
                        )

        tokens = record.get("tokens")
        if isinstance(tokens, dict):
            bd_oc = breakdown_from_opencode_tokens(tokens)
            if bd_oc:
                ctx = sum(bd_oc.get(f, 0) for f in PROMPT_FIELDS)
                if ctx > 0:
                    return ctx, None

    return None, None


def format_context_watermark(
    context_tokens: int | None,
    context_window: int | None = None,
) -> tuple[str, int, str]:
    """将会话上下文 token 数格式化为 `(capacity_state, pct, watermark_label)`。

    仅分两档（以 500k tokens 为唯一分界）：
    - ``low``（`< 500k`）：充裕，可继续往该会话塞入同事务新 prompt；
    - ``high``（`>= 500k`）：不充裕，严禁再往该会话塞入新 prompt，必须新开 Worker 会话。
    """
    tok = max(int(context_tokens or 0), 0)
    win = (
        int(context_window)
        if isinstance(context_window, int | float) and int(context_window) > 0
        else _DEFAULT_CONTEXT_WINDOW
    )
    if tok <= 0:
        return "low", 0, "未知（< 500k · 充裕）"
    pct = round(tok * 100 / win)
    tok_str = f"{tok / 1000:.1f}k" if tok >= 1000 else f"{tok}"
    if tok >= _CONTEXT_AMPLE_LIMIT:
        return (
            "high",
            pct,
            f"{tok_str}（>= 500k · 不充裕：严禁继续塞入新 prompt，请新开 Worker 会话）",
        )
    return (
        "low",
        pct,
        f"{tok_str}（< 500k · 充裕：可继续塞入同事务新 prompt）",
    )


def _inspect_session_dir(
    session_dir: Path,
    session_id: str,
    raw_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """读取单个会话目录的首条真实用户诉求、末尾助手结论摘要与上下文水位（自动剥离 `<frago-employee>` 注入块）。"""
    meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
    if not meta:
        meta_path = session_dir / "metadata.json"
        if meta_path.is_file():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    meta = loaded
            except (json.JSONDecodeError, OSError):
                meta = {}

    started_at = str(meta.get("started_at", "") or "").strip()
    last_activity = str(meta.get("last_activity", "") or "").strip()
    first_prompt = ""
    emp_id: str | None = None
    latest_conclusion = ""
    context_tokens: int | None = None
    context_window: int | None = None
    max_file_bytes = 0

    raw_name = str(meta.get("name", "") or "").strip()
    if raw_name:
        name_emp, cleaned_name = strip_injected_session_blocks(raw_name)
        if name_emp and not emp_id:
            emp_id = name_emp
        meta["name"] = cleaned_name

    transcript_files = [
        p for p in (session_dir / "raw.jsonl", session_dir / "steps.jsonl") if p.is_file()
    ]
    for path in transcript_files:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for _ in range(80):
                    line = handle.readline()
                    if not line:
                        break
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    role, text, stamp = _extract_record_role_and_text(rec)
                    if stamp and not started_at:
                        started_at = stamp
                    if role == "user" and text and not first_prompt:
                        found_emp, clean_user = strip_injected_session_blocks(text)
                        if found_emp and not emp_id:
                            emp_id = found_emp
                        if clean_user:
                            first_prompt = " ".join(clean_user.split())[:400]
                            break
        except OSError:
            pass
        if first_prompt:
            break

    for path in transcript_files:
        try:
            size = path.stat().st_size
            if size <= 0:
                continue
            max_file_bytes = max(max_file_bytes, size)
            read_len = min(size, _SESSION_TAIL_BYTES)
            with path.open("rb") as handle:
                handle.seek(size - read_len)
                chunk = handle.read(read_len)
            lines = chunk.split(b"\n")
            if size > read_len:
                lines = lines[1:]
            for raw_line in reversed(lines):
                if not raw_line.strip():
                    continue
                try:
                    rec = json.loads(raw_line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if context_tokens is None:
                    c_tok, c_win = _extract_record_context_tokens(rec)
                    if c_tok is not None and c_tok > 0:
                        context_tokens = c_tok
                        context_window = c_win
                role, text, stamp = _extract_record_role_and_text(rec)
                if stamp and not last_activity:
                    last_activity = stamp
                if role == "assistant" and text and not latest_conclusion:
                    _, clean_ans = strip_injected_session_blocks(text)
                    compact = " ".join(
                        line.strip().lstrip("#*- ").strip()
                        for line in clean_ans.splitlines()
                        if line.strip()
                    )
                    if compact:
                        latest_conclusion = compact[:240]
                if last_activity and latest_conclusion and context_tokens is not None:
                    break
        except OSError:
            pass
        if latest_conclusion and context_tokens is not None:
            break

    if context_tokens is None and max_file_bytes > 0:
        # 若归档行未记录显式 usage 字段，按转录字节数保守估算上下文水位（约 4 字节/token）
        context_tokens = max(1, max_file_bytes // 4)

    cap_state, cap_pct, cap_label = format_context_watermark(context_tokens, context_window)
    title = _session_title(meta, first_prompt, session_id)
    entry_dict: dict[str, Any] = {
        "session_id": session_id,
        "employee_id": emp_id,
        "started_at": started_at,
        "last_activity": last_activity or started_at,
        "title": title,
        "first_prompt_summary": first_prompt[:200],
        "latest_conclusion": latest_conclusion or first_prompt[:200] or "（无首条消息摘要）",
        "context_tokens": context_tokens or 0,
        "context_window": context_window or _DEFAULT_CONTEXT_WINDOW,
        "context_pct": cap_pct,
        "context_state": cap_state,
        "context_watermark": cap_label,
    }
    import contextlib

    with contextlib.suppress(Exception):
        from frago.session.store import get_default_session_store

        ont_rec = get_default_session_store().get(session_id)
        if ont_rec is not None:
            entry_dict["lifecycle_state"] = ont_rec.lifecycle_state
            entry_dict["origin"] = ont_rec.origin
            if ont_rec.is_worker:
                entry_dict["is_worker"] = True
    return entry_dict


def _locate_session_dir_by_id(sessions_root: Path, session_id: str) -> Path | None:
    """在 `~/.frago/sessions/<core>/<session_id>` 下直接按路径定位会话目录。"""
    clean_id = str(session_id or "").strip()
    if not clean_id or not sessions_root.is_dir():
        return None
    for core in _SESSION_CORES:
        candidate = sessions_root / core / clean_id
        if candidate.is_dir():
            return candidate
    return None


def _session_first_prompt(session_dir: Path) -> str:
    """会话的第一条用户消息，一行（自动剥离 `<frago-employee>` 语境块）。"""
    info = _inspect_session_dir(session_dir, session_dir.name)
    return str(info.get("first_prompt_summary") or "")


def _session_title(raw: dict[str, Any], first_prompt: str, session_id: str) -> str:
    """一场会话在账本里叫什么。

    ``metadata.json`` 的 ``name`` 优先，但只有它是「人给这场所起的名」时才算数。派活型的
    会话里那一栏常常是投给 agent 的系统提示词原文（``你是 frago recipe 开发专家。任务：
    根据 spec 创建 recipe……``），把它当标题，账本里就会出现一串一模一样的「你是……专家」，
    读的人分不清哪场是哪场。

    ``first_prompt`` 也过同一道筛：派活型会话的第一条消息就是那段任务书本身，直接拿它
    顶替，标题里那串「你是……专家」原样还在。
    """
    _, raw_name = strip_injected_session_blocks(str(raw.get("name", "") or "").strip())
    name = " ".join(raw_name.split())
    if name and name != "-" and not _looks_like_system_prompt(name):
        return name[:80]
    _, clean_prompt = strip_injected_session_blocks(first_prompt.strip())
    prompt = " ".join(clean_prompt.split())
    if prompt and not _looks_like_system_prompt(prompt):
        return prompt[:60]
    # 名字与首句都是任务书：从里面捞出它到底在做什么，总比一串「你是……专家」强。
    intent = _intent_from_prompt(prompt or name)
    if intent:
        return intent
    return session_id


def _looks_like_system_prompt(text: str) -> bool:
    """这段话是不是一段派给 agent 的任务书，而不是会话标题。"""
    stripped = text.strip()
    if stripped.startswith(("你是", "You are", "你是一位", "<frago-employee")):
        return True
    if len(stripped) > 120:
        return True
    return "\n" in stripped


#: 任务书里常见的那几个动作词，用来从「你是……专家。任务：<做什么>」里取出「做什么」。
_TASK_MARKERS = ("任务：", "任务:", "目标：", "目标:", "Task:")


def _intent_from_prompt(prompt: str) -> str:
    """从一段任务书里取出「这一场到底在做什么」那一句。

    ``你是 frago recipe 开发专家。任务：根据 spec 创建 recipe 'stock_volatility_adaptive_lab'``
    → ``根据 spec 创建 recipe 'stock_volatility_adaptive_lab'``。
    """
    for marker in _TASK_MARKERS:
        position = prompt.find(marker)
        if position == -1:
            continue
        tail = prompt[position + len(marker) :].strip()
        if tail:
            return " ".join(tail.split())[:60]
    return ""


def resolve_employee_recent_sessions(
    record: EmployeePostRecord,
    ledger: EmployeeLedger | None = None,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """汇总该员工的近期会话脉络（优先本岗 `active_session_ids` 历次会话，合并账本认领的相关会话）。

    新开员工会话时从 0 历史消息 Token 启动，但通过该函数实时提取本岗最近会话的 `session_id`、
    用户真实诉求与最新结论摘要，供新会话按需执行 `frago session ask <session_id> "<问题>"` 续接。
    """
    sessions_root = frago_home() / "sessions"
    by_id: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []

    if ledger is not None:
        for item in ledger.claimed_resources.get("matched_sessions") or []:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("session_id") or "").strip()
            if not sid:
                continue
            by_id[sid] = dict(item)

    # 本岗自己的 active_session_ids 按逆序（最近启动的排最前）实时读取最新结论
    for sid in reversed(record.active_session_ids):
        clean_sid = str(sid or "").strip()
        if not clean_sid or clean_sid in ordered_ids:
            continue
        ordered_ids.append(clean_sid)
        session_dir = _locate_session_dir_by_id(sessions_root, clean_sid)
        if session_dir is not None:
            inspected = _inspect_session_dir(session_dir, clean_sid)
            inspected["bound_to_post"] = True
            by_id[clean_sid] = inspected
        elif clean_sid in by_id:
            by_id[clean_sid]["bound_to_post"] = True
        else:
            by_id[clean_sid] = {
                "session_id": clean_sid,
                "started_at": "",
                "last_activity": "",
                "title": f"本岗会话 {clean_sid[:8]}",
                "first_prompt_summary": "",
                "latest_conclusion": "",
                "bound_to_post": True,
            }

    for sid in by_id:
        if sid not in ordered_ids:
            ordered_ids.append(sid)

    result: list[dict[str, Any]] = []
    for sid in ordered_ids[: max(limit, 0)]:
        entry = by_id.get(sid)
        if entry:
            result.append(entry)
    return result


def resolve_employee_worker_sessions(
    record: EmployeePostRecord,
    ledger: EmployeeLedger | None = None,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """汇总本岗位主会话派出的 Worker 会话池（含运行中与已完成可续接的 Worker 会话）。

    帮助 Employee 作为管理者清晰掌握「哪些 Worker 会话在执行哪些任务、当前新任务适合塞进
    哪个已存在的 Worker 会话继续执行（`frago agent --resume <session_id> --prompt-file <任务书.md>`），
    还是应该新开一个 Worker 会话执行（`frago agent --prompt-file <任务书.md>`）」。
    """
    import contextlib

    sessions_root = frago_home() / "sessions"
    own_parent_ids: set[str] = {
        str(sid).strip() for sid in record.active_session_ids if str(sid).strip()
    }
    if ledger is not None:
        for item in ledger.claimed_resources.get("matched_sessions") or []:
            if isinstance(item, dict) and item.get("bound_to_post"):
                sid = str(item.get("session_id") or "").strip()
                if sid:
                    own_parent_ids.add(sid)

    launch_entries: list[dict[str, Any]] = []
    origin_parents: dict[str, str] = {}
    with contextlib.suppress(Exception):
        from frago.session import session_origin

        for raw in session_origin._ledger_entries():
            parsed = session_origin._parse_entry(raw)
            if parsed is not None:
                launch_entries.append(parsed)
        idx = session_origin.load_origin_index()
        origin_parents = dict(idx.parents)
        for child_sid, parent_sid in origin_parents.items():
            rel = idx.relation_of(child_sid)
            if rel is not None and rel.kind == "branch" and parent_sid in own_parent_ids:
                own_parent_ids.add(child_sid)

    if not own_parent_ids:
        return []

    # 包含多级派活（Employee 主会话 -> Worker -> 子 Worker，最多追溯 3 层）
    tracked_parents = set(own_parent_ids)
    worker_meta_by_id: dict[str, dict[str, Any]] = {}
    ordered_worker_ids: list[str] = []

    for _ in range(3):
        added = False
        for entry in launch_entries:
            if entry.get("kind") != "dispatch":
                continue
            parent_sid = str(entry.get("parent") or "").strip()
            child_sid = str(entry.get("child") or "").strip()
            if not child_sid or parent_sid not in tracked_parents:
                continue
            if child_sid not in tracked_parents:
                tracked_parents.add(child_sid)
                added = True
            worker_meta_by_id[child_sid] = entry
            if child_sid in ordered_worker_ids:
                ordered_worker_ids.remove(child_sid)
            ordered_worker_ids.append(child_sid)
        for child_sid, parent_sid in origin_parents.items():
            if parent_sid in tracked_parents and child_sid not in own_parent_ids:
                if child_sid not in tracked_parents:
                    tracked_parents.add(child_sid)
                    added = True
                if child_sid not in worker_meta_by_id:
                    worker_meta_by_id[child_sid] = {
                        "child": child_sid,
                        "parent": parent_sid,
                        "kind": "dispatch",
                    }
                    ordered_worker_ids.append(child_sid)
        if not added:
            break

    # 最新派出的排在最前
    ordered_worker_ids.reverse()

    live_drive_ids: set[str] = set()
    drive_dir = frago_home() / "drive"
    if drive_dir.is_dir():
        for sidecar in drive_dir.glob("*.json"):
            with contextlib.suppress(Exception):
                data = json.loads(sidecar.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("name"):
                    live_drive_ids.add(str(data["name"]).strip())

    workers: list[dict[str, Any]] = []
    for w_sid in ordered_worker_ids[: max(limit, 0)]:
        meta = worker_meta_by_id.get(w_sid) or {}
        session_dir = _locate_session_dir_by_id(sessions_root, w_sid)
        inspected: dict[str, Any] = {}
        if session_dir is not None:
            inspected = _inspect_session_dir(session_dir, w_sid)
        agent_type = str(meta.get("agent_type") or "").strip()
        if not agent_type and session_dir is not None:
            agent_type = session_dir.parent.name
        prompt_head = str(meta.get("prompt_head") or "").strip()
        title = (
            str(inspected.get("title") or "").strip()
            or _intent_from_prompt(prompt_head)
            or prompt_head[:80]
            or f"Worker {w_sid[:8]}"
        )
        conclusion = str(inspected.get("latest_conclusion") or "").strip()
        if conclusion == "（无首条消息摘要）":
            conclusion = ""
        ctx_tokens = int(inspected.get("context_tokens") or 0)
        ctx_window = int(inspected.get("context_window") or _DEFAULT_CONTEXT_WINDOW)
        if ctx_tokens <= 0:
            with contextlib.suppress(Exception):
                from frago.session import record_reader

                for urec in reversed(record_reader.read_records(w_sid, limit=120)):
                    if urec.kind == "usage.tick":
                        tok = urec.payload.get("context_tokens")
                        win = urec.payload.get("context_window")
                        if isinstance(tok, int | float) and tok > 0:
                            ctx_tokens = int(tok)
                            if isinstance(win, int | float) and win > 0:
                                ctx_window = int(win)
                            break
                    elif urec.kind == "agent.say" and not conclusion:
                        conclusion = " ".join(
                            str(urec.payload.get("text") or "").split()
                        )[:240]
        cap_state, cap_pct, cap_label = format_context_watermark(ctx_tokens, ctx_window)
        status = "running" if w_sid in live_drive_ids else "idle"
        workers.append(
            {
                "session_id": w_sid,
                "parent_session_id": str(meta.get("parent") or "").strip(),
                "agent_type": agent_type or "worker",
                "cwd": str(meta.get("cwd") or "").strip(),
                "status": status,
                "title": title,
                "first_prompt_summary": str(
                    inspected.get("first_prompt_summary") or prompt_head[:200]
                ).strip(),
                "latest_conclusion": conclusion,
                "last_activity": str(
                    inspected.get("last_activity") or inspected.get("started_at") or ""
                ).strip(),
                "context_tokens": ctx_tokens,
                "context_window": ctx_window,
                "context_pct": cap_pct,
                "context_state": cap_state,
                "context_watermark": cap_label,
            }
        )
    return workers


def _scan_sessions(
    keywords: set[str],
    cursor: LedgerCursor,
    *,
    limit: int = 200,
    record: EmployeePostRecord | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """扫会话目录，认领本岗绑定会话（`active_session_ids`）及与职责相关的会话。

    时间口径一律取 ``metadata.json`` 或记录自带的 ``started_at`` / ``last_activity``，NEVER 用
    目录 mtime：mtime 会被同步、备份、保活触碰改掉，按它判「有没有新会话」等于按文件的
    最后触碰时刻判内容，两边不是一回事。
    """
    sessions_root = frago_home() / "sessions"
    matched: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    watermark = ""
    if not sessions_root.is_dir():
        return matched, topics, watermark

    processed = set(cursor.processed_session_ids)
    seen_in_batch: set[str] = set()

    # 1. 优先认领本岗自己的 active_session_ids（含 agy / claude / codex / opencode / coreagent）
    if record is not None:
        for own_sid in reversed(record.active_session_ids):
            clean_sid = str(own_sid or "").strip()
            if not clean_sid or clean_sid in processed or clean_sid in seen_in_batch:
                continue
            own_dir = _locate_session_dir_by_id(sessions_root, clean_sid)
            if own_dir is None:
                continue
            info = _inspect_session_dir(own_dir, clean_sid)
            stamp = str(info.get("last_activity") or info.get("started_at") or "")
            if stamp and stamp > watermark:
                watermark = stamp
            processed.add(clean_sid)
            seen_in_batch.add(clean_sid)
            matched.append(
                {
                    "session_id": clean_sid,
                    "started_at": info["started_at"],
                    "last_activity": info["last_activity"],
                    "title": info["title"],
                    "first_prompt_summary": info["first_prompt_summary"],
                    "latest_conclusion": info["latest_conclusion"],
                    "bound_to_post": True,
                }
            )
            topics.append(
                {
                    "topic_key": f"session:{clean_sid}",
                    "title": info["title"],
                    "status": "active",
                    "latest_conclusion": info["latest_conclusion"],
                    "artifacts": [str(own_dir)],
                }
            )

    candidates: list[tuple[str, str, Path, dict[str, Any]]] = []

    for metadata_path in sessions_root.glob("*/*/metadata.json"):
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(raw, dict):
            continue
        session_id = str(raw.get("session_id", "") or "").strip()
        if not session_id or session_id in processed or session_id in seen_in_batch:
            continue
        started = str(raw.get("started_at", "") or "")
        last_activity = str(raw.get("last_activity", "") or "")
        stamp = last_activity or started
        # 严格早于水位线的会话上一轮已经考虑过了，只是没匹配上职责词。
        if cursor.sessions_through and stamp and stamp < cursor.sessions_through:
            continue
        name = str(raw.get("name", "") or "")
        if any(marker in name.lower() for marker in _LEDGER_SESSION_MARKERS):
            continue
        haystack = " ".join(
            [
                name,
                str(raw.get("project_path", "") or ""),
                str(raw.get("domain", "") or ""),
            ]
        )
        candidates.append(
            (session_id, stamp, metadata_path.parent, {**raw, "_haystack": haystack})
        )

    candidates.sort(key=lambda item: item[1], reverse=True)
    # 水位线取全体候选里最新的那个时刻，而不是「细读到哪」。取后者的话，被 limit 截掉的
    # 那一批比它更旧，下一轮会被水位线挡在外面，永远轮不到。
    if candidates:
        cand_max = max(stamp for _, stamp, _, _ in candidates)
        if cand_max > watermark:
            watermark = cand_max

    for session_id, _stamp, session_dir, raw in candidates[: max(limit, 0)]:
        info = _inspect_session_dir(session_dir, session_id, raw)
        first_prompt = info["first_prompt_summary"]
        haystack = f"{raw['_haystack']} {first_prompt}"
        processed.add(session_id)
        is_own = bool(
            record is not None
            and info.get("employee_id")
            and info.get("employee_id") == record.member_post_id
        )
        if not is_own and not _matches_scope(haystack, keywords):
            # 不匹配也记进已处理：不记的话下一轮还得把它读一遍，那场会话的开销白付了。
            continue
        title = info["title"]
        matched.append(
            {
                "session_id": session_id,
                "started_at": info["started_at"],
                "last_activity": info["last_activity"],
                "title": title,
                "first_prompt_summary": first_prompt,
                "latest_conclusion": info["latest_conclusion"],
                "bound_to_post": is_own,
            }
        )
        topics.append(
            {
                "topic_key": f"session:{session_id}",
                "title": title,
                "status": "active",
                "latest_conclusion": info["latest_conclusion"],
                "artifacts": [str(session_dir)],
            }
        )

    cursor.processed_session_ids = sorted(processed)
    return matched, topics, watermark


_LEDGER_SESSION_MARKERS: tuple[str, ...] = (
    "employee-ledger-sync",
    "员工账本巡检",
)


# --- 词汇表与意图剧本 ---


def _derive_glossary(
    claimed_recipes: list[dict[str, Any]],
    claimed_domains: list[dict[str, Any]],
    claimed_slots: list[dict[str, Any]],
    claimed_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """从认领到的资源里反推词汇表：用户嘴里的词 → 本机哪个东西。

    键取「人会说出口的那个词」，不是资源的机器名：

    - 配方有中文标题就用它（``波动率择时研究台（自适应窗口版）``），没写才退回配方名；
    - 数据主体目录取目录名（``stock``、``a_stock_dma``），那是用户和人对话时也在用的词；
    - 事务目录里的信号名、报告名是这一行真正的行话（``dma``、``波动率``），从目录名里
      切出来当词条，映射回那一件工作落在哪。

    只列机器名的话，这张表就是一份「本机有什么文件」的清单——员工读了它，还是不知道
    用户说「看下波动率那个」指的是哪个配方。
    """
    glossary: list[dict[str, Any]] = []

    for recipe in claimed_recipes:
        name = str(recipe.get("name", ""))
        if not name:
            continue
        display = str(recipe.get("display_title", "")).strip()
        description = str(recipe.get("description", ""))
        # 中文标题是用户说的那个词，配方名是它在这台机器上的标识，两条都列：
        # 前者让人一眼认出「哦是这个」，后者让员工知道该敲哪个命令。
        if display and display != name:
            glossary.append(
                {
                    "term": display,
                    "meaning": f"本机配方 {name}：{description}" if description else f"本机配方 {name}",
                    "mapped_targets": [f"recipe:{name}"],
                }
            )
        glossary.append(
            {
                "term": name,
                "meaning": description or f"本机配方 {name}",
                "mapped_targets": [f"recipe:{name}"],
            }
        )

    for domain in claimed_domains:
        name = str(domain.get("name", ""))
        if not name:
            continue
        glossary.append(
            {
                "term": name,
                "meaning": str(domain.get("purpose", "")) or f"知识域 {name}",
                "mapped_targets": [f"domain:{name}"],
            }
        )

    for slot in claimed_slots:
        name = str(slot.get("name", ""))
        if not name:
            continue
        glossary.append(
            {
                "term": name,
                "meaning": f"本机数据主体目录 {slot.get('path', '')}",
                "mapped_targets": [f"slot:{slot.get('path', '')}"],
            }
        )

    # 事务目录名里的行话：``20261102-min15-volatility-lab`` 里 ``min15``、
    # ``volatility``、``lab`` 是这一行的常用词，指向那一件具体的工作。
    for entry in claimed_entries:
        name = str(entry.get("name", ""))
        path = str(entry.get("path", ""))
        if not name or not path:
            continue
        slug = re.sub(r"^\d{8}-", "", name)
        for token in re.split(r"[-_]", slug):
            if len(token) < 3 or token.isdigit():
                continue
            glossary.append(
                {
                    "term": token,
                    "meaning": f"本岗位数据条目「{slug}」（{entry.get('summary', '') or '未写摘要'}）",
                    "mapped_targets": [f"data:{path}"],
                }
            )
    return glossary


def _recipe_trigger_words(claimed_recipes: list[dict[str, Any]]) -> list[str]:
    """从认领到的配方里提几个「代表词」，当意图剧本的触发词。

    这一段刻意不写死任何领域词：岗位千差万别，写死「回测 / 算信号」只有股票岗位
    对得上，换成文员、法务、设计，剧本里就挂着一串与本岗位无关的词。代表词只从
    这个岗位**自己认领到的**配方里长出来——账本里有的配方名，用户就有可能顺口
    叫出来，映射到的名字也都是真的。

    中文标题优先（``title.zh-CN``），没有就退回配方名里切出来的实词。名字里的
    版本号与 ``engine`` / ``feed`` 这类通用段先丢掉，它们出现在几乎每张配方名里，
    拿来当触发词等于没写。
    """
    words: list[str] = []
    for recipe in claimed_recipes:
        title = str(recipe.get("display_title", "") or "").strip()
        if title:
            # 标题里常带「A股全市场个股数据层（baostock…）」这样的括注与顿号，
            # 按分隔符拆开只留主体那几段，整串标题没人会照着一字不差地念。
            for chunk in re.split(r"[（(）)、,，/｜|·]", title):
                chunk = chunk.strip()
                if 2 <= len(chunk) <= 12:
                    words.append(chunk)
        name = str(recipe.get("name", "") or "")
        for segment in name.split("_"):
            segment = segment.strip()
            if len(segment) >= 3 and not segment.isdigit():
                if segment.lower() in _RECIPE_NAME_NOISE:
                    continue
                words.append(segment)
    seen: set[str] = set()
    unique: list[str] = []
    for word in words:
        if word not in seen:
            seen.add(word)
            unique.append(word)
    return unique


def _derive_intent_playbooks(
    record: EmployeePostRecord,
    claimed_recipes: list[dict[str, Any]],
    claimed_slots: list[dict[str, Any]],
    claimed_domains: Sequence[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    """从岗位职责与认领到的工具链里，推出「哪句话通常对应哪套动作」。

    只建三类最通用的：一类是「看现状/复盘」，指向本岗位的数据底账；一类是
    「执行本岗位配方与自动化工具」，指向本岗位的配方；一类是「查本岗位既有结论」，
    指向本岗位的知识域。这三类是任何岗位都有的，编得出来也核得实——映射到的名字
    都是真的，说法里一个领域词都不写死。
    """
    playbooks: list[dict[str, Any]] = []
    slot_paths = [str(s.get("path", "")) for s in claimed_slots if s.get("path")]
    recipe_names = [str(r.get("name", "")) for r in claimed_recipes if r.get("name")]
    domain_names = {
        str(d).strip() for d in record.knowledge_domains if str(d).strip()
    } | {
        str(d.get("name", "")).strip()
        for d in claimed_domains
        if isinstance(d, dict) and str(d.get("name", "")).strip()
    }

    if record.member_post_id == "recipe-builder" or "frago-recipe-ops" in domain_names:
        playbooks.append(
            {
                "intent": "新建或迭代本机配方（需求拆解 → 规格定义 → 模板实现 → 契约校验 → 本机运行交付）",
                "trigger_phrases": [
                    "做个配方",
                    "新建配方",
                    "写个配方",
                    "创建配方",
                    "配方工作台",
                    "迭代配方",
                    "修改配方",
                ],
                "default_action": (
                    "将权威规范章节（`frago book recipe-spec-writing`、`frago book recipe-creation`、"
                    "`frago book interactive-recipe`、`frago book must-recipe-data`）与 `frago-recipe-ops` 知识域写入任务书，"
                    "交由 Worker 按标准四步推进（`plan` 写 `spec.md` → `create` 生成模板并填实现 → `validate` 过检 → `run`/`open` 本机验证）。"
                    "【本机生效 vs 服务器开放硬边界】本机（`local` 区）配方落盘即自动被服务识别生效、主人免权限直通；"
                    "有界面的配方只需将 `default_mode` 设为打开页面的 mode（调 `self.publish` + `self.open_page`）或执行 `frago recipe open <名字>` 即可使用；"
                    "严禁为让本机配方生效而执行 `frago recipe expose` 或调 `frago app ask` 询问开放权限（`expose` 仅在用户明确要求向远端/多账号服务器外部他人开放页面时使用）。"
                ),
                "recipes_or_slots": [
                    "book:recipe-spec-writing",
                    "book:recipe-creation",
                    "book:interactive-recipe",
                    "book:must-recipe-data",
                    "domain:frago-recipe-ops",
                ],
            }
        )

    if slot_paths:
        playbooks.append(
            {
                "intent": "看现状 / 复盘 / 拆解当前情况",
                "trigger_phrases": ["现在什么情况", "复盘", "看一下", "进展", "拆解"],
                "default_action": (
                    "结合已挂载的近期活跃事项与槽位目录摘要，将相关数据槽位路径、知识域方向及核查准则写进任务书，"
                    "塞进对口的已有 Worker 会话（`frago agent --resume <session_id> --prompt-file <任务书.md>`）"
                    "或新开 Worker 会话（`frago agent --prompt-file <任务书.md>`）去读取核实并代审，拿回结论后在本会话向人类汇报并给出决策建议。"
                ),
                "recipes_or_slots": slot_paths,
            }
        )
    if recipe_names:
        triggers = list(_GENERIC_RECIPE_TRIGGERS)
        for word in _recipe_trigger_words(claimed_recipes):
            if word not in triggers:
                triggers.append(word)
        playbooks.append(
            {
                "intent": "调度本岗位配方与自动化工具",
                "trigger_phrases": triggers[:12],
                "default_action": (
                    "将候选配方名、相关数据槽位路径与执行准则作为参考方向编入任务书，交由已有或新开的 Worker 会话"
                    "（`frago agent --resume <session_id> --prompt-file <任务书.md>` 或 `frago agent --prompt-file <任务书.md>`）"
                    "去执行 `frago recipe info <名字>` 与 `frago recipe run <名字> --params '<JSON>'`，回收审核结果后在本会话向人类交付结论。"
                ),
                "recipes_or_slots": recipe_names,
            }
        )
    if domain_names:
        playbooks.append(
            {
                "intent": "调取本岗位既有结论与领域准则",
                "trigger_phrases": ["以前怎么定的", "有没有沉淀", "查一下知识", "之前遇到过吗"],
                "default_action": (
                    "绝不自己在主会话盲搜细节，将候选知识域名与关联历史会话 ID 作为参考方向写入任务书交给 Worker "
                    "执行 `frago <domain> find` / `frago session ask` 取证与核验，再基于 Worker 交回的结论在本会话向人类输出决策建议。"
                ),
                "recipes_or_slots": [f"domain:{d}" for d in sorted(domain_names)],
            }
        )
    return playbooks


# --- 巡检入口 ---


def sync_employee_ledger(
    member_post_id: str,
    *,
    base_dir: Path | None = None,
    full_rescan: bool = False,
    session_limit: int = 200,
) -> dict[str, Any]:
    """对一个员工执行一次主动资源巡检，增量入账并落盘账本。

    ``full_rescan=True`` 丢掉游标重扫一遍（用于改过岗位职责、想重新认领的场合）。
    默认走增量：指纹没变的资源直接跳过。

    重扫丢掉的是**游标**，不是**排除名单**。名单是人逐条剔除出来的判断，巡检这一侧产不出
    「人改主意了」这个信号；全量重扫若把它一起丢掉，人上次删掉的那几项会当场回来，页面上的
    「重新巡检」就成了「撤销我上次的调整」。
    """
    record = get_post(member_post_id, base_dir=base_dir)
    if record is None:
        raise KeyError(f"Employee post '{member_post_id}' does not exist.")

    # 磁盘上那一份账本要读一次、用两处：增量时它就是合并的底本；全量重扫时它的认领结果
    # 弃用，只把排除名单接过来。
    existing_ledger = load_ledger(member_post_id, base_dir=base_dir)
    prior = existing_ledger
    if full_rescan:
        old_ledger = EmployeeLedger(
            member_post_id=record.member_post_id,
            excluded_resources=(
                dict(existing_ledger.excluded_resources) if existing_ledger else {}
            ),
        )
        cursor = LedgerCursor()
    else:
        old_ledger = existing_ledger
        cursor = existing_ledger.cursor if existing_ledger is not None else LedgerCursor()

    keywords = extract_scope_keywords(record)

    # 知识域排在数据目录前面，因为它多带一层证据：一个域被认领后，它用途栏里那句
    # 自述也算这个岗位的职责证据。个人助理的职责词只有「家庭」，而本机 ``health-report-reading``
    # 里全是「体检」「就医」——那正是它认领到的 ``family-health`` 在管的主题。不接这一跳，
    # 这类目录永远漏在外面。
    #
    # 这一层只喂给数据目录扫描，不外溢到配方与会话：配方名、会话标题的匹配面本来就宽，
    # 再叠一层间接词，误伤会比多认领到的那点收益更贵。
    domains, domain_topics, domain_digests = _scan_domains(
        keywords, cursor, excluded=prior, record=record
    )
    claimed_domain_names = {
        str(d.get("name", "")).strip().lower()
        for d in domains
        if isinstance(d, dict) and str(d.get("name", "")).strip()
    } | {str(d).strip().lower() for d in record.knowledge_domains if str(d).strip()}
    slot_keywords = keywords | _domain_evidence_keywords(domains) | claimed_domain_names

    slots, slot_entries, slot_topics, data_digests = _scan_data_slots(
        record, slot_keywords, cursor, excluded=prior
    )
    recipes, recipe_topics, recipe_digests = _scan_recipes(
        keywords, cursor, excluded=prior, record=record
    )
    sessions, session_topics, latest_session = _scan_sessions(
        keywords, cursor, limit=session_limit, record=record
    )

    delta = EmployeeLedger(
        member_post_id=record.member_post_id,
        work_scope_anchor=record.work_scope or record.description,
        cursor=LedgerCursor(
            sessions_through=latest_session or cursor.sessions_through,
            processed_session_ids=list(cursor.processed_session_ids),
            processed_data_entries=dict(data_digests),
            recipe_digests=dict(recipe_digests),
            domain_digests=dict(domain_digests),
        ),
        claimed_resources={
            "data_slots": slots,
            "data_incremental_entries": slot_entries,
            "recipes": recipes,
            "knowledge_domains": domains,
            "matched_sessions": sessions,
        },
        glossary=_derive_glossary(recipes, domains, slots, slot_entries),
        intent_playbooks=_derive_intent_playbooks(record, recipes, slots, domains),
        active_topics=[*slot_topics, *recipe_topics, *domain_topics, *session_topics],
    )

    merged, counts = merge_ledger_entries(
        old_ledger, delta, member_post_id=record.member_post_id
    )
    path = save_ledger(merged, base_dir=base_dir)

    # 主动认领的结果反哺回岗位编制：下次起会话时岗位本身就知道自己管着哪些槽位/配方/
    # 知识域，不必先读一遍账本才知道。去重保序，已有的一律不动。
    _feed_back_territory(record, slots, recipes, domains, base_dir=base_dir, excluded=prior)

    return {
        "member_post_id": record.member_post_id,
        "ledger_path": str(path),
        "work_scope_anchor": merged.work_scope_anchor,
        "scope_keywords": sorted(keywords),
        "counts": counts,
        "new_data_entries": len(slot_entries),
        "new_recipes": len(recipes),
        "new_domains": len(domains),
        "new_sessions": len(sessions),
        "cursor": {
            "sessions_through": merged.cursor.sessions_through,
            "processed_session_count": len(merged.cursor.processed_session_ids),
            "processed_data_entry_count": len(merged.cursor.processed_data_entries),
            "recipe_digest_count": len(merged.cursor.recipe_digests),
            "domain_digest_count": len(merged.cursor.domain_digests),
        },
        "totals": {
            "glossary": len(merged.glossary),
            "intent_playbooks": len(merged.intent_playbooks),
            "active_topics": len(merged.active_topics),
            "claimed_slots": len(merged.claimed_resources["data_slots"]),
            "claimed_recipes": len(merged.claimed_resources["recipes"]),
            "claimed_domains": len(merged.claimed_resources["knowledge_domains"]),
            "matched_sessions": len(merged.claimed_resources["matched_sessions"]),
        },
    }


def _feed_back_territory(
    record: EmployeePostRecord,
    slots: Sequence[dict[str, Any]],
    recipes: Sequence[dict[str, Any]],
    domains: Sequence[dict[str, Any]],
    *,
    base_dir: Path | None,
    excluded: EmployeeLedger | None = None,
) -> None:
    """把本轮新认领的槽位/配方/知识域写回岗位编制，去重保序。

    槽位写成 ``~/`` 相对形式：岗位编制里人写的是 ``~/.frago/data/stock``，巡检发现的是
    ``/Users/<人>/.frago/data/stock``，两者指向同一处而字面不同。照绝对路径写回去，同一
    个槽位会以两种写法各占一行，之后每读一次岗位都要人去判断它们是不是一回事。

    人否决过的（``excluded``）不写回去。写回去就等于「删了又长出来」：账本那一侧已经
    跳过它们，编制这一侧若照旧写入，下一次起会话仍然带着它。

    判重先归一化再比。编制里可能写着绝对路径（人从页面上复制来的、或早期版本写进去的），
    巡检手上的是 ``~/`` 形式，两种写法指向同一处而字面不同；直接按字面比，同一个目录会以
    两种写法各占一行，之后每读一次岗位都要人去判断它们是不是一回事。归一化只用于比较，
    编制里原有的写法一个都不改写。
    """
    new_slots: list[str] = []
    for slot in slots:
        path = str(slot.get("path", ""))
        if not path or slot.get("bound"):
            continue
        canonical = _with_tilde(path)
        if is_resource_excluded(excluded, "data_slots", canonical) or is_resource_excluded(
            excluded, "data_slots", path
        ):
            continue
        new_slots.append(canonical)
    new_recipes = [
        str(r.get("name", ""))
        for r in recipes
        if r.get("name") and not is_resource_excluded(excluded, "recipes", str(r.get("name", "")))
    ]
    new_domains = [
        str(d.get("name", ""))
        for d in domains
        if d.get("name")
        and not is_resource_excluded(
            excluded, "knowledge_domains", str(d.get("name", ""))
        )
    ]

    changed = False
    for target, additions, normalize in (
        (record.data_slots, new_slots, _with_tilde),
        (record.recipes, new_recipes, None),
        (record.knowledge_domains, new_domains, None),
    ):
        # 编制里已有的写法一并归一化后参与比较：槽位在编制里可能写成绝对路径，巡检给出的是
        # ``~/`` 形式，按字面比会把同一处目录判成两个，于是同一行在编制里出现两遍。
        seen = {normalize(str(x)) if normalize else str(x) for x in target if str(x).strip()}
        for item in additions:
            if not item:
                continue
            key = normalize(item) if normalize else item
            if key in seen:
                continue
            seen.add(key)
            target.append(item)
            changed = True
    if changed:
        record.__post_init__()
        save_post(record, base_dir=base_dir)


# --- 定时排程 ---

#: 每天一次，避开整点：整点是所有定时任务挤在一起的时候，巡检又要扫一万多个会话目录。
LEDGER_SYNC_CRON = "17 8 * * *"


def ensure_employee_ledger_schedule(
    member_post_id: str,
    *,
    base_dir: Path | None = None,
    add_schedule: Callable[..., dict[str, Any]] | None = None,
    list_schedules: Callable[[], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """确保这台机器上有一条每天执行的员工账本巡检任务。

    排程不自己写 ``schedules.json``，走的是服务端 ``SchedulerService`` 的 ``add_schedule``
    （由调用方注入）：那份文件有它自己的字段约定与调度器每一轮的重读逻辑，两边各写一份
    迟早对不上账。命令行与接口层负责把调度器接进来。

    已经有同名任务时什么都不做，把已有的那条 ID 还回去——重复建排程会让同一件事一天
    跑好几遍。
    """
    post_id = str(member_post_id).strip()
    schedule_name = f"员工账本巡检:{post_id}"
    schedule_id = f"daily-{post_id}-ledger-sync"

    if list_schedules is not None:
        for existing in list_schedules():
            if existing.get("name") == schedule_name or existing.get("id") == schedule_id:
                _record_schedule_id(post_id, str(existing.get("id", "")), base_dir=base_dir)
                return {
                    "schedule_id": existing.get("id"),
                    "created": False,
                    "name": schedule_name,
                    "cron": existing.get("cron"),
                }

    if add_schedule is None:
        return {
            "schedule_id": None,
            "created": False,
            "name": schedule_name,
            "cron": LEDGER_SYNC_CRON,
            "reason": "调度器未接入：命令行与接口层负责注入 SchedulerService.add_schedule。",
        }

    created = add_schedule(
        name=schedule_name,
        cron=LEDGER_SYNC_CRON,
        command=f"frago employee sync-ledger {post_id}",
        cwd=str(Path.home()),
        notify={"on": "never", "to": None, "context": {}},
    )
    _record_schedule_id(post_id, str(created.get("id", "")), base_dir=base_dir)
    return {
        "schedule_id": created.get("id"),
        "created": True,
        "name": schedule_name,
        "cron": LEDGER_SYNC_CRON,
    }


def _record_schedule_id(
    member_post_id: str,
    schedule_id: str,
    *,
    base_dir: Path | None,
) -> None:
    if not schedule_id:
        return
    record = get_post(member_post_id, base_dir=base_dir)
    if record is None or schedule_id in record.schedule_ids:
        return
    record.schedule_ids.append(schedule_id)
    record.__post_init__()
    save_post(record, base_dir=base_dir)


def remove_employee_ledger_schedule(
    member_post_id: str,
    *,
    schedule_ids: Sequence[str] = (),
    remove_schedule: Callable[[str], bool] | None = None,
    list_schedules: Callable[[], list[dict[str, Any]]] | None = None,
) -> list[str]:
    """移除该员工关联的每日账本巡检排程，返回实际删掉的排程编号列表。

    同时按两条线索找：岗位编制 ``schedule_ids`` 里记下的编号，以及调度器里按命名约定
    （``员工账本巡检:<post_id>`` / ``daily-<post_id>-ledger-sync`` / 命令 ``frago employee sync-ledger <post_id>``）
    能对上的任务——即使岗位文件先一步删了，也能把孤儿巡检排程清干净。
    """
    if remove_schedule is None:
        return []
    post_id = str(member_post_id).strip()
    schedule_name = f"员工账本巡检:{post_id}"
    default_id = f"daily-{post_id}-ledger-sync"
    sync_cmd = f"frago employee sync-ledger {post_id}"

    candidates: list[str] = [
        str(sid).strip() for sid in schedule_ids if str(sid).strip()
    ]
    if list_schedules is not None:
        for existing in list_schedules():
            sid = str(existing.get("id", "")).strip()
            if not sid or sid in candidates:
                continue
            if (
                existing.get("name") == schedule_name
                or sid == default_id
                or str(existing.get("command", "")).strip() == sync_cmd
            ):
                candidates.append(sid)

    removed_ids: list[str] = []
    for sid in candidates:
        if remove_schedule(sid):
            removed_ids.append(sid)
    return removed_ids


def ledger_is_excluded(path: Path) -> bool:
    """巡检扫描时是否要跳过这个路径。防自指的第二道判据（第一道是账本不在 data 下）。"""
    return is_employee_ledger_path(path)


__all__ = [
    "LEDGER_SYNC_CRON",
    "ensure_employee_ledger_schedule",
    "extract_scope_keywords",
    "ledger_is_excluded",
    "remove_employee_ledger_schedule",
    "resolve_employee_recent_sessions",
    "resolve_employee_worker_sessions",
    "sync_employee_ledger",
]
