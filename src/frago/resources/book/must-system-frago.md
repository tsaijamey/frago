# must-system-frago

分类: 替代（MUST）

## 解决什么问题

在 frago 源码仓库里，`uv run frago <命令>` 曾经能跑通。跑通本身就是问题：它执行的是仓库里的代码，而周围一切——正在服务的 server、recipe 实际调用的二进制、hook 推给 agent 的知识——都来自系统安装的那份。这个组合在任何真实用户机器上都不存在，所以在这里"验证通过"什么也证明不了。

更根本的是习惯问题。只要 `uv run frago book` 能出结果，agent 就永远学不会 `frago book`；写出来的文档、recipe、hook 规则也会跟着分叉成两套写法。

## 规则

一切 frago 命令用 `{{frago_launcher}} <命令>`。

唯一例外是打包入口：

    uv run frago server restart      # 在源码仓库里发布本地改动
    uv run frago server start

这条命令做的事是"把仓库打成 wheel 装到系统，再把自己换成系统 frago 继续跑"，它是唯一一条以仓库身份进去、以系统身份出来的路。改完代码想让改动生效，走的就是它。

## 两道闸门

CLI 顶层拦截：从源码仓库跑任何非 `server` 命令直接拒绝并退出，提示改用 `{{frago_launcher}}`。`--help` 放行（纯查询无副作用），测试套件通过 `FRAGO_ALLOW_CHECKOUT_CLI=1` 绕过——那是唯一预期的绕过口。

server 自身另有两道独立的闸门，管的是别的入口：绕过 CLI 直接执行守护进程模块、以及 systemd 从仓库 venv 拉起 server。两者不重合，都要留。

实现在 `frago.server.launch_guard`。

## 自查

    if 命令.以 "uv run frago" 开头:
        if 命令 是 "uv run frago server start|restart":
            放行  # 打包入口
        else:
            改写为 "frago ..."

## 相关

`{{frago_launcher}} book better-server-restart` — restart 前的活跃任务检查
