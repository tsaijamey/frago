# remote-frago

分类: 效率（AVAILABLE）

## 是什么

一台服务器上也可以装 frago。它不是本机 frago 的从属进程，是另一个 agent：有自己的机器、自己的 hook 规则、自己的 def 知识、自己的浏览器。两边的正确关系不是 RPC —— 本机说「要发生什么」，服务端决定「在它那台机器上怎么发生」，因为只有它知道那台机器上装了什么、正在跑什么、东西该放哪。

通道复用的是 PA 的入口队列（`frago chat` 一直在本机用的那条）：消息进队 → 服务端 PA 带着那台机器的上下文读、决策、起 worker → 回复顺着同一条 WebSocket 回来。

## 怎么用

服务端拿 token（只需一次）：

    frago server token                  # 打印，首次调用自动生成
    frago server token --rotate         # 作废旧 token

本机登记并下发：

    frago remote add box --url http://127.0.0.1:18093 --token <token>
    frago remote send box "<任务书>"              # 阻塞等回复
    frago remote send box --prompt-file brief.md --json
    frago remote send box "<任务书>" --no-wait     # 只入队，不等
    frago remote status box                       # 通不通 + token 认不认
    frago remote chat box                         # 交互 REPL
    frago remote list / remove

`--json` 输出 `{"status","remote","msg_id","session_id","reply","trace","duration_ms"}`，
status 是 `ok` / `timeout` / `queued`。超时退出码 1，任务可能仍在跑，用 `frago remote chat` 接。

传输走 SSH 隧道最省事，控制面完全不上公网：

    ssh -L 18093:127.0.0.1:8093 box

## 什么时候用

- 任务要在那台机器上做才有意义（那边有数据、有账号、有常驻服务、要长跑）
- 本机要关机 / 换地方，但活儿得继续
- 服务端要产出一个公开页面（配合 `frago recipe expose`）

## 不要做

- 不要把任务书写成命令序列。写「要什么结果 + 硬约束（用哪个 recipe、产出落哪、要不要发布页面）」，剩下交给对面的 PA —— 它知道那台机器，你不知道。
- 不要为了省事把服务端的 `/api` 直接反代上公网。那套接口能读写任意路径、能起 agent、能跑脚本；公网只该看见 `/app/`。
- 不要在服务端把 `FRAGO_SERVER_HOST` 留成默认的 `0.0.0.0`。部署机上设成 `127.0.0.1`，只让反代碰得到；同时设 `FRAGO_TRUST_LAN=0`（否则同一个 VPC 里的邻居会被当成「本机」放行）和 `FRAGO_BEHIND_PROXY=1`（不再从对端地址推断信任，反代设不设转发头都不影响）。个人机器上这三个默认值是对的，别动。

## 相关

`frago book recipe-expose` — 把服务端的 recipe 页面开给公网看
