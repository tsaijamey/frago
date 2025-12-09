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
src/frago/           # 核心代码
examples/            # 示例 Recipe
.claude/commands/    # Claude Code slash 命令
.claude/skills/      # Claude Code skills
```

## 资源更新流程

```
.claude/commands/  ──┐
.claude/skills/    ──┼──→  frago dev-pack  ──→  src/frago/resources/
examples/          ──┘
```

## 禁止事项

- ❌ 直接修改 `src/frago/resources/`（由 dev-pack 自动生成）
- ❌ 直接修改 `~/.claude/` 或 `~/.frago/`（用户目录，通过命令管理）
- ✅ 修改源头 `.claude/` 或 `examples/`，再通过 `frago dev-pack` 同步

## 文档索引（按需阅读）

| 文档 | 用途 |
|------|------|
| `docs/concepts.md` | 核心概念与架构设计 |
| `pyproject.toml` | 依赖版本、入口点配置 |
| `specs/*/spec.md` | 各功能的规格说明 |
| `.claude/commands/frago/` | Agent 使用 frago 的行为规范 |
