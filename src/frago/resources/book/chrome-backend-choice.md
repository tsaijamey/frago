# chrome-backend-choice

frago chrome 有两套后端，行为差异显著。选错会绕路或失败。

## 后端选择

```
{{frago_launcher}} chrome <cmd> -b cdp        # 默认；FRAGO_CHROME_BACKEND env 也可设
{{frago_launcher}} chrome <cmd> -b extension  # 通过浏览器扩展 + native messaging
```

| 维度 | CDP | Extension |
|------|-----|-----------|
| 命令覆盖 | 全部 26 条 | 大部分（不支持 stop / 启动模式相关）|
| 浏览器生命周期 | start/stop 完整管理 | start/stop 是 no-op，浏览器需另外起 |
| anti-bot 探针 | ❌ | ✅ `detect` 命令独有 |
| 通过 CF / Akamai | 易被检测 | 真实用户环境，过检率高 |
| 启动选项（headless/void/profile-dir/port） | ✅ | ❌ |
| 性能 / 调试 | 直连 DevTools，最快 | 多一层 RPC，略慢 |

**默认选 CDP**。下列场景切 extension：
1. 网站有 anti-bot 检测（Cloudflare / Datadome / PerimeterX / Akamai）
2. 需要 `frago chrome detect --group <g>` 探针返回 challenge 状态
3. 受限环境（localhost:9222 不可用，比如某些公司网络）
4. 走真人 profile（用户日常用的浏览器扩展、登录态）做"代为操作"

## Profile 隔离机制（CDP 后端）

CDP 启动浏览器时用 `--user-data-dir=~/.frago/<browser>_profile`，**跟系统浏览器 profile 完全隔离**：

- **首次**启动从系统 profile（`Default/` + `Local State`）拷贝一次：登录态、cookies、书签带过来
- 之后两边各走各的——frago 里改不影响系统浏览器，反之亦然
- 不同 `--port` 启动会派生独立 profile（`<browser>_profile_<port>`），多实例并存

含义：
- agent 第一次开 frago Chrome 看到的是用户当时的快照，不必担心污染日常浏览器
- 反过来：日常浏览器后续登的新账号、装的新扩展，frago 这边看不到——必要时 `rm -rf ~/.frago/<browser>_profile` 让它下次启动重新从系统拷

`--profile-dir <path>` 可指定独立 profile 目录（多账号场景）。

## Extension 后端的特殊约束

- 必须先有运行中的浏览器 + 装好 frago extension（`frago.chrome.extension.bundle_path()` 给路径）
- `start` 不会启动浏览器，只检查桥接（unix socket `~/.frago/chrome/extension.sock`）
- `stop` 是 no-op，不能用 frago 关 extension 后端的浏览器
- 走 native messaging + JSON-RPC，daemon 进程独立

## 决策流

```
任务 → 是否反爬场景？
        ├─ 是 → -b extension（先 detect 探一下）
        └─ 否 → -b cdp（默认即可）
              → 需要换 browser/port/headless？→ 见 chrome-startup
```
