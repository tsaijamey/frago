# recipe-execution

分类: 效率（AVAILABLE）

## 是什么
frago recipe 系统提供可复用的自动化脚本。执行前先查询可用 recipe，避免重复造轮子。支持同步和异步执行。

## 怎么用
  frago recipe list                                            # 查看所有可用 recipe
  frago recipe info <name>                                     # 查看 recipe 详情（参数、用法、来源）
  frago recipe run <name> --params '{"key": "value"}'          # 同步执行
  frago recipe run <name> --params '{"key": "value"}' --async  # 异步执行

## 跑起来是什么样

- 配方跑在一个只看得见指定目录的视图里：本次运行的落点、自己的 `~/.frago/recipe-data/<配方>/` 可写；别人写了 `shares` 的那块、系统与解释器、配方源码只读；其余一切不存在，越界当场失败。
- 后端由内核来管：macOS 用自带的 `sandbox-exec`；Linux 用 `bwrap`，**没装 bubblewrap 就拒绝起配方**（`apt install bubblewrap`）。要关掉，MUST 在 `~/.frago/config.json` 明写 `"recipe": {"isolation": "off"}`。
- frago 包里不带任何配方，`frago init` 也装不来配方。要配方去社区仓库 `tsaijamey/frago-recipe-community` 取。

## 什么时候用
- 开始一个浏览器自动化任务前，先查看是否已有对应 recipe
- 需要重复执行的操作，应封装为 recipe
- 长时间运行的任务用 --async 异步执行

## 不要做
- 不要直接 python 执行 recipe 脚本文件
- 不要在不查看已有 recipe 的情况下从头写自动化逻辑
- 不要用 2>&1 重定向 recipe 输出（会丢失结构化返回值）
