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

import json
import re
from collections.abc import Callable, Sequence
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
    }
)

#: 中文职责词按长度倒序切：先认「波动率」再认「波动」，短词套长词会把词根切碎。
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
    """从中文串里取「以标点或换行分隔的整段」，不做内部切分。

    试过按 2–4 字滑窗切词根，实机结果是切出来的碎片跨词边界：岗位描述里
    「……把归因结论与失效边界一起写下」切出 ``结论与``、``的数据``、``工具链``，
    拿这些当认领判据，``~/.frago/books/due-diligence`` 会因为用途里写着「风险结论与
    报告产出位置」而被认领，``svc-audio`` 因为写着「工具链知识」而被认领。切得越碎，
    命中越随机。

    只取整段：本机资源的名字几乎全是 ASCII（``stock``、``etf``、``a_stock_dma``、
    ``a_stock_dma_signal_engine``），真正的认领主力是 ASCII 词根。中文整段只在
    资源名本身是中文时才用得上，所以它只做兜底，不再切碎。
    """
    words: set[str] = set()
    for run in _CJK_RUN.finditer(text):
        chunk = run.group(0)
        if 3 <= len(chunk) <= 12:
            words.add(chunk)
    return words


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
    return {t for t in tokens if t not in _STOPWORDS and len(t) >= 3}


def _matches_scope(name: str, keywords: set[str]) -> bool:
    """资源名是否与职责范围相关。

    ASCII 词根按「词根是名字的一部分」判（``stock`` 命中 ``a_stock_dma``）。

    中文按「谁含谁」双向判：资源名可能是中文（``~/.frago/data/双色球``），而关键词是
    一段整句（``负责双色球走势分析``），单向的「关键词是名字的子串」永远不成立。
    中文名本身很短、领域性强，双向包含不会像碎片滑窗那样随机命中。
    """
    lowered = name.lower()
    if not lowered:
        return False
    for keyword in keywords:
        if keyword in lowered:
            return True
        if _CJK_RUN.fullmatch(keyword) and len(lowered) >= 2 and lowered in keyword:
            return True
    return False


def _read_text_head(path: Path, limit: int = 4096) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def _entry_summary(directory: Path) -> str:
    """一个事务目录的业务摘要。

    先找 ``notebook.md`` / ``README.md``；都没有时，退回从目录里的文件名与首个
    ``.md`` 标题里提炼。``~/.frago/data/stock/`` 下大部分事务目录根本没有
    ``notebook.md``，只认它的话摘要会全是空的——账本记了 15 个目录，一个都说不出
    是干什么的，等于没记。

    标题下的第一行正文优先于标题本身：``# 回测报告`` 说的是「这是什么」，紧跟的
    ``口径与复核步骤，结论：信号在震荡市失效`` 说的才是「现在到哪了」。账本里的
    事项结论要跟着工作推进走，取标题的话，正文改了结论也不会变，那这一栏就成了摆设。
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
    # 没有 markdown 时用文件名凑一句：``20260818-dma-daily-buy-signals`` 里放着
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


def _scan_data_slots(
    record: EmployeePostRecord,
    keywords: set[str],
    cursor: LedgerCursor,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """扫 ``~/.frago/data/`` 下与职责相关的主体目录及其事务目录。

    返回 ``(认领的槽位, 新增/变化的事务条目, 活跃事项, 本轮指纹)``。

    主体目录的认领不只看岗位已绑定的 ``data_slots``：岗位描述里写着「股票与 ETF 投研」，
    而 ``data_slots`` 是空的（新建岗位的常态），这时按职责词主动去找 ``data/stock``、
    ``data/a_stock_dma``、``data/etf`` 才是「主动资源查找」本身。
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
        is_bound = resolved in bound
        if not is_bound and not _matches_scope(subject.name, keywords):
            continue
        claimed_slots.append(
            {
                "path": str(subject),
                "name": subject.name,
                "bound": is_bound,
                "discovered_by": "bound" if is_bound else "scope_keywords",
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

    #: 配方在磁盘上的目录约定与配方系统自己的注册表一致（``frago.recipes.registry``）：
    #: 顶层三个子目录各放一层，``workflows/<配方>/recipe.md`` 是两层，而
    #: ``atomic/chrome/<配方>/recipe.md`` 与 ``atomic/system/<配方>/recipe.md`` 是三层。
    #: 只 glob ``*/*/recipe.md`` 会把 atomic 下的配方整类漏掉——漏得没有声音，账本里
    #: 本岗位真在用的工具就这么少了一批。这里按约定逐个扫，同时保留原来那条通配，
    #: 免得约定之外的目录布局（用户自己放在顶层别的目录下）反而被新写法丢掉。
    candidates: set[Path] = set(recipes_root.glob("*/*/recipe.md"))
    for subdir in _RECIPE_SUBDIRS:
        candidates.update((recipes_root / subdir).glob("*/recipe.md"))

    for metadata_path in sorted(candidates):
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
                # 只看顶层键（缩进为 0）。配方文件里 ``description:`` 出现很多次——顶层一次，
                # 底下每个 mode 与参数各一次。逐行扫而不判缩进，最后读到的是某个参数的说明，
                # 账本里那条配方的「是什么意思」就变成了一句 ``mode=detail 用，stock | etf``。
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
        blob = " ".join([name, description, *tags])
        if not _matches_scope(blob, keywords):
            continue
        digest = digest_text(blob)
        if cursor.recipe_digests.get(name) == digest:
            continue
        digests[name] = digest
        claimed.append(
            {
                "name": name,
                "type": recipe_type,
                "description": description,
                "display_title": display_title,
                "tags": tags,
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """扫 ``~/.frago/books/`` 下的知识域，认领与职责相关的那些。

    指纹取「文档数 + 最近更新的那篇」的组合：知识域是持续往里加条目的，条数变了说明
    有新内容；条数没变但最近那篇换人了，说明有人在修订，两种都值得重记一次。
    """
    books_root = frago_home() / "books"
    claimed: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    digests: dict[str, str] = {}
    if not books_root.is_dir():
        return claimed, topics, digests

    registry_purposes: dict[str, str] = {}
    registry_path = books_root / "registry.json"
    if registry_path.is_file():
        try:
            raw = json.loads(registry_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                registry_purposes = {
                    str(k): str((v or {}).get("purpose", ""))
                    for k, v in raw.items()
                    if isinstance(v, dict)
                }
        except (json.JSONDecodeError, OSError):
            registry_purposes = {}

    try:
        domains = sorted(p for p in books_root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return claimed, topics, digests

    for domain in domains:
        purpose = registry_purposes.get(domain.name, "")
        if not _matches_scope(f"{domain.name} {purpose}", keywords):
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


def _session_first_prompt(session_dir: Path) -> str:
    """会话的第一条用户消息，一行。

    读 ``steps.jsonl`` 的第一条 ``type=user`` 记录。整个文件可能几十兆，但只需要开头：
    第一句话就在最前面，把整份记录读进内存去取它没有意义。
    """
    steps_path = session_dir / "steps.jsonl"
    if not steps_path.is_file():
        return ""
    try:
        with steps_path.open("r", encoding="utf-8", errors="replace") as handle:
            for _ in range(50):
                line = handle.readline()
                if not line:
                    break
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") != "user":
                    continue
                text = str(record.get("content_summary", "") or "").strip()
                if text:
                    return " ".join(text.split())[:400]
    except OSError:
        return ""
    return ""


def _session_title(raw: dict[str, Any], first_prompt: str, session_id: str) -> str:
    """一场会话在账本里叫什么。

    ``metadata.json`` 的 ``name`` 优先，但只有它是「人给这场所起的名」时才算数。派活型的
    会话里那一栏常常是投给 agent 的系统提示词原文（``你是 frago recipe 开发专家。任务：
    根据 spec 创建 recipe……``），把它当标题，账本里就会出现一串一模一样的「你是……专家」，
    读的人分不清哪场是哪场。

    ``first_prompt`` 也过同一道筛：派活型会话的第一条消息就是那段任务书本身，直接拿它
    顶替，标题里那串「你是……专家」原样还在。
    """
    name = str(raw.get("name", "") or "").strip()
    if name and name != "-" and not _looks_like_system_prompt(name):
        return name
    prompt = first_prompt.strip()
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
    if stripped.startswith(("你是", "You are", "你是一位")):
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


def _scan_sessions(
    keywords: set[str],
    cursor: LedgerCursor,
    *,
    limit: int = 200,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """扫会话目录，认领与职责相关的会话。

    时间口径一律取 ``metadata.json`` 里的 ``started_at`` / ``last_activity``，NEVER 用
    目录 mtime：mtime 会被同步、备份、保活触碰改掉，按它判「有没有新会话」等于按文件的
    最后触碰时刻判内容，两边不是一回事。

    ``limit`` 封顶本轮**逐场细读**的会话数，按时间倒序取最新的那批。一台机器上有一万多场
    会话，逐场读首条消息是一笔真开销，而账本要的是「近期在跟哪几件事」，不是一份全量
    会话清单。细读之外的那些由 ``sessions_through`` 水位线代表：「这个时刻之前都已考虑
    过」。水位线一立，下一轮就只剩新增的几场是候选，巡检从「扫一万场」变成「看几场」。
    """
    sessions_root = frago_home() / "sessions"
    matched: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    watermark = ""
    if not sessions_root.is_dir():
        return matched, topics, watermark

    processed = set(cursor.processed_session_ids)
    candidates: list[tuple[str, str, Path, dict[str, Any]]] = []

    for metadata_path in sessions_root.glob("*/*/metadata.json"):
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(raw, dict):
            continue
        session_id = str(raw.get("session_id", "") or "").strip()
        if not session_id or session_id in processed:
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
        watermark = max(stamp for _, stamp, _, _ in candidates)

    for session_id, _stamp, session_dir, raw in candidates[: max(limit, 0)]:
        first_prompt = _session_first_prompt(session_dir)
        haystack = f"{raw['_haystack']} {first_prompt}"
        processed.add(session_id)
        if not _matches_scope(haystack, keywords):
            # 不匹配也记进已处理：不记的话下一轮还得把它读一遍，那场会话的开销白付了。
            continue
        title = _session_title(raw, first_prompt, session_id)
        matched.append(
            {
                "session_id": session_id,
                "started_at": str(raw.get("started_at", "") or ""),
                "last_activity": str(raw.get("last_activity", "") or ""),
                "title": title,
                "first_prompt_summary": first_prompt[:200],
            }
        )
        topics.append(
            {
                "topic_key": f"session:{session_id}",
                "title": title,
                "status": "active",
                "latest_conclusion": first_prompt[:200] or "（无首条消息摘要）",
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

    if slot_paths:
        playbooks.append(
            {
                "intent": "看现状 / 复盘 / 拆解当前情况",
                "trigger_phrases": ["现在什么情况", "复盘", "看一下", "进展", "拆解"],
                "default_action": "先读本岗位数据底账里最近的事务目录，再回答；结论要能指回具体文件。",
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
                "intent": "执行本岗位配方与自动化工具",
                "trigger_phrases": triggers[:12],
                "default_action": "先 `frago recipe info <名字>` 看清参数，再 `frago recipe run`；不要另写脚本重造。",
                "recipes_or_slots": recipe_names,
            }
        )
    if record.knowledge_domains:
        playbooks.append(
            {
                "intent": "查本岗位既有结论",
                "trigger_phrases": ["以前怎么定的", "有没有沉淀", "查一下知识", "之前遇到过吗"],
                "default_action": "先 `frago <domain> find` 取结论，再决定要不要重新推导。",
                "recipes_or_slots": [f"domain:{d}" for d in record.knowledge_domains],
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
    """
    record = get_post(member_post_id, base_dir=base_dir)
    if record is None:
        raise KeyError(f"Employee post '{member_post_id}' does not exist.")

    old_ledger = None if full_rescan else load_ledger(member_post_id, base_dir=base_dir)
    cursor = old_ledger.cursor if old_ledger is not None else LedgerCursor()

    keywords = extract_scope_keywords(record)

    slots, slot_entries, slot_topics, data_digests = _scan_data_slots(record, keywords, cursor)
    recipes, recipe_topics, recipe_digests = _scan_recipes(keywords, cursor)
    domains, domain_topics, domain_digests = _scan_domains(keywords, cursor)
    sessions, session_topics, latest_session = _scan_sessions(
        keywords, cursor, limit=session_limit
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
        intent_playbooks=_derive_intent_playbooks(record, recipes, slots),
        active_topics=[*slot_topics, *recipe_topics, *domain_topics, *session_topics],
    )

    merged, counts = merge_ledger_entries(
        old_ledger, delta, member_post_id=record.member_post_id
    )
    path = save_ledger(merged, base_dir=base_dir)

    # 主动认领的结果反哺回岗位编制：下次起会话时岗位本身就知道自己管着哪些槽位/配方/
    # 知识域，不必先读一遍账本才知道。去重保序，已有的一律不动。
    _feed_back_territory(record, slots, recipes, domains, base_dir=base_dir)

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
) -> None:
    """把本轮新认领的槽位/配方/知识域写回岗位编制，去重保序。

    槽位写成 ``~/`` 相对形式：岗位编制里人写的是 ``~/.frago/data/stock``，巡检发现的是
    ``/Users/<人>/.frago/data/stock``，两者指向同一处而字面不同。照绝对路径写回去，同一
    个槽位会以两种写法各占一行，之后每读一次岗位都要人去判断它们是不是一回事。
    """
    home = str(Path.home())
    new_slots: list[str] = []
    for slot in slots:
        path = str(slot.get("path", ""))
        if not path or slot.get("bound"):
            continue
        new_slots.append(f"~{path[len(home):]}" if path.startswith(home) else path)
    new_recipes = [str(r.get("name", "")) for r in recipes if r.get("name")]
    new_domains = [str(d.get("name", "")) for d in domains if d.get("name")]

    changed = False
    for target, additions in (
        (record.data_slots, new_slots),
        (record.recipes, new_recipes),
        (record.knowledge_domains, new_domains),
    ):
        for item in additions:
            if item and item not in target:
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


def ledger_is_excluded(path: Path) -> bool:
    """巡检扫描时是否要跳过这个路径。防自指的第二道判据（第一道是账本不在 data 下）。"""
    return is_employee_ledger_path(path)


__all__ = [
    "LEDGER_SYNC_CRON",
    "ensure_employee_ledger_schedule",
    "extract_scope_keywords",
    "ledger_is_excluded",
    "sync_employee_ledger",
]
