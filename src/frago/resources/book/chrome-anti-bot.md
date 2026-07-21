# chrome-anti-bot

遇到 Cloudflare / Datadome / PerimeterX / Akamai / captcha / "verify you are human" / 403 / 重定向到验证页 时，**禁止盲目重试 click 或 navigate**。

## 探针命令

```bash
{{frago_launcher}} chrome detect --group <name>
```

返回 JSON：
```json
{
  "challenge": true,
  "type": "interactive | invisible_or_static | blocked",
  "needs_human": true,
  "detector": "cloudflare-turnstile" 
}
```

## 三档处理策略

| type | 含义 | 正确处理 |
|------|------|----------|
| `interactive` | 需要点击复选框、拖拽、点图（hCaptcha / Turnstile checkbox / reCAPTCHA challenge） | **停下，告知用户需要人工干预**，不要自动 click——脚本化点击会被识别为 bot 加重封锁 |
| `invisible_or_static` | 不可见挑战或静态等待（CF "checking your browser..." 5s 自动放行）| `frago chrome wait 8` 后再 detect 一次；最多重试 2 次 |
| `blocked` | 已被拒（403、IP 黑名单）| **失败**：换 IP / 换账号 / 用真人浏览器手动开。不再自动重试 |

## 为什么过检率高

frago chrome 运行在真实用户浏览器环境（扩展 + 真实 profile），没有自动化调试通道的指纹，多数 anti-bot 检测直接放行。这是默认行为，不需要任何额外 flag。

## 反模式（NEVER）

- `for i in range(10): click ...`：触发风控升级
- 截图当判断依据"看起来通过了"：visual 不可靠，用 detect 的结构化结果
- 调 `exec-js` 改 `navigator.webdriver`：CF/Akamai 早就检测这种 hook

## 链路示例

```bash
{{frago_launcher}} chrome start   # 首次：自动选浏览器+加载扩展+拉起 daemon
{{frago_launcher}} chrome navigate "https://target.com" --group t
{{frago_launcher}} chrome detect --group t
# {"challenge": true, "type": "invisible_or_static"}
{{frago_launcher}} chrome wait 8 --group t
{{frago_launcher}} chrome detect --group t
# {"challenge": false} → 继续后续操作
```

如果 type=interactive 或者 wait 后仍然 challenge → 报告用户、暂停、不重试。
