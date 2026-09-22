"""WorkBuddy 这条借登录的连接，设置页要问的四件事都在这里。

## 四件事，代价差了几个数量级

- **登录态** —— 读一个本地文件。客户端退出登录时文件还留着、令牌字段变空，所以要解析，
  不能只看文件在不在。
- **能选哪些模型** —— 读客户端自己缓存的账号产品配置，不联网。客户端菜单读的就是这一份。
- **本期剩余积分** —— 一次 POST，不花模型额度。
- **探测** —— 每个模型真调一遍，两条协议依次试，四十多个模型一轮。这一步花模型额度，
  只在用户自己点下去时才跑。

## 为什么名单不读网关那份配置

网关配置下发 37 个模型，客户端菜单里是 51 个，前者是后者的子集：GLM-5.3、
Deepseek-V4.1-Flash、Hy4 preview 这些新的一个都不在网关那份里，而网关那份里还混着
`codewise-*` 补全模型、几个小模型和图像模型——客户端菜单从来不列它们。照网关那份列
下拉，结果就是新模型选不到、补全模型反倒排在最前面。

分辨的判据是积分倍率：**菜单上能选的都带倍率，补全模型、小模型、图像模型都没有**。
51 个里带倍率的 33 个，倍率数值与客户端界面上显示的逐个对得上。

换客户端版本号或身份头去要网关那份配置，名单一个字不变——「名单旧」不是版本号造成的。
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

#: 账务与鉴权那一侧。签到、续期、余额都在这儿；模型网关是另一个 host。
ACCOUNT_BASE = "https://www.workbuddy.cn"

#: 请求必须带客户端身份头，缺了对面会拒（400 或 403 code 10085）。
CLIENT_VERSION = "2.137.1"

#: 余额那一次请求的超时。它挂在「打开设置页」上，宁可取不到也不能让页面等。
BALANCE_TIMEOUT_SECONDS = 8

#: 余额缓存多久。反复开关表单不该每次都发请求。
BALANCE_CACHE_SECONDS = 120

#: 客户端缓存的账号产品配置：菜单那份名单就是它。
PRODUCT_CONFIG = Path.home() / ".workbuddy" / "cache" / "acc-product-config-v3.json"
#: 同目录下带哈希后缀的历史副本。当前那份读不到时退到最新的一份。
PRODUCT_CONFIG_SPILL = PRODUCT_CONFIG.parent / "conversation-product-spill"

#: 查余额要带的产品码与筛选条件。实测出来的，不是从文档抄的。
BALANCE_PRODUCT_CODE = "p_tcaca"
BALANCE_STATUSES = (0, 3)

_balance_cache: tuple[float, dict[str, Any] | None] | None = None
_balance_lock = threading.Lock()


def headers(login: dict[str, str]) -> dict[str, str]:
    """一次请求要带的全部头。企业账号多带两个，有域名的多带一个——少了对面会拒。"""
    out = {
        "Authorization": f"Bearer {login['access_token']}",
        "X-User-Id": login["uid"],
        "User-Agent": f"WorkBuddy/{CLIENT_VERSION}",
        "X-IDE-Type": "WorkBuddy",
        "X-IDE-Name": "WorkBuddy",
        "X-Product": "WorkBuddy",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if enterprise := login.get("enterprise_id"):
        out["X-Enterprise-Id"] = enterprise
        out["X-Tenant-Id"] = enterprise
    if domain := login.get("domain"):
        out["X-Domain"] = domain
    return out


# ── 能选哪些模型 ────────────────────────────────────────────────────────────


def _load_product_config() -> list[dict[str, Any]]:
    """客户端缓存的那份名单。读不到就空着。

    客户端只在运行时写它，本机没有别的东西会更新——客户端一直不开，名单就一直是旧的。
    那不是这里能解决的事，如实空着比编一份出来好。
    """
    paths = [PRODUCT_CONFIG]
    if PRODUCT_CONFIG_SPILL.is_dir():
        paths += sorted(
            PRODUCT_CONFIG_SPILL.glob("acc-product-config-v3-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # 当前那份是裸的配置对象；有些副本外面还套着一层响应壳。
        if isinstance(data, list) and data and isinstance(data[0], dict):
            data = data[0].get("data")
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            models = [m for m in data["models"] if isinstance(m, dict) and m.get("id")]
            if models:
                return models
    return []


def credits_value(raw: Any) -> float | None:
    """倍率的数值。`x0.79` 这种写法解出 0.79；不是倍率就回 None。"""
    if not isinstance(raw, str):
        return None
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", raw)
    return float(m.group(1)) if m else None


def chat_models() -> dict[str, dict[str, Any]]:
    """客户端菜单里能选的那些模型，按 id 索引。

    判据是带倍率。不带倍率的是补全模型、小模型和图像模型——把它们列进下拉，
    等于让人从一堆根本不是用来对话的东西里挑。
    """
    out: dict[str, dict[str, Any]] = {}
    for m in _load_product_config():
        value = credits_value(m.get("credits"))
        if value is None:
            continue
        out[m["id"]] = {
            "id": m["id"],
            "name": m.get("name") or m["id"],
            "credits": m["credits"],
            "credits_value": value,
        }
    return out


def sort_key(model: dict[str, Any]) -> tuple[int, float, float, str]:
    """下拉里的排法：能用的在前，倍率低的在前，同倍率里快的在前。

    倍率是花多少，延迟是等多久。花多少是挑模型时先看的那一项，所以它当主键；延迟仍然
    量着、仍然存着——它决定这个模型在网关上能不能用、认哪条口，只是不再当显示主角。
    """
    ok = 0 if model.get("ok") else 1
    rate = model.get("credits_value")
    rate = rate if isinstance(rate, (int, float)) else 10**6
    first_ms = model.get("first_ms")
    latency = first_ms if isinstance(first_ms, int) else 10**9
    return (ok, rate, latency, str(model.get("id") or ""))


# ── 本期剩余积分 ────────────────────────────────────────────────────────────


def credit_balance(*, use_cache: bool = True) -> dict[str, Any] | None:
    """本期还剩多少积分，以及最早到期的那一笔。None = 没登录或取不到。

    账上是一个个资源包，不是一个总数；扣费按到期时间从早到晚烧，所以光报总数不够诚实
    ——最早到期那一笔和它的日子同样要说，攒着没用完是会整包作废的。
    """
    global _balance_cache

    if use_cache and _balance_cache and time.time() - _balance_cache[0] < BALANCE_CACHE_SECONDS:
        return _balance_cache[1]

    from frago.init.profile_manager import workbuddy_login

    login = workbuddy_login()
    if not login:
        return None
    now = datetime.now()
    body = {
        "PageNumber": 1,
        "PageSize": 50,
        "ProductCode": BALANCE_PRODUCT_CODE,
        "Status": list(BALANCE_STATUSES),
        # 起点往前放宽一年多：资源包的周期起始日可能在很久以前，窗口开小了会漏掉。
        "PackageStartTimeRangeBegin": (now - timedelta(days=400)).strftime("%Y-%m-%d 00:00:00"),
        "PackageStartTimeRangeEnd": now.strftime("%Y-%m-%d 23:59:59"),
    }
    try:
        response = requests.post(
            f"{ACCOUNT_BASE}/v2/billing/meter/get-user-resource",
            headers=headers(login),
            json=body,
            timeout=BALANCE_TIMEOUT_SECONDS,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.debug("取 WorkBuddy 积分余额失败：%s", exc)
        return None
    if not isinstance(payload, dict) or payload.get("code") != 0:
        logger.debug("WorkBuddy 积分余额返回 code=%s", (payload or {}).get("code"))
        return None

    accounts = (((payload.get("data") or {}).get("Response") or {}).get("Data") or {}).get(
        "Accounts"
    )
    if not isinstance(accounts, list):
        return None

    remaining = 0
    soonest: tuple[str, int] | None = None
    for a in accounts:
        if not isinstance(a, dict):
            continue
        left = a.get("CycleCapacityRemain")
        if not isinstance(left, (int, float)) or left <= 0:
            continue
        remaining += int(left)
        end = str(a.get("CycleEndTime") or "").strip()
        if end and (soonest is None or end < soonest[0]):
            soonest = (end, int(left))

    result = {
        "remaining": remaining,
        "expires_at": soonest[0][:10] if soonest else None,
        "expiring": soonest[1] if soonest else None,
    }
    with _balance_lock:
        _balance_cache = (time.time(), result)
    return result


# ── 探测：起一次，盯着它跑完 ────────────────────────────────────────────────

_probe_lock = threading.Lock()
_probe: dict[str, Any] = {"running": False, "started_at": None, "ok": None, "error": None}


def core_binary() -> Path:
    """frago-core 的落点。派活起它的那条路径，这里照用。"""
    return Path.home() / ".frago" / "bin" / "frago-core"


def probe_state() -> dict[str, Any]:
    with _probe_lock:
        return dict(_probe)


def probed_ids() -> set[str]:
    """上一轮探过的那些 id，不管探通没探通。"""
    from frago.init.profile_manager import WORKBUDDY_MODELS_PATH

    try:
        data = json.loads(WORKBUDDY_MODELS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {
        m["id"]
        for m in data.get("models", [])
        if isinstance(m, dict) and isinstance(m.get("id"), str)
    }


def start_probe() -> tuple[bool, str | None]:
    """起一次探测，立刻返回。``(起成功了吗, 起不来的原因)``

    一轮要跑几分钟，不能让请求在那儿等着。已经在跑就不再起第二个——两个进程抢着写同一份
    清单，写回时互相覆盖，结果是哪一轮的都不算。

    探测命令自己只按网关下发的名单探，而新模型不在那份名单里。所以这里把菜单上有、清单里
    还没探过的一并交给它——不交的话，点完探测 GLM-5.3 这些照样进不了可选项。
    """
    from frago.init.profile_manager import workbuddy_login_state

    binary = core_binary()
    if not binary.exists():
        return False, "frago-core 还没装好（~/.frago/bin 下找不到）"
    state = workbuddy_login_state()
    if state != "ok":
        return False, (
            "本机没有 WorkBuddy 登录，先打开客户端登录"
            if state == "no_client"
            else "WorkBuddy 客户端已退出登录，先在客户端登录一次"
        )
    with _probe_lock:
        if _probe["running"]:
            return False, "已经在探测了"
        _probe.update(running=True, started_at=time.time(), ok=None, error=None)

    extra = sorted(set(chat_models()) - probed_ids())
    argv = [str(binary), "models", "probe-workbuddy"]
    if extra:
        argv += ["--also", ",".join(extra)]
    threading.Thread(target=_run_probe, args=(argv,), daemon=True, name="workbuddy-probe").start()
    return True, None


def _run_probe(argv: list[str]) -> None:
    ok, error = False, None
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            # 四十多个模型、每个最多两条协议各 60 秒。给足，超了当它卡死。
            timeout=45 * 60,
        )
        ok = result.returncode == 0
        if not ok:
            # 失败原因写在最后几行，整份输出对页面没用。
            tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
            error = " / ".join(tail) or f"frago-core 退出码 {result.returncode}"
    except (OSError, subprocess.SubprocessError) as exc:
        error = f"起不来 frago-core：{exc}"
    finally:
        with _probe_lock:
            _probe.update(running=False, ok=ok, error=error)
    if ok:
        logger.info("WorkBuddy 模型探测跑完")
    else:
        logger.warning("WorkBuddy 模型探测失败：%s", error)
