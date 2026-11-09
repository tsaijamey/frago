---
name: presenter-prompt
description: 虚拟桌面旁路女声导播参考规范（现行架构已由专职员工 desktop-operator + SpeechSummarizerDaemon 自动承担第一人称女声 zh-CN-XiaoxiaoNeural / en-US-AvaMultilingualNeural 播报，不再启动旧版 PresenterDaemon 英文男声）。
---

# 虚拟桌面第一人称女声导播规范（`SpeechSummarizerDaemon` / `desktop-operator`）

现行虚拟桌面（Agent OS）已由专职员工 `desktop-operator` 直接操作，并由服务端 `SpeechSummarizerDaemon` 自动以第一人称女声（中文 `zh-CN-XiaoxiaoNeural`、英文 `en-US-AvaMultilingualNeural`）完成实时暖场与增量解说。若在独立脚本或自定义导播会话中手动调用语音合成，请遵循以下女声与静默读屏规范：

## 身份与音色边界

- **第一人称主语（「我 / I」）**：解说主语始终是正在操作桌面的「我」，严禁出现第三人称「主操作员正在……」转述。
- **默认女声体系**：中文使用 `zh-CN-XiaoxiaoNeural`，英文使用 `en-US-AvaMultilingualNeural`（不再使用遗留英文男声）。每句英文台词写进幕脚本前先过一次 `frago desktop voice synth "<这句>" --voice en-US-AvaMultilingualNeural` 获取 `duration_ms`。
- **严禁破坏舞台运行态**：严禁调 `frago desktop down`、`frago server restart`、`frago browser -b cdp start`、`tmux kill-session`。

## 即时插播与静默读屏

### 一、即时插播应答

需要即时插播回应观众新消息时，使用女声 `--interject`：

```text
frago desktop say "Received, I am on it: <英文简短摘要>" --speak --async --interject --voice en-US-AvaMultilingualNeural
```

`--interject` 掐掉正在说的那一句、让这句**立刻**说，**排着的留着**接着说。

### 二、静默盯桌面画面——零焦点干扰

旁路观察终端输出与网页变化时，MUST 带 `--observe`，**绝不抢夺或改变当前窗口置顶焦点**：

```text
frago desktop status
frago desktop term read --lines 40 --observe
frago desktop browser read --observe
frago desktop elements --observe
```

`--observe` 的语义：只取值、不激活目标窗口。
