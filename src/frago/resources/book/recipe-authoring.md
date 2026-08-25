# recipe-authoring

分类: 效率（AVAILABLE）

## 解决什么问题
agent 创建 Recipe 脚本时不知道参数怎么接收、输出怎么写、依赖怎么声明，导致写出无法运行的脚本。本文档覆盖 recipe 脚本代码编写规范，与 recipe-fields（元数据规范）互补。

## 参数接收方式

frago recipe runner 按 runtime 类型用不同方式传递参数。写错方式会导致脚本收不到参数。

### Python（runtime: python）

runner 执行：`uv run recipe.py '<json>'`，参数作为第一个命令行参数传入。

```python
import json
import sys

def main():
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            print(json.dumps({"success": False, "error": f"参数解析失败: {e}"}), file=sys.stderr)
            sys.exit(1)

    query = params.get('query', '')
    max_results = params.get('max_results', 10)

    # ... 业务逻辑 ...

    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

### Shell（runtime: shell）

runner 执行：`./recipe.sh '<json>'`，参数作为 `$1` 传入。

```bash
#!/bin/bash
set -e

# 参数从 $1 读取
INPUT="$1"
if [ -z "$INPUT" ]; then
    INPUT='{}'
fi

URL=$(echo "$INPUT" | jq -r '.url // empty')
QUALITY=$(echo "$INPUT" | jq -r '.quality // "1080p"')

if [ -z "$URL" ]; then
    echo '{"success": false, "error": "url is required"}' >&2
    exit 1
fi

# ... 业务逻辑 ...

# 结果输出到 stdout
jq -n --arg file "$OUTPUT_FILE" '{"success": true, "file": $file}'
```

### Chrome-JS（runtime: chrome-js）

runner 先执行 `window.__FRAGO_PARAMS__ = <json>`，再执行 recipe.js。脚本从全局变量读取。

```javascript
(async () => {
    const params = window.__FRAGO_PARAMS__ || {};
    const query = params.query || '';

    // ... 业务逻辑 ...

    return { success: true, data: result };
})();
```

## Secrets 接收方式（API key / token / 凭证）

**唯一标准通道**：环境变量 `FRAGO_SECRETS`，值是 JSON 字符串。runner 从 `~/.frago/recipes.local.json` 读取，按 recipe.md 的 `secrets:` schema 过滤后注入子进程 env。

**绝对禁止**：从 `params` 读 secrets、硬编码读 `os.environ["XXX_API_KEY"]` 等自定义环境变量、脚本里写 fallback 兜底。runner 不通过 params 传 secrets，也不会设置 recipe 专属的环境变量。

### recipe.md 声明 schema

```yaml
secrets:
  api_key:
    type: string
    required: true
    description: ARK API key
  app_id:
    type: string
    required: false
```

### Python 读取

```python
import json
import os

secrets = json.loads(os.environ.get("FRAGO_SECRETS", "{}"))
api_key = secrets.get("api_key")
if not api_key:
    print(json.dumps({"success": False, "error": "api_key missing; configure via Web UI or ~/.frago/recipes.local.json"}), file=sys.stderr)
    sys.exit(1)
```

### Shell 读取

```bash
API_KEY=$(echo "$FRAGO_SECRETS" | jq -r '.api_key // empty')
```

### Chrome-JS

chrome-js runtime 不注入 FRAGO_SECRETS（浏览器环境无法访问）。如果 chrome-js recipe 需要凭证，改用 workflow + system recipe 组合。

## Recipe 内调 frago CLI（subprocess）

recipe 子进程里要调 `frago browser navigate` / `frago <domain> find` 等命令时，直接裸写 `frago`：

```python
import subprocess

subprocess.run(["frago", "chrome", "navigate", url, "--no-border"], ...)
```

配方要把自己的页面交给人看时，这里换成 `frago recipe open`——它开在用户的系统默认浏览器里，跟 `frago browser` 驱动的那个受控浏览器是两回事，NEVER 用 `browser navigate` 代替：

```python
subprocess.run(["frago", "recipe", "open", url], ...)
```

带界面的配方完整写法见 `frago book interactive-recipe`。

**禁止写 `["uv", "run", "frago", ...]`**——它假设 uv 在 PATH 且 cwd 是 frago 项目，还会把调用引回仓库虚拟环境里那份可能过时的代码。

frago 只有一份，装在 uv tool 里、从 PATH 解析。仓库源码树永远不会用自己的 venv 跑 frago（见 `frago.server.launch_guard`），所以不需要探测、不需要 env 变量传递 argv、也不需要兜底链。

### 用户如何配置

用户在 Web UI 的 Recipe Secrets 面板填写，或手写 `~/.frago/recipes.local.json`：

```json
{
  "my_recipe": { "api_key": "sk-xxx", "app_id": "123" },
  "shared_ark": { "api_key": "sk-yyy" },
  "other_recipe": { "$ref": "shared_ark" }
}
```

runner 在执行前校验 `required: true` 的字段必须已配置，缺失直接报错。

## 配方之间只能靠接口，NEVER 读对方的源码

一个配方要用另一个配方的能力，只有一条路：**把它当命令跑，读它的结构化返回**。

```python
# ✅ 对：跑它，读它答应过的输出
r = subprocess.run(["frago", "recipe", "run", "astock_trade_ledger",
                    "--params", json.dumps({"mode": "data"})],
                   capture_output=True, text=True, timeout=120)
data = json.loads(r.stdout)
```

**NEVER 做的事**：读对方的源码文件、按函数名从里面抠代码、import 对方的模块、
直接读写对方的数据目录、假设对方的目录结构或文件名。

### 为什么这条是硬的

对方**不知道自己正在被读**。它的作者改自己的代码时，看不到任何提示说别处依赖着
这个函数名、这个文件位置、这行结构。于是断裂发生在一个跟改动毫无关系的地方，
而且往往要等到有人点开某张页面才暴露。

2026-08-25 实际发生过：`stock_structure_dma_report` 为了不自己手搓 DMA 口径，
去 `etf_structure_dma_plan/assets/app.js` 里按函数名抠出两个函数 eval 求值。
那份 app.js 的一次重写把函数删了，报表配方当场跑不动，报的是「看板源码结构已变」
——而做那次重写的人完全看不到这个后果。

注意它的**初衷是对的**：agent 手搓技术指标去断言「有没有金叉」确实是越位，
宁可用已有的那一份。错的是实现方式——把「复用口径」做成了「读对方源码」。

### 想复用又不想漂，怎么办

按代价从低到高：

1. **跑对方的命令，读返回值。** 口径永远是对方的，而且对方改了接口会立刻报错，
   不会静默给出错的数字。**默认选这个。**
2. **抄一份进自己的 lib，在文件头记下抄自哪个文件、哪个版本、什么时候抄的，
   并写明「改一边要改另一边」。** 口径会漂，但漂得看得见——而且它不会在别人改
   无关代码时断掉。
3. **把公共部分抽成两边都依赖的东西。** 最干净，但要动两个配方，得先跟它们的
   使用者对齐。

### 这条也适用于数据

「读对方的数据目录」和「读对方的源码」是同一个病。同一个人的两个配方要共用一份
账本，走 `frago book must-recipe-data` 里的共读数据，由平台交代目录；
NEVER 自己拼一条通往别人目录的路径。

## 输出规范

stdout 和 stderr 有严格分工，混用会导致 runner 解析失败。

| 通道 | 用途 | 格式 |
|------|------|------|
| stdout | 最终结果（runner 解析） | 必须是合法 JSON |
| stderr | 进度日志、调试信息 | 自由格式 |

### Python 输出模式

```python
# 进度 → stderr
print('[step1] 开始搜索...', file=sys.stderr)
print('[step1] ✓ 找到 15 条结果', file=sys.stderr)

# 最终结果 → stdout（整个脚本只 print 一次到 stdout）
print(json.dumps({"success": True, "count": 15, "data": results}, ensure_ascii=False))
```

### output_file 模式

即使结果写入文件，stdout 仍须输出状态 JSON：

```python
if output_file:
    with open(output_file, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(json.dumps({"success": True, "output_file": output_file, "count": len(results)}))
else:
    print(json.dumps(results, ensure_ascii=False))
```

### 错误输出

错误信息写 stderr，设置非零退出码：

```python
print(json.dumps({"success": False, "error": "描述"}), file=sys.stderr)
sys.exit(1)
```

## Python 依赖声明（PEP 723）

在 recipe.py 顶部用内联元数据声明，uv run 自动创建临时环境：

```python
# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx>=0.24", "beautifulsoup4"]
# ///
```

无需 requirements.txt。首次运行自动安装，后续使用缓存。
如需系统级包（如 dbus-python），在 recipe.md 中设 `system_packages: true`。

## 目录结构

```
Atomic (chrome):   ~/.frago/recipes/atomic/chrome/<name>/recipe.md + recipe.js
Atomic (system):   ~/.frago/recipes/atomic/system/<name>/recipe.md + recipe.py（或 recipe.sh）
Workflow:          ~/.frago/recipes/workflows/<name>/recipe.md + recipe.py
```

## 命名规范

格式：`<platform>_<verb>_<object>_<modifier>`

好：`youtube_extract_video_transcript`、`arxiv_search_papers`
坏：`youtube_transcript`（动词缺失）、`my_recipe`（无意义）

## Chrome-JS 脚本模式

使用 fallback selector 和等待模式，提高稳定性：

```javascript
(async () => {
    console.log('[start] executing...');

    function findElement(selectors, description) {
        for (const sel of selectors) {
            const elem = document.querySelector(sel);
            if (elem) {
                console.log(`[found] ${description} (${sel})`);
                return elem;
            }
        }
        throw new Error(`Cannot find ${description}`);
    }

    async function waitForElement(selector, timeout = 5000) {
        const start = Date.now();
        while (Date.now() - start < timeout) {
            const elem = document.querySelector(selector);
            if (elem) return elem;
            await new Promise(r => setTimeout(r, 100));
        }
        throw new Error(`Timeout waiting for ${selector}`);
    }

    const elem = findElement([
        '[aria-label="Search"]',
        '#search-input',
        '.search-box'
    ], 'search input');

    // ... 操作 ...

    return { success: true, data: result };
})();
```

## Workflow 脚本模式

Workflow 用 RecipeRunner 调用子 recipe：

```python
from frago.recipes import RecipeRunner
import json
import sys

def main():
    if len(sys.argv) < 2:
        params = {}
    else:
        params = json.loads(sys.argv[1])

    print('[start] executing workflow...', file=sys.stderr)
    runner = RecipeRunner()

    print('[step1] calling sub_recipe...', file=sys.stderr)
    result = runner.run('sub_recipe_name', params={'key': 'value'})
    if not result['success']:
        print(f'[error] sub recipe failed: {result.get("error")}', file=sys.stderr)
        sys.exit(1)
    print('[step1] ✓ done', file=sys.stderr)

    print(json.dumps({"success": True, "data": result}))

if __name__ == "__main__":
    main()
```

## 创建完整流程

```
1. frago recipe list                          # 确认不存在类似 recipe
2. 确定 type（atomic/workflow）和 runtime
3. 创建目录和 recipe.md（见 recipe-fields）
4. 编写脚本文件（本文档的模板）
5. frago recipe validate <path>               # 校验
6. frago recipe run <name> --params '{...}'   # 测试
```

## 不要做
- 不要用环境变量（如 RECIPE_PARAMS）接收参数 — runner 不会设置它
- 不要用 stdin 读参数（`input()` 或 `cat`）— runner 通过命令行参数传递
- 不要在 stdout 混入非 JSON 内容（进度日志走 stderr）
- 不要 `chmod +x` recipe 脚本 — runner 不需要
- 不要加 shebang 行 — runner 通过 uv run 或指定解释器执行
- 不要直接 `python recipe.py` 或 `node recipe.js` 执行 — 走 `frago recipe run`
- 不要用 `2>&1` 重定向 recipe 输出 — 会把 stderr 混入 stdout 破坏 JSON 解析
- 不要从 `params` 读 secrets（如 `params["secrets"]`、`params.get("api_key")`）— runner 不通过 params 传凭证
- 不要硬编码读 recipe 专属环境变量（如 `os.environ["ARK_API_KEY"]`、`os.environ["OPENAI_API_KEY"]`）— 凭证统一走 `FRAGO_SECRETS`
- 不要在脚本里写多通道 fallback（既读 FRAGO_SECRETS 又读 params 又读自定义 env）— 只用 FRAGO_SECRETS 一条路径
