#!/usr/bin/env python3
"""agent_os 实例注册表：身份层与运行态层分离。

一个实例的"物质载体"——人浏览器里那个标签页、viewer 内容目录、clips 目录、
tmux 会话——不会因为 broker 进程退出而消失。v1 把身份和运行态混在一起，
broker 一退出实例身份就没了，于是桌面页还开着却永远收不到画面，
系统也无从知道"那里还有一台等着被喂画面的显示器"。

所以拆成两层：

  身份层（id / content_id / desktop_url / clips_dir / tmux_session / created_at）
      首次创建后不再变动，实例永不自动删除。

  运行态层（pid / port / status / started_at / heartbeat_at）
      分钟级，每次启动覆写。

recipe.py 与 broker.py 共用本模块。两边各写一份必然会漂移——
字段名或 content_id 算法但凡差一个字符，身份就不再稳定，而这种错
表现成"桌面页地址莫名其妙变了"，极难往两份实现不一致上想。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
from pathlib import Path

FRAGO_HOME = Path.home() / ".frago"


#: 台账落在哪个名字底下。舞台进包之后落点一个字节都不换（见 migration-plan C7）：
#: 369 个 clips、broker.log、default.json 全部留在原处，所以这里仍是 agent_os。
#: 路径里那个 recipe-data 也名不副实了，一并保留——正名要连着 data_migration 一起
#: 做，改名换来的只是路径好看一点，代价是全部历史失联。
DATA_NAME = "agent_os"


def _instances_dir() -> Path:
    """舞台实例台账落在哪。自己向平台求，不等别人用环境变量交代。

    NEVER 自己拼路径：老落点 ~/.frago/data/agent-os/ 是一个主体容器，里面还住着
    人归档的交付物和另一个配方的视频项目，把运行状态混在那儿谁也说不清哪份归谁。
    NEVER 在模块顶层求值：这个文件被 broker 与 stage 两处 import，顶层解析身份
    会让它们一 import 就死，抛的还是一句看不懂的异常。

    此前这里读 FRAGO_RECIPE_DATA_DIR，由起进程的一方交代。那份进程间的口头约定
    在这台机器上已经烂了整整 4005 次：平台的保活守护按路径 import 本文件、却从不
    设那个变量，于是每 15 秒抛一次、被 except Exception 吞成一行 WARNING——
    **本机的虚拟桌面从来没有被守护过**，而没有一层报错。调用方有机会漏掉交代，
    就一定有人漏掉；自己求就没有这个机会。

    算出来的路径与从前逐字节相同（2026-09-02 实测）：
    ~/.frago/users/<身份>/recipe-data/agent_os
    """
    from frago.recipes.app_state import recipe_data_dir
    from frago.recipes.context import default_identity

    return recipe_data_dir(default_identity(), DATA_NAME)

IDENTITY_FIELDS = (
    "id", "content_id", "desktop_url", "clips_dir", "tmux_session", "created_at",
)
RUNTIME_FIELDS = ("pid", "port", "status", "started_at", "heartbeat_at")

# 人希不希望它跑，跟它现在跑没跑是两回事。守护只看得见"进程不在了"，而这有
# 两种截然相反的原因：崩了（该拉起）和人关的（不该动）。没有这个字段就分不开，
# 于是要么关不掉（关了被拉回来，回执还说停成功了），要么崩了没人管。
# 值只有两个：running / stopped。
DESIRED_FIELD = "desired"
DESIRED_RUNNING = "running"
DESIRED_STOPPED = "stopped"

DEFAULT_ID = "default"

# kebab-case：小写字母数字，中间可用单个连字符分段。
_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# 纯十六进制且够长 = 哈希或随机串。实例 id 是给人认的名字，
# 用哈希当 id 等于回到 v1 那种"每次算出来都不一样"的老路。
_HASHISH = re.compile(r"^[0-9a-f]{8,}$")


def validate_id(instance_id: str) -> str:
    if not instance_id:
        raise ValueError("实例 id 不能为空")
    if len(instance_id) > 40:
        raise ValueError(f"实例 id 过长（{len(instance_id)} > 40）: {instance_id}")
    if not _KEBAB.match(instance_id):
        raise ValueError(
            f"实例 id 必须是 kebab-case（小写字母数字加连字符）: {instance_id}"
        )
    if _HASHISH.match(instance_id):
        raise ValueError(f"实例 id 禁止使用哈希或随机串: {instance_id}")
    return instance_id


def content_id_for(instance_id: str) -> str:
    """由实例 id 计算，**不含端口**。

    v1 用 hash("agent_os:" + port)：端口一变 content_id 就变，桌面页 URL
    跟着变，人得重新开一个浏览器标签页。身份不该挂在一个随时可改的运行参数上。
    """
    return hashlib.sha256(f"agent_os:{instance_id}".encode()).hexdigest()[:12]


def path_for(instance_id: str) -> Path:
    return _instances_dir() / f"{instance_id}.json"


def _read_raw(instance_id: str) -> dict | None:
    p = path_for(instance_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_raw(instance_id: str, record: dict) -> None:
    p = path_for(instance_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 先写临时文件再原子替换：注册表会被 recipe 和 broker 两个进程读写，
    # 直接就地覆写的话，读方可能读到写了一半的 JSON。
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(p)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def ensure_identity(
    instance_id: str,
    *,
    desktop_url: str,
    clips_dir: str,
    tmux_session: str,
) -> dict:
    """确保身份层存在并返回完整记录。

    已存在则**原样返回身份层，不重算、不覆盖**——身份的全部价值就在于它不变。
    传进来的 desktop_url 等参数在这种情况下被忽略。
    """
    validate_id(instance_id)
    existing = _read_raw(instance_id)
    if existing and all(existing.get(f) for f in IDENTITY_FIELDS):
        return existing

    record = dict(existing or {})
    record.update({
        "id": instance_id,
        "content_id": content_id_for(instance_id),
        "desktop_url": desktop_url,
        "clips_dir": clips_dir,
        "tmux_session": tmux_session,
        "created_at": record.get("created_at") or _now(),
    })
    for f in RUNTIME_FIELDS:
        record.setdefault(f, None)
    record["status"] = record.get("status") or "stopped"
    _write_raw(instance_id, record)
    return record


def mark_running(instance_id: str, pid: int, port: int) -> dict:
    """写入运行态。身份层若已存在，一个字段都不碰。

    起来了就意味着人想让它跑——不管这次是人敲的还是守护拉的，都把意愿改回
    running。否则一次关闭会永久压住它，人再敲 up 也起不来。
    """
    record = _read_raw(instance_id) or {}
    now = _now()
    record.update({
        "id": record.get("id") or instance_id,
        "pid": pid,
        "port": port,
        "status": "running",
        "started_at": now,
        "heartbeat_at": now,
        DESIRED_FIELD: DESIRED_RUNNING,
    })
    _write_raw(instance_id, record)
    return record


def set_desired(instance_id: str, desired: str) -> None:
    """记下人希不希望它跑。这条意愿跨进程、跨重启都算数。"""
    if desired not in (DESIRED_RUNNING, DESIRED_STOPPED):
        raise ValueError(f"desired 只能是 running / stopped，收到 {desired!r}")
    record = _read_raw(instance_id) or {"id": instance_id}
    record[DESIRED_FIELD] = desired
    _write_raw(instance_id, record)


def wants_running(instance_id: str = DEFAULT_ID) -> bool:
    """人还想让它跑吗。

    没有这个字段的老记录一律当"想跑"：这些记录建立时还没有关闭意愿这回事，
    把它们默认成"不想跑"会让守护对既有实例集体失效，而那是静默的。
    """
    record = _read_raw(instance_id)
    if not record:
        return False
    return record.get(DESIRED_FIELD, DESIRED_RUNNING) == DESIRED_RUNNING


def touch_heartbeat(instance_id: str) -> None:
    record = _read_raw(instance_id)
    if not record or record.get("status") != "running":
        return
    record["heartbeat_at"] = _now()
    _write_raw(instance_id, record)


def mark_stopped(instance_id: str, owner_pid: int | None = None) -> None:
    """正常退出时调用：只改运行态，**绝不删除文件**。

    身份的载体（桌面页标签、viewer 目录、clips、tmux 会话）都还在，
    删掉记录等于把"存在但没跑"错报成"不存在"。

    owner_pid 是"我是谁"。传了就只在注册表记的确实是我的时候才落笔——
    这道闸拦的是**两个 broker 抢同一个端口**：后起的那个绑不上 8770、当场收尾，
    而它的收尾会把**活着的那个**注销成 stopped。之后 `frago desktop status` 报
    "实例存在但没在运行"，每条指令都被这句话挡掉，而画面其实好端端地在推、
    日志里除了一行 bind 失败什么都没有。2026-08-10 实测踩到。
    """
    record = _read_raw(instance_id)
    if not record:
        return
    if owner_pid is not None and record.get("pid") not in (None, owner_pid):
        return
    record["status"] = "stopped"
    record["pid"] = None
    _write_raw(instance_id, record)


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        # 进程存在但不属于当前用户——存在性判定成立。
        return True


def _port_alive(port: int | None) -> bool:
    if not port:
        return False
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=1).read()
        return True
    except Exception:
        return False


def read_instance(instance_id: str = DEFAULT_ID) -> dict | None:
    """读注册表，顺手用探活纠正 stale 的 running。

    为什么不靠"退出时清理"：进程崩溃（SIGKILL、OOM）与机器重启这两种情况
    根本执行不到退出钩子，指望退出逻辑来维护状态本身就是设计错误。
    真相只能现场探：pid 还在 + 端口 /status 可达，两个信号同时成立才算真的在跑；
    不成立就地把 status 纠正为 stopped 落盘。
    """
    record = _read_raw(instance_id)
    if not record:
        return None
    if record.get("status") != "running":
        return record
    if _pid_alive(record.get("pid")) and _port_alive(record.get("port")):
        return record
    record["status"] = "stopped"
    record["pid"] = None
    _write_raw(instance_id, record)
    return record


def list_instances() -> list[dict]:
    root = _instances_dir()
    if not root.exists():
        return []
    out = []
    for p in sorted(root.glob("*.json")):
        rec = read_instance(p.stem)
        if rec:
            out.append(rec)
    return out
