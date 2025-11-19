# /auvima.start

信息收集阶段 - 根据主题收集并整理信息（原auvima.prepare）

## 用法
```
/auvima.start <topic> [project_name]
```

## 支持的内容类型（仅限以下4类）

1. **资讯深度分析** - 必须提供核心观点
2. **GitHub项目解析** - 提供仓库URL
3. **产品介绍** - 产品名称或官网
4. **MVP开发演示** - 产品想法和技术栈

## 主要任务

1. 验证主题类型是否符合要求
2. 创建项目目录结构
3. 根据类型收集信息
4. 生成研究报告
5. 保存截图素材

## 输出文件

```
projects/<project_name>/
└── research/
    ├── report.json         # 信息收集报告
    ├── sources.json        # 信息来源索引
    ├── screenshots/        # 页面截图
    └── start.done          # 完成标记（pipeline检测用）
```

## 完成标记

**必须**在所有任务完成后创建 `start.done` 空文件，位于项目根目录。

## 可用工具

### Chrome CDP命令（通过Python CLI）
- `uv run auvima navigate <url>` - 导航网页
- `uv run auvima get-content [--selector <selector>]` - 提取内容
- `uv run auvima screenshot <output_file>` - 截图（必须使用绝对路径）
- `uv run auvima scroll [--pixels <px>] [--direction <up/down>]` - 滚动页面
- `uv run auvima click <selector>` - 点击元素
- `uv run auvima wait <seconds>` - 等待加载

### 其他工具
- Git克隆和分析
- 本地文件读取
- 命令行工具执行

## 收集边界

- 时间限制：单主题不超过10分钟
- 截图限制：不超过20张
- 必须覆盖核心功能
- 信息来源必须可靠

## 实现脚本
`scripts/auvima_start.py` (待实现)