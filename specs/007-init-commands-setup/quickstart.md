# Quickstart: frago init 资源安装

## 快速开始

### 1. 安装 frago

```bash
pip install frago
# 或使用 uv
uv pip install frago
```

### 2. 初始化环境

```bash
frago init
```

执行后将：
- 检查并安装依赖（Node.js, Claude Code）
- 安装 Claude Code slash 命令到 `~/.claude/commands/`
- 创建 `~/.frago/recipes/` 并复制示例 recipe
- 配置认证方式

### 3. 验证安装

```bash
# 检查资源状态
frago init --status

# 在 Claude Code 中测试
# 输入 /frago.run 应能看到命令提示
```

---

## 常用操作

### 强制更新资源

升级 frago 后更新所有资源：

```bash
frago init --update-resources
```

### 仅更新配置

跳过依赖检查和资源安装：

```bash
frago init --skip-deps --skip-resources
```

### 重置环境

删除配置重新初始化：

```bash
frago init --reset
```

---

## 目录结构

安装后的用户目录结构：

```
~/.claude/
├── commands/
│   ├── frago.run.md       # Run 命令系统
│   ├── frago.recipe.md    # Recipe 管理
│   ├── frago.exec.md      # 一次性任务执行
│   └── frago.test.md      # Recipe 测试
└── skills/
    └── frago-browser-automation/
        └── SKILL.md

~/.frago/
├── config.yaml            # frago 配置
└── recipes/
    ├── atomic/
    │   ├── chrome/        # Chrome CDP 操作示例
    │   └── system/        # 系统操作示例
    └── workflows/         # Workflow 示例
```

---

## 故障排查

### 权限错误

```
❌ 无法写入 ~/.claude/commands/: Permission denied
```

**解决**：
```bash
mkdir -p ~/.claude/commands
chmod 755 ~/.claude/commands
frago init
```

### 命令不可见

Claude Code 中输入 `/frago.` 没有提示：

1. 确认文件已安装：
   ```bash
   ls ~/.claude/commands/frago.*.md
   ```
2. 重启 Claude Code

### Recipe 未找到

```bash
# 检查 recipe 目录
ls ~/.frago/recipes/

# 手动复制示例
frago init --update-resources
```
