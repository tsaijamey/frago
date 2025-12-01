---
name: file_copy
type: atomic
runtime: shell
version: "1.0.0"
description: 复制文件从源路径到目标路径
use_cases:
  - 备份配置文件到指定位置
  - 在工作流中复制中间结果文件
  - 批量文件操作的原子步骤
tags:
  - file
  - system
  - copy
output_targets:
  - stdout
  - file
inputs:
  source_path:
    type: string
    required: true
    description: 源文件路径
  dest_path:
    type: string
    required: true
    description: 目标文件路径
outputs:
  source:
    type: string
    description: 源文件路径
  destination:
    type: string
    description: 目标文件路径
  size_bytes:
    type: number
    description: 文件大小（字节）
  operation:
    type: string
    description: 执行的操作类型
---

# Recipe: 复制文件

## 功能描述

将文件从源路径复制到目标路径，并返回操作结果信息（包括文件大小）。

## 使用方法

```bash
# 通过命令行参数
uv run frago recipe run file_copy --params '{"source_path": "/path/to/source.txt", "dest_path": "/path/to/dest.txt"}'

# 通过参数文件
echo '{"source_path": "/path/to/source.txt", "dest_path": "/path/to/dest.txt"}' > params.json
uv run frago recipe run file_copy --params-file params.json

# 输出到文件
uv run frago recipe run file_copy --params '{"source_path": "a.txt", "dest_path": "b.txt"}' --output-file result.json
```

## 前置条件

- 源文件必须存在且可读
- 目标路径的父目录必须存在且可写
- 需要 Bash shell 环境（Linux、macOS、WSL）

## 预期输出

```json
{
  "success": true,
  "data": {
    "source": "/path/to/source.txt",
    "destination": "/path/to/dest.txt",
    "size_bytes": 1024,
    "operation": "copy"
  }
}
```

## 注意事项

- 如果目标文件已存在，将被覆盖
- 复制操作不保留文件权限和元数据（使用标准 `cp` 命令）
- 仅支持单个文件复制，不支持目录

## 更新历史

- **v1.0.0** (2025-11-21): 初始版本，支持基础文件复制功能
