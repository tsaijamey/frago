# Frago Development Guidelines

## 本文档维护原则

本文件仅用于指导 Claude Code 迭代本仓库代码，内容限于：
- 项目目录结构
- 资源更新流程与禁止操作
- 开发时的技术偏好

不应包含：
- frago 产品的使用说明、命令参考、API 文档
- Agent 使用 frago 工具时的行为规范
- 版本号、依赖列表等可从 pyproject.toml 获取的信息

## 目录结构

```
src/frago/              # 核心代码
src/frago/resources/    # PyPI 包资源（由 dev pack 生成）
```

## 资源统一到用户目录

所有资源均存放在用户目录：

```
~/.claude/
├── commands/
│   ├── frago.*.md       # Frago 命令
│   └── frago/           # 命令规则和脚本
└── skills/
    └── frago-*/         # Frago skills

~/.frago/
├── config.json          # 全局配置
├── current_run          # 当前 run 上下文
├── projects/            # run 实例目录
├── recipes/             # Recipe 库
│   ├── atomic/
│   └── workflows/
├── sessions/            # Session 存储
└── chrome_profile/      # Chrome 配置
```

## 资源更新流程

```
~/.claude/commands/frago.*.md  ──┐
~/.claude/skills/frago-*       ──┼──→  frago dev pack  ──→  src/frago/resources/
~/.frago/recipes/              ──┘
```

## 禁止事项

- ❌ 直接修改 `src/frago/resources/`（由 dev pack 自动生成）
- ✅ 在 `~/.claude/` 和 `~/.frago/` 编辑资源，再通过 `frago dev pack` 同步

## 文档索引（按需阅读）

| 文档 | 用途 |
|------|------|
| `docs/concepts.md` | 核心概念与架构设计 |
| `pyproject.toml` | 依赖版本、入口点配置 |
| `specs/*/spec.md` | 各功能的规格说明 |
| `~/.claude/commands/frago/` | Agent 使用 frago 的行为规范 |
