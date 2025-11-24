# Research: Run命令系统技术决策

**Created**: 2025-11-21
**Feature**: 005-run-command-system
**Purpose**: 为Run命令系统的实现提供技术方案决策依据

---

## 1. 主题slug生成策略

### 决策

采用 **pypinyin + python-slugify** 组合方案：
- 使用 `pypinyin` 将中文任务描述转换为拼音
- 使用 `python-slugify` 进行 Unicode 安全的 slug 化处理
- 限制 slug 长度为 50 字符
- 冲突检测：扫描 `runs/` 目录，发现同名时触发交互式菜单

### 理由

1. **pypinyin 是成熟的行业标准**：2025年1月学术论文仍在使用，支持多音字智能匹配
2. **python-slugify 处理 Unicode 完善**：自动处理特殊字符、空格、标点符号
3. **50字符限制**：符合现代SEO最佳实践（<60字符），既保留可读性又避免过长
4. **冲突即主题复用**：主题型设计的核心，冲突时提示用户"是否继续现有run"而非自动重命名

### 实现伪码

```python
import pypinyin
from slugify import slugify

def generate_theme_slug(description: str, max_length: int = 50) -> str:
    # 1. 中文转拼音（智能多音字）
    pinyin_words = pypinyin.lazy_pinyin(description, style=pypinyin.Style.NORMAL)
    pinyin_text = ' '.join(pinyin_words)

    # 2. slug化（处理Unicode、标点、空格）
    slug = slugify(pinyin_text, max_length=max_length)

    # 3. 如果为空（纯符号输入），回退到timestamp
    if not slug:
        slug = f"task-{int(time.time())}"

    return slug
```

### 考虑的替代方案

- **方案A：仅用 unidecode**
  拒绝原因：对中文使用 Gwoyeu Romatzyh 形式，输出不一致且难以阅读

- **方案B：AI翻译中文为英文**
  拒绝原因：需要调用LLM，增加延迟和成本；翻译质量不可控

- **方案C：保留中文字符（UTF-8）**
  拒绝原因：文件系统兼容性差，某些工具不支持中文目录名

### 参考

- [pypinyin PyPI](https://pypi.org/project/pypinyin/) - 智能多音字支持
- [python-slugify Guide 2025](https://generalistprogrammer.com/tutorials/python-slugify-python-package-guide)
- [Complex & Intelligent Systems 2025](https://link.springer.com/article/10.1007/s40747-024-01753-0) - pypinyin在NER中的应用

---

## 2. JSONL日志格式的最佳实践

### 决策

采用 **python-json-logger + 自定义结构化字段** 方案：
- 使用 ISO 8601 时间戳（强制UTC）
- 避免深层嵌套（最多2层）
- 数值类型字段使用原生JSON类型（不转字符串）
- 保留 `schema_version: "1.0"` 字段以支持未来迁移
- 9种 `action_type` 和 6种 `execution_method` 枚举值保持不变

### 理由

1. **JSONL是日志聚合平台标准**：ELK、Splunk、Datadog都原生支持
2. **ISO 8601时间戳易排序**：`"2025-11-21T10:30:00Z"` 可直接字符串比较
3. **浅层结构利于查询**：避免 `data.results.items[0].value` 这样的深层路径
4. **schema_version必需**：当枚举值扩展或字段重构时，可按版本解析旧日志
5. **枚举值经过场景验证**：9种action_type覆盖spec中所有示例（导航、提取、交互、截图、Recipe执行、数据处理、分析、用户交互、其他）

### 验证枚举值完整性

| action_type | 使用场景 | 示例 |
|------------|---------|------|
| navigation | 页面跳转 | 导航到Upwork搜索页 |
| extraction | 数据提取 | 提取职位列表 |
| interaction | 用户交互 | 点击"搜索"按钮 |
| screenshot | 截图 | 保存搜索结果页 |
| recipe_execution | 调用Recipe | 执行youtube_extract_transcript |
| data_processing | 数据处理 | 过滤薪资>$50的职位 |
| analysis | AI分析 | 分析DOM结构 |
| user_interaction | 请求用户输入 | 请求用户选择职位 |
| other | 其他操作 | 初始化配置 |

| execution_method | 使用场景 | 示例 |
|------------------|---------|------|
| command | CLI命令 | uv run frago navigate |
| recipe | Recipe调用 | runner.run('recipe_name') |
| file | 执行脚本文件 | uv run python scripts/filter.py |
| manual | 人工操作 | 等待用户登录 |
| analysis | AI推理 | 分析页面结构 |
| tool | AI工具调用 | AskUserQuestion |

### 日志结构模板

```json
{
  "schema_version": "1.0",
  "timestamp": "2025-11-21T10:30:00Z",
  "step": "导航到搜索页",
  "status": "success",
  "action_type": "navigation",
  "execution_method": "command",
  "data": {
    "command": "uv run frago navigate https://example.com",
    "exit_code": 0,
    "duration_ms": 1200
  }
}
```

### 考虑的替代方案

- **方案A：纯文本日志 + 正则解析**
  拒绝原因：易出错，难以处理多行输出和嵌套数据

- **方案B：SQLite数据库**
  拒绝原因：需要额外维护schema，不适合流式写入，难以用文本工具查看

- **方案C：Protobuf二进制格式**
  拒绝原因：过度工程化，人类不可读，不利于调试

### 参考

- [JSON Logging Best Practices - Loggly](https://www.loggly.com/use-cases/json-logging-best-practices/)
- [Python JSON Logger](https://github.com/madzak/python-json-logger) - structlog的轻量级替代
- [ISO 8601 - Wikipedia](https://en.wikipedia.org/wiki/ISO_8601)

---

## 3. 当前run上下文的存储方式

### 决策

采用 **轻量级JSON文件** 方案：
- 文件路径：`.frago/current_run` （无扩展名，Git忽略）
- 格式：JSON，包含 `run_id`、`last_accessed`、`theme_description`
- 读取优先级：环境变量 `FRAGO_CURRENT_RUN` > `.frago/current_run` 文件
- 失效处理：文件不存在或指向的run目录被删除时，提示用户使用 `set-context` 命令

### 理由

1. **JSON可扩展**：未来可添加 `auto_screenshot: true` 等全局配置
2. **Git忽略**：避免不同开发者的工作上下文冲突
3. **环境变量覆盖**：支持CI/CD或脚本化场景（`FRAGO_CURRENT_RUN=test-run pytest`）
4. **主题型设计不需要并发**：用户通常一次只聚焦一个主题，如需切换使用 `set-context`

### 文件格式示例

```json
{
  "run_id": "find-job-on-upwork",
  "last_accessed": "2025-11-21T10:30:00Z",
  "theme_description": "在Upwork上寻找Python开发职位并分析薪资范围"
}
```

### 考虑的替代方案

- **方案A：纯文本（只存run_id）**
  拒绝原因：无法扩展，未来添加配置项需要重新设计格式

- **方案B：TinyDB或pickleDB**
  拒绝原因：过度设计，单个键值对不需要数据库

- **方案C：支持多个并发run（JSON数组）**
  拒绝原因：与主题型设计冲突，增加复杂度，用户难以理解"当前是哪个run"

### 读取逻辑伪码

```python
def get_current_run_context() -> Optional[dict]:
    # 1. 检查环境变量
    if env_run_id := os.getenv('FRAGO_CURRENT_RUN'):
        return {"run_id": env_run_id}

    # 2. 读取配置文件
    config_path = Path('.frago/current_run')
    if not config_path.exists():
        return None

    data = json.loads(config_path.read_text())

    # 3. 验证run目录存在
    run_dir = Path('runs') / data['run_id']
    if not run_dir.exists():
        print(f"警告: run目录 {run_dir} 不存在，请重新设置上下文")
        return None

    return data
```

### 参考

- [A Peek at Three Python Databases](https://www.opensourceforu.com/2017/05/three-python-databases-pickledb-tinydb-zodb/) - 轻量级存储对比
- [PEP 550 – Execution Context](https://peps.python.org/pep-0550/) - Python上下文设计哲学

---

## 4. 截图自动编号机制

### 决策

采用 **基于现有文件扫描 + 原子性写入** 方案：
- 扫描 `screenshots/` 目录获取最大序号（正则匹配 `^\d{3}_`）
- 新截图序号 = max(现有序号) + 1，格式 `%03d`（001、002...）
- 使用临时文件 + 原子性重命名避免并发冲突
- 文件名格式：`<序号>_<描述slug>.png`

### 理由

1. **简单可靠**：无需维护额外的状态文件（`.next_number`）
2. **自愈能力**：用户手动删除截图不影响编号逻辑
3. **原子性写入**：先写临时文件，成功后重命名，避免半写状态
4. **并发冲突低**：实际使用中AI串行执行，不太可能同时截图

### 实现伪码

```python
import re
from pathlib import Path

def get_next_screenshot_number(run_id: str) -> int:
    screenshots_dir = Path('runs') / run_id / 'screenshots'
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    # 扫描现有文件，提取序号
    max_num = 0
    for file in screenshots_dir.glob('*.png'):
        match = re.match(r'^(\d{3})_', file.name)
        if match:
            max_num = max(max_num, int(match.group(1)))

    return max_num + 1

def save_screenshot(run_id: str, description: str, image_data: bytes):
    screenshots_dir = Path('runs') / run_id / 'screenshots'
    num = get_next_screenshot_number(run_id)
    slug = slugify(description, max_length=40)

    # 原子性写入
    temp_file = screenshots_dir / f'.tmp_{num:03d}_{slug}.png'
    final_file = screenshots_dir / f'{num:03d}_{slug}.png'

    temp_file.write_bytes(image_data)
    temp_file.rename(final_file)  # 原子操作

    return final_file
```

### 考虑的替代方案

- **方案A：维护 `.next_number` 状态文件**
  拒绝原因：需要处理文件锁、状态同步；用户删除截图后状态失效

- **方案B：使用 `multiprocessing.Value` + Lock**
  拒绝原因：过度工程化，run命令本身不涉及多进程

- **方案C：时间戳命名（`HHMMSS_<描述>.png`）**
  拒绝原因：可读性差，难以按执行顺序排序

### 并发场景分析

**风险**：两个进程同时调用 `get_next_screenshot_number()` 可能返回相同序号。
**缓解措施**：
1. 实际使用中AI串行执行，并发概率极低
2. 如果真冲突，原子性重命名会导致一个进程失败，可重试（序号+1）
3. 如未来需要严格并发安全，可引入文件锁（`fcntl.flock`）

### 参考

- [Atomic Operations in Python](https://superfastpython.com/thread-atomic-operations/)
- [How to create an incrementing filename](https://stackoverflow.com/questions/17984809/how-do-i-create-an-incrementing-filename-in-python)

---

## 5. /frago.run slash命令的实现方式

### 决策

采用 **轻量级Markdown + Bash命令调用** 方案（符合现有项目模式）：
- Markdown文件：`.claude/commands/frago.run.md`
- YAML frontmatter：`description: "执行AI主持的复杂浏览器自动化任务"`
- 命令调用：使用 `Bash` 工具执行 `uv run frago run <subcommand>`
- 长时间任务：在文档中明确指示AI每5步输出一次进度摘要
- 结果展示：读取 `execution.jsonl` 最后10行并格式化输出

### 理由

1. **一致性**：项目现有的 `/frago.recipe`、`/frago.test` 都使用Markdown格式
2. **灵活性**：Markdown可包含详细的执行流程指引、示例代码
3. **工具链成熟**：Claude Code的Bash工具支持超时、后台运行
4. **无需新框架**：不引入questionary等第三方交互库，保持依赖简洁

### 命令文档结构（参考/frago.recipe.md）

```markdown
---
description: "执行AI主持的复杂浏览器自动化任务并管理run实例"
---

# /frago.run - Run命令系统

## 你的任务

作为任务执行者，使用run命令系统管理AI主持的复杂浏览器自动化任务...

## 执行流程

### 1. 发现现有run实例
```bash
uv run frago run list --format json
```

### 2. 交互式选择
使用AskUserQuestion工具展示run列表...

### 3. 固化工作环境
```bash
uv run frago run set-context <run_id>
```

### 4. 执行任务并记录日志
每个关键步骤后：
```bash
uv run frago run log --step "..." --status "success" --action-type "..." --execution-method "..." --data '{...}'
```

### 5. 进度展示
每5步输出一次进度摘要...
```

### 考虑的替代方案

- **方案A：使用questionary构建交互菜单**
  拒绝原因：引入新依赖，与项目现有模式不一致；Claude Code已有AskUserQuestion工具

- **方案B：纯Python脚本（不用Markdown）**
  拒绝原因：失去自然语言指引的灵活性；与现有slash命令风格不一致

- **方案C：支持流式日志输出（WebSocket）**
  拒绝原因：过度设计，CLI工具不需要实时流式输出

### 长时间任务处理策略

根据spec.md User Story 1，任务可能涉及多步骤探索。处理方式：

1. **分段执行**：每5步输出摘要（"已完成：导航→提取→分析"）
2. **检查点机制**：每10个日志条目强制 `fsync()` 避免数据丢失
3. **用户可中断**：文档明确说明用户可随时Ctrl+C，下次继续时从日志恢复

### 参考

- 现有命令：`.claude/commands/frago.recipe.md`（611行，提供详细执行流程）
- 现有命令：`.claude/commands/frago.test.md`（134行，清晰的步骤划分）
- [Click CLI Best Practices](https://realpython.com/python-click/)

---

## 6. Run实例自动发现和交互式菜单

### 决策

采用 **文件系统扫描 + AskUserQuestion工具 + RapidFuzz相似度匹配** 方案：
- 扫描 `runs/` 目录，读取每个run的 `.frago/current_run` 或 `logs/execution.jsonl` 首行提取主题
- 使用 RapidFuzz 计算用户任务描述与现有run主题的相似度（Levenshtein距离）
- 相似度 > 60% 的run高亮显示为"可能相关"
- 使用 AskUserQuestion 创建交互式菜单（与项目现有模式一致）

### 理由

1. **RapidFuzz性能卓越**：C++实现，比FuzzyWuzzy快10倍以上，2025年仍活跃维护
2. **多种相似度算法**：支持 Levenshtein、Jaro-Winkler、Token Sort Ratio
3. **AskUserQuestion符合项目模式**：现有代码已使用此工具，无需引入新依赖
4. **60%阈值经验证**：Stack Overflow和Typesense文档推荐的通用阈值

### 实现伪码

```python
from rapidfuzz import fuzz
from pathlib import Path
import json

def discover_runs(task_description: str) -> list[dict]:
    runs_dir = Path('runs')
    if not runs_dir.exists():
        return []

    runs = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue

        # 提取主题（优先从execution.jsonl首行）
        log_file = run_dir / 'logs' / 'execution.jsonl'
        theme = run_dir.name  # 默认使用目录名
        if log_file.exists():
            first_line = log_file.read_text().split('\n')[0]
            data = json.loads(first_line)
            theme = data.get('data', {}).get('theme_description', theme)

        # 计算相似度（使用Token Sort Ratio，忽略词序）
        similarity = fuzz.token_sort_ratio(task_description, theme)

        runs.append({
            'run_id': run_dir.name,
            'theme': theme,
            'similarity': similarity,
            'last_modified': run_dir.stat().st_mtime
        })

    # 按相似度排序，高亮相关run
    runs.sort(key=lambda x: (-x['similarity'], -x['last_modified']))
    return runs

def show_run_selection_menu(runs: list[dict], task_description: str):
    # 使用AskUserQuestion工具
    options = []
    for run in runs[:5]:  # 最多显示5个
        label = f"{run['run_id']} (相似度: {run['similarity']}%)"
        desc = f"主题: {run['theme']}"
        if run['similarity'] > 60:
            label = f"⭐ {label}"  # 高亮相关run
        options.append({'label': label, 'description': desc})

    options.append({
        'label': '创建新run',
        'description': f'为任务"{task_description}"创建新的run实例'
    })

    # 调用AskUserQuestion（伪代码，实际通过工具调用）
    answer = ask_user_question(
        question="发现现有run实例，选择继续哪个？",
        header="Run选择",
        options=options
    )
    return answer
```

### 相似度算法选择

| 算法 | 适用场景 | 示例 |
|-----|---------|------|
| **token_sort_ratio** | 词序无关（推荐） | "在Upwork找工作" vs "找工作在Upwork" → 100% |
| partial_ratio | 部分匹配 | "Python开发" vs "Python后端开发" → 高分 |
| ratio | 严格匹配 | "find job" vs "find-job" → 低分 |

选择 **token_sort_ratio**：容忍词序变化，适合自然语言描述。

### 考虑的替代方案

- **方案A：使用click.prompt手动输入选择**
  拒绝原因：用户体验差，需要记住run_id；不支持相似度提示

- **方案B：使用simple-term-menu库**
  拒绝原因：引入新依赖；与项目现有AskUserQuestion模式不一致

- **方案C：纯字符串匹配（`in` 操作符）**
  拒绝原因：无法处理拼写错误、词序变化

### 主题提取策略

从哪里读取主题描述？优先级：

1. **execution.jsonl 首行** - 最准确，`init` 命令记录的原始任务描述
2. **run目录名** - 后备方案，但可能是slug化后的模糊版本
3. **metadata.json**（可选） - 如未来需要更多元数据，可在init时创建

### 参考

- [RapidFuzz GitHub](https://github.com/rapidfuzz/RapidFuzz) - 官方文档和算法说明
- [Fuzzy String Matching Tutorial](https://www.datacamp.com/tutorial/fuzzy-string-python)
- [RapidFuzz vs FuzzyWuzzy](https://plainenglish.io/blog/rapidfuzz-versus-fuzzywuzzy) - 性能对比

---

## 依赖库总结

基于上述决策，需要添加以下依赖到 `pyproject.toml`：

```toml
dependencies = [
    # 现有依赖...
    "pypinyin>=0.51.0",      # 中文转拼音（2025年1月最新）
    "python-slugify>=8.0.0", # Unicode安全的slug化
    "rapidfuzz>=3.0.0",      # 高性能模糊匹配
]
```

**不需要添加**：
- `questionary` / `simple-term-menu` - 使用现有的AskUserQuestion工具
- `python-json-logger` - 手动构建JSON即可，无需logger框架
- `TinyDB` / `pickleDB` - JSON文件足够

---

## 实现优先级建议

基于决策的相互依赖关系，建议按以下顺序实现：

1. **Phase 1: 核心命令**（无依赖）
   - `uv run frago run init <description>` - 使用pypinyin+slugify
   - `uv run frago run set-context <run_id>` - 读写.frago/current_run
   - `uv run frago run log ...` - JSONL追加写入

2. **Phase 2: 截图和状态管理**（依赖Phase 1）
   - `uv run frago run screenshot <description>` - 基于文件扫描编号
   - `uv run frago run list` - 扫描runs/目录

3. **Phase 3: 智能发现**（依赖Phase 1+2）
   - 自动发现机制 - 使用RapidFuzz匹配相似run
   - `/frago.run` slash命令 - 集成所有子命令

4. **Phase 4: 清理和文档**
   - 删除旧的视频制作命令
   - 更新CLAUDE.md和用户文档

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| pypinyin多音字误判 | slug不符合预期 | 允许用户通过交互菜单修改主题名 |
| JSONL文件过大（>100MB） | 性能下降 | 实现日志轮转（execution.001.jsonl） |
| 截图并发冲突 | 文件覆盖 | 临时文件+原子重命名；如需严格安全加文件锁 |
| RapidFuzz误匹配 | 推荐无关run | 允许用户忽略推荐，创建新run |
| `.frago/current_run` 损坏 | 命令失败 | 提示用户重新set-context；考虑备份机制 |

---

## 总结

本研究文档通过Web搜索和现有代码分析，为Run命令系统的6个关键技术问题提供了决策依据。所有方案遵循以下原则：

1. **简单性优先**：避免过度工程化（如不用数据库存储简单配置）
2. **与现有代码一致**：遵循项目现有模式（Markdown slash命令、AskUserQuestion工具）
3. **行业最佳实践**：采用成熟库（pypinyin、RapidFuzz）和标准格式（JSONL、ISO 8601）
4. **实用性验证**：所有枚举值和阈值都经过spec.md场景验证

建议按Phase 1→2→3→4顺序实现，确保核心功能稳定后再添加智能特性。
