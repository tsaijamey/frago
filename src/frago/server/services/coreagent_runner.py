"""把页面上打的一句话交给 CoreAgent，在那一场会话上接着跑。

## 为什么这一家不走另外三家那条路

工作台里的 Claude Code、codex、opencode 都是**交互式命令行程序**：起一个 tmux、把它挂在
那儿，之后每句话 send-keys 进去，上下文一直在它自己的进程里。CoreAgent 不是那样的东西，
它是 frago 自己的 agent 循环——交一件事、跑、给答案。

## 但它有自己的「挂着的 stdin」

内核认 ``--input-format stream-json``：一个进程、一根 stdin，一行一条用户消息，每跑完一轮
交一行 ``result``，第 2 轮起把上下文留在内存里接着说（见 frago-core 的 ``kernel/mod.rs``
那个 ``while`` 循环）。这与 tmux 里那根 stdin 是同一件事的两个外观——区别只在 CoreAgent
没有一块屏。

2026-10-02 实测两条消息喂进一个进程：第 1 轮 ``input_tokens: 7058``，第 2 轮
``input_tokens: 366 / cache_read: 5120``。上下文确实没重放。

所以这一家从「一轮一进程」改成**常驻进程 + 按会话排队**：来了话就入队，喂料线程顺序往
stdin 写，不再当场拒掉第二句。

## 一场会话同一时刻只许一个进程

两个进程对着同一个编号跑，会往同一份记录里交替写行：记录读回来是两轮串在一起的胡话，
而页面上看不出任何异样。常驻之后这条更容易违反——进程活着，更要拦住第二个。所以
:data:`_sessions` 里一场只有一条 :class:`_Session`，它自带锁。

## 不等它跑完

一轮可能跑几分钟。页面要的不是这一轮的返回值——记录流那条路本来就在盯着那份 jsonl，
一行写下去页面就看得见。所以等一个不长的时限，到点还没完就先回「在跑」，队列照常在跑。

分层：服务层。可以 import ``session/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from frago.server.services.ui_session_runner import SessionActivation

logger = logging.getLogger(__name__)

#: 一轮的墙钟上限，交给内核自己收场（它超时会把这件事写进会话记录）。
#: 给得比一次问答宽得多：CoreAgent 在页面上接的多半是「帮我把这件事办完」。
TURN_TIMEOUT_S = 1800.0

#: 等一轮答完最多等多久再先回「在跑」。与另外三家那条路的一轮等待量级一致。
WAIT_S = 180.0

#: 看护线程按这个间隔看一眼：卡住的那一轮该放开了没有、闲够了的进程该收掉了没有。
#: 投喂那条路不等整轮、也不按点轮着看——有话才动，这类按时的活归这里。
_JANITOR_INTERVAL_S = 1.0

#: 叫醒喂料线程的哨子。它平时阻塞在队列上等下一句话；叫停/停机时塞一个进去，让它当场
#: 看见 ``closed`` 退出去，而不是一直挂到进程结束。
_WAKE = object()

#: 闲着多久就把进程收掉（秒）。保它的全部价值是省掉下一轮的历史重放；一轮重放几秒到
#: 几十秒，而闲置进程占的是内存。20 分钟是「问完一句、去别处转一圈回来接着问」的典型
#: 间隔，与 PA 那套的活跃窗口（15 分钟）同一量级、略宽。
IDLE_EVICT_S = 1200.0

#: 一场会话最多排多少句。超了当场拒，**不丢最旧的**——丢最旧等于静默吃掉人已经打出去的
#: 话，而人以为发出去了，这跟本模块要解决的问题是同一类伤害。
QUEUE_MAX = 32

#: 关掉 stdin 之后等内核自己收场的时间。实测它读到 EOF 就干净退出（exit_code 0），
#: 通常远快于此；这个是兜底，超了就补一刀。
_REAP_GRACE_S = 10.0

#: 人按下叫停之后，等内核自己把手上这一轮收掉的时间。比 :data:`_REAP_GRACE_S` 短得多：
#: 空闲回收是在没人等的时候慢慢等，叫停是人等不下去了才按的。
_STOP_GRACE_S = 5.0

#: 关 stdin 等不到、送了 SIGTERM 之后，再等这么久。还不动才补 SIGKILL。
#:
#: 这两级不是走过场：SIGKILL 之下内核没有任何收尾的机会，它正跑着的那条命令会被 init
#: 收养、接着跑（本机实测：叫停两次，留下两对还在睡的进程），而人按下停止的意思正是
#: 「别再动了」。先给一个能被捕到的信号，那一边就有机会把手上的活收掉。
_TERM_GRACE_S = 3.0


class CoreAgentBusy(RuntimeError):
    """这一场现在收不下这句话：队列排满了。

    单立一档：让它落进通用的 500，页面上只剩一句「没发出去」，人会以为出了故障，而实际
    只需要等它答完。**排队本身不再抛这个**——改前它是「这一场在跑」的常态回应，现在只有
    排满才抛。
    """


class CoreAgentUnavailable(RuntimeError):
    """内核不在，或者它一上来就起不来（多半是没给 CoreAgent 配连接）。"""


@dataclass
class _Session:
    """一场会话的常驻进程与待办队列。

    状态只有四种：``absent``（没进程）、``starting``（进程起了、还没跑完第一轮）、
    ``idle``（跑完了，等下一行）、``busy``（当前轮在跑）。``lock`` 串起所有状态迁移——
    本模块被多个页面线程、一个喂料线程、一个读线程同时碰。
    """

    session_id: str
    cwd: str
    title: str | None = None
    state: str = "absent"
    proc: subprocess.Popen | None = None
    pending: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=QUEUE_MAX))
    #: 最近一轮的结论，供 ``send`` 在等到的情形下直接交出。
    last_result: dict[str, object] = field(default_factory=dict)
    #: 最近一次有动静的时刻，空闲回收据此判。
    touched_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)
    feeder: threading.Thread | None = None
    reader: threading.Thread | None = None
    #: 按点看一眼的那条：卡住的一轮放开、闲够了的进程回收。与投喂分开，投喂只「有话才动」。
    janitor: threading.Thread | None = None
    #: 这一轮的交卷信号：喂料线程写出一行后清掉，读线程收到 result 后置上。
    turn_done: threading.Event = field(default_factory=threading.Event)
    #: 自上一次交卷以来写进 stdin 的条数。喂料线程不再等整轮，写出去的话可能还在内核
    #: 手里没被读到；叫停时要把它们一并算作作废，不然「人刚发的话不见了」在返回值里
    #: 一个数都没有。每收到一条 result 归零，所以不会越攒越多。
    in_flight: int = 0
    #: 这一场被叫停了（或服务要停了）。置上之后喂料线程不再往下走，自己退出去。
    closed: bool = False


_sessions: dict[str, _Session] = {}
_sessions_lock = threading.Lock()


def _session_for(session_id: str, cwd: str, title: str | None) -> _Session:
    """取这一场的常驻条目，没有就建一个（此时还没起进程）。"""
    with _sessions_lock:
        got = _sessions.get(session_id)
        if got is None:
            got = _Session(session_id=session_id, cwd=cwd, title=title)
            _sessions[session_id] = got
        else:
            got.cwd = cwd
            if title:
                got.title = title
        return got


def running(session_id: str) -> bool:
    """这一场现在有没有活进程（含正在起、正在跑）。

    语义与改前一致：改前是「这一场有进程在跑」，现在是「这一场有常驻进程」。``busy``
    不再等于「发不进去」——那是 :func:`queued_count` 与队列上限管的事。
    """
    with _sessions_lock:
        got = _sessions.get(session_id)
    return got is not None and got.state != "absent"


def live_states() -> dict[str, bool]:
    """此刻还开着的每一场 → 它是不是正在跑某一轮。

    「有没有常驻进程」与「忙不忙」是两回事：跑完了等下一句话的那些也还开着，但它们是
    闲着，不是在干活。看护那条路要分清楚——一场等人打字的会话静上半个钟头是正常的，
    一场正在跑却半个钟头没有新记录的才是卡住了。

    一次给全而不是逐场问：看护一趟要过上百张卡片，逐场问就要逐场拿一次锁。
    """
    with _sessions_lock:
        return {
            sid: sess.state == "busy"
            for sid, sess in _sessions.items()
            if sess.state != "absent"
        }


def busy(session_id: str) -> bool:
    """这一场此刻是不是正在跑某一轮。

    与「有没有常驻进程」是两回事：跑完了等下一句话的那些也还开着，但它们在等人，
    不是在干活。
    """
    return live_states().get(session_id, False)


def queued_count(session_id: str) -> int:
    """这一场还排着几句话说出去。"""
    with _sessions_lock:
        got = _sessions.get(session_id)
    return 0 if got is None else got.pending.qsize()


def new_session_id() -> str:
    """现发一个 CoreAgent 会话编号。

    ``core_`` 前缀是会话页认出"这一场属于 CoreAgent"的唯一判据（内核那边生成编号时
    写的也是它）。发起方自己发编号，才能在会话跑起来之前就把它归好组、记进执行记录。
    """
    return f"core_{uuid.uuid4().hex}"


def start_local_ops(title: str) -> str:
    """给 frago 自己要起的一场 CoreAgent 会话备好编号，并归到「本机管理」那一组。

    定时任务、待办拟稿、外部命令审计都从这里拿编号。两件事在这里一起做完，是因为它们
    在别处一起漏掉过：编号不自己发，这一场就只能叫开口第一句——那是一整段说明书，二十
    场长得一模一样；不归组，它们就堆在左栏未分组区，把人自己那几场埋掉。

    归组失败只记一句日志：归类不成是左栏难看，而让一次定时任务因此不跑是另一个量级的事。

    **名字要调用方自己交给内核**（拼命令时带上 ``--title``）：这几处各自拼自己那条命令，
    这里拿到名字只为写进日志，好在日志里对上号。走 :func:`send` 的那条路把名字直接交给它。
    """
    session_id = new_session_id()
    try:
        from frago.server.services import workbench_groups

        workbench_groups.file_under(
            session_id,
            workbench_groups.LOCAL_OPS_TAG,
            key=workbench_groups.LOCAL_OPS_KEY,
        )
    except Exception:  # noqa: BLE001 — 归组不成不该把任务本身拦下
        logger.warning("把 %s 归到「本机管理」组时出错", session_id, exc_info=True)
    logger.info("coreagent local-ops session %s（%s）", session_id, title)
    return session_id


def binary() -> Path:
    """内核二进制在哪。跟 hook 引擎是同一个文件，不带 ``--engine`` 就是内核。"""
    from frago.init.hook_binary import get_binary_name, get_hook_deploy_dir

    path = get_hook_deploy_dir() / get_binary_name()
    if not path.exists():
        raise CoreAgentUnavailable(
            "frago 的内核还没装好（~/.frago/bin 下找不到），跑一次 frago init 补上"
        )
    return path


def build_command(
    session_id: str,
    *,
    cwd: str,
    title: str | None = None,
) -> list[str]:
    """起这一场的常驻进程时交给内核的那条命令。

    ``--input-format stream-json`` 是常驻的全部：任务从 stdin 一行一条来，一个进程跑很多
    轮，第 2 轮起读回记忆。**不传 ``--prompt``**（那是一次一进程的写法）；内核那边
    ``--input-format stream-json`` 强制要配 ``--output-format stream-json``，所以两个都在。

    ``--session-id`` 是续接：编号指向的记录已经存在时，内核先把那一场读回来；记录不存在
    时它新建这一场。所以「刚建的会话」与「进程被回收后重来」共用这一条路径，不必先探记录
    在不在。

    工具不加限制——人在页面上跟自己的 agent 说话，与在终端里跑 ``frago-core`` 是同一件
    事，而每一步仍然要过 frago 的规则闸（内核自己在 PreToolUse 那一刻问规则引擎）。
    """
    cmd = [
        str(binary()),
        "--mode", "agent",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--session-id", session_id,
        "--cwd", cwd,
    ]
    if title:
        cmd += ["--title", title]
    return cmd


def _user_line(prompt: str) -> str:
    """一行用户消息，照 Claude Code 的 ``stream-json`` 形状。"""
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": prompt}},
        ensure_ascii=False,
    )


def _spawn(sess: _Session) -> None:
    """起这一场的常驻进程并挂上两个线程。调用方持有 ``sess.lock``。"""
    from frago.server.services.subprocess_utils import get_utf8_env

    cmd = build_command(sess.session_id, cwd=sess.cwd, title=sess.title)
    sess.proc = subprocess.Popen(  # noqa: S603 — 命令由本模块拼，无 shell
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,  # 内核的进度话走 stderr，这里不读、别把管道塞满
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=sess.cwd,
        env=get_utf8_env(),
        bufsize=1,  # 行缓冲：一轮的 result 立刻读得到，不等它攒满
    )
    sess.state = "starting"
    sess.turn_done.clear()
    sess.reader = threading.Thread(
        target=_read_loop, args=(sess,), name=f"coreagent-read-{sess.session_id[:16]}", daemon=True
    )
    sess.feeder = threading.Thread(
        target=_feed_loop, args=(sess,), name=f"coreagent-feed-{sess.session_id[:16]}", daemon=True
    )
    sess.janitor = threading.Thread(
        target=_janitor_loop, args=(sess,), name=f"coreagent-jan-{sess.session_id[:16]}", daemon=True
    )
    sess.reader.start()
    sess.feeder.start()
    sess.janitor.start()
    logger.info("coreagent 常驻进程起来了（session=%s pid=%s）", sess.session_id, sess.proc.pid)


def _reclaim(sess: _Session) -> None:
    """收掉这一场的进程。调用方持有 ``sess.lock``。

    回收动作就是**关 stdin**：实测内核读到 EOF 自己收场退出（``next_stream_message``
    返回 ``None`` → 循环结束），干净退出，不需要信号。等一小会儿退不掉才动硬的。
    """
    proc = sess.proc
    sess.proc = None
    sess.state = "absent"
    if proc is None:
        return
    _let_it_go(proc, _REAP_GRACE_S, "空闲回收")


def _let_it_go(proc: subprocess.Popen, grace: float, what: str) -> None:
    """关 stdin → 等 ``grace`` → SIGTERM → 等一小会儿 → SIGKILL。

    关 stdin 这一下同时是「礼」和「实活」：内核读到 EOF 会先把手上的活收掉——正在跑的那条
    命令连进程组一起终止（见 frago-core 的 ``tools::kill_live_groups``），然后这一轮结束、
    进程干净退出。这条路走通了就一步也用不着信号。

    走不通才动硬的，且**先 SIGTERM 后 SIGKILL**：SIGKILL 捕不住，内核来不及收它拉起的命令，
    那些命令会被 init 收养、接着跑。收不干净只记一句日志，NEVER 把它带的这件事本身带崩。
    """
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    except Exception:  # noqa: BLE001 — 关不成 stdin 也还有下面两级
        logger.warning("%s：关 coreagent 的 stdin 时出错（pid=%s）", what, proc.pid, exc_info=True)
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        logger.info("%s：关 stdin 后 %ss 没退，先送 SIGTERM（pid=%s）", what, grace, proc.pid)
    except Exception:  # noqa: BLE001
        logger.warning("%s：等 coreagent 退出时出错（pid=%s）", what, proc.pid, exc_info=True)
        return
    try:
        proc.terminate()
        proc.wait(timeout=_TERM_GRACE_S)
        return
    except subprocess.TimeoutExpired:
        logger.warning("%s：SIGTERM 之后 %ss 还没退，补一刀（pid=%s）", what, _TERM_GRACE_S, proc.pid)
    except Exception:  # noqa: BLE001
        logger.warning("%s：送 SIGTERM 时出错（pid=%s）", what, proc.pid, exc_info=True)
        return
    try:
        proc.kill()
        proc.wait(timeout=_REAP_GRACE_S)
    except Exception:  # noqa: BLE001
        logger.warning("%s：补刀之后还是收不干净（pid=%s）", what, proc.pid, exc_info=True)


def _read_loop(sess: _Session) -> None:
    """读常驻进程的 stdout：逐行判，每读到一条 ``result`` 就是一轮结论到了。"""
    from frago.server.services.coreagent_output import result_from_line

    proc = sess.proc
    if proc is None or proc.stdout is None:
        return
    try:
        for line in proc.stdout:
            found = result_from_line(line)
            if found is None:
                continue  # system / assistant / hook 回执那些行：与本轮结论无关
            with sess.lock:
                sess.last_result.clear()
                sess.last_result.update(found)
                sess.touched_at = time.time()
                sess.in_flight = 0  # 这一轮交卷了，写在它名下的那些话都有了下落
                if sess.state == "busy":
                    sess.state = "idle"
            sess.turn_done.set()
    except Exception:  # noqa: BLE001 — 读线程崩了不该静默
        logger.warning("读 coreagent stdout 时出错（session=%s）", sess.session_id, exc_info=True)
    finally:
        # 进程没了（自己退的、被杀的、收掉的）。把这一场退回 absent，下一句话重新起。
        with sess.lock:
            if sess.proc is proc:
                sess.proc = None
                sess.state = "absent"
        sess.turn_done.set()  # 别让正在等的人一直等下去
        logger.info("coreagent 进程结束了（session=%s）", sess.session_id)


def _feed_loop(sess: _Session) -> None:
    """顺序把队列里的句子写进 stdin，写完就走——不等这一轮跑完。

    从前这里写完要等这一轮的 result 才写下一条：一轮跑多久，后面的话就压多久。CoreAgent
    的一轮可以跑十几分钟，人趁它干活时改主意、追加一句，全被压到整件事做完之后才被读到。
    内核那一侧现在每一轮开跑前都会取一次 stdin（常驻模式的「中途插话」，见 loop.rs 的
    `Interjections`），所以忙的时候写进去的话当轮就接得上。

    串行没变：内核一次只跑一轮，写进去的两句话要么接进同一轮，要么排在下一轮，不并行。
    """
    while True:
        if sess.closed:
            return  # 这一场被叫停了：别再去碰那具已经收掉的进程
        if sess.feeder is not threading.current_thread():
            return  # 这一具进程已经换过喂料线程了（回收后又起了一次），老的退出去
        prompt = sess.pending.get()
        if prompt is _WAKE:
            continue
        _feed_one(sess, prompt)


def _janitor_loop(sess: _Session) -> None:
    """按点看一眼这一场：卡住的那一轮放开，闲够了的进程回收。

    从前这两件事挂在喂料线程「等 queue 超时」上——一轮跑完才轮到看一眼。投喂那条路现在
    纯粹是「有话才动」，这类按时的活另起一条，免得把它拖回轮询。
    """
    while True:
        if sess.closed or sess.janitor is not threading.current_thread():
            return
        time.sleep(_JANITOR_INTERVAL_S)
        _sweep(sess)


def _wake_feeder(sess: _Session) -> None:
    """把可能正阻塞在队列上的喂料线程叫醒，让它看见 ``closed`` 自己退出。

    叫停与停机都要叫一声，否则那条线程会一直挂在队列上，直到这个进程结束。
    """
    # 队满说明它有话要处理，醒了自然会看见 closed，叫停本身不该为这个失败。
    with contextlib.suppress(queue.Full):
        sess.pending.put_nowait(_WAKE)


def _sweep(sess: _Session) -> None:
    """闲着的时候过一遍：卡住的那一轮放开，闲够了的进程回收。

    从前这两件事都挂在喂料线程「等 queue 超时」上——一轮跑完才轮到看一眼，卡住的那一轮
    要等满 ``TURN_TIMEOUT_S`` 才被发现。现在归看护线程按固定的间隔看，投喂那条路只负责
    有话就写。
    """
    now = time.time()
    with sess.lock:
        if sess.pending.qsize() > 0:
            return  # 刚有新话：马上就去取，不在这儿动状态
        if sess.state == "busy":
            if now - sess.touched_at <= TURN_TIMEOUT_S:
                return
            # 一轮跑得太久还没交卷：别把这一场锁死，让下一句还能发。
            logger.warning("这一轮等不到结论，按超时处理（session=%s）", sess.session_id)
            sess.state = "idle"
            sess.turn_done.set()
            return
        if sess.state != "idle" or now - sess.touched_at <= IDLE_EVICT_S:
            return
        # 闲够久了：把进程收掉，这一场退回 absent。下次来话重新起、重放一次历史。
        logger.info("coreagent 空闲回收（session=%s）", sess.session_id)
        _reclaim(sess)


def _feed_one(sess: _Session, prompt: str) -> None:
    """把这一句写进那一场的 stdin。写不进去就放回队列，交给下一趟。"""
    # 写之前再取一次锁：进程可能在上一步和这一步之间没了。
    with sess.lock:
        proc = sess.proc
        if proc is None or proc.stdin is None or proc.stdin.closed:
            # 进程这一会儿没了（崩溃、被外部杀掉、刚被回收）。这一句不能吞：
            # 放回队列，让下一轮重新起进程时先处理它。
            logger.warning("这一场没有活进程，把这句话放回队列（session=%s）", sess.session_id)
            sess.pending.put(prompt)
            time.sleep(1.0)
            return
        if sess.state != "busy":
            # 这一场正闲着：这一句开新一轮，状态与交卷标志都归它。已经忙着的就只是往里
            # 递一句——那一轮的交卷标志照旧归它自己，别被人递话这件事清掉。
            sess.state = "busy"
            sess.turn_done.clear()
        sess.touched_at = time.time()
        try:
            proc.stdin.write(_user_line(prompt) + "\n")
            proc.stdin.flush()
            sess.in_flight += 1
        except (BrokenPipeError, ValueError, OSError):
            logger.warning("往这一场写话失败，进程多半已经没了（session=%s）", sess.session_id)
            sess.pending.put(prompt)
            _reclaim(sess)


def _enqueue(sess: _Session, prompt: str) -> None:
    """把一句话排进这一场。满了就当场拒——唯一该拦下的情形。"""
    try:
        sess.pending.put_nowait(prompt)
    except queue.Full:
        raise CoreAgentBusy(
            f"这一场排了 {QUEUE_MAX} 句还没轮到，等它答完再说（排满时当场拒绝，"
            "不丢你已经发出去的话）"
        ) from None
    sess.touched_at = time.time()
    with sess.lock:
        if sess.proc is None:
            _spawn(sess)


def _wait_for_turn(sess: _Session, wait_s: float) -> dict[str, object]:
    """等这一轮出结论，最多等 ``wait_s``。到时还没完就交出眼下这份（多半是空的）。"""
    deadline = time.time() + wait_s
    while time.time() < deadline:
        with sess.lock:
            state = sess.state
            got = dict(sess.last_result)
        if got and state in ("idle", "absent"):
            return got
        if state == "absent" and sess.pending.qsize() == 0:
            return {}  # 进程没了、也没有下一句在跑：等下去不会有结论
        time.sleep(0.1)
    with sess.lock:
        return dict(sess.last_result)


def send(
    session_id: str,
    prompt: str,
    *,
    cwd: str,
    title: str | None = None,
    wait_s: float = WAIT_S,
) -> SessionActivation:
    """把这句话排给这一场，最多等 ``wait_s``，到点先回「在跑」。

    排满（:class:`CoreAgentBusy`）当场抛出——这是唯一该拦下的情形。等到了而这一轮是失败
    收场，抛 :class:`CoreAgentUnavailable`：失败得早的那几种（没配连接、内核不在）压根没在
    会话记录里留下任何一行，页面上除了这句抛出来的话没有别的线索。等不到就只记日志：那时
    记录里已经有行在写了，人看得见。
    """
    sess = _session_for(session_id, cwd, title)
    _enqueue(sess, prompt)
    got = _wait_for_turn(sess, wait_s)
    if not got:
        logger.info("coreagent turn still running after %ss (session=%s)", wait_s, session_id)
        return SessionActivation(session_id=session_id, status="activating", text="")
    error = got.get("error")
    if error:
        raise CoreAgentUnavailable(str(error))
    return SessionActivation(
        session_id=session_id, status="activating", text=str(got.get("text") or "")
    )


def send_queued(
    session_id: str,
    prompt: str,
    *,
    cwd: str,
    title: str | None = None,
) -> str:
    """同 :func:`send`，但一步都不等：排上就返回，投喂在后台做。

    排满仍当场抛 :class:`CoreAgentBusy`——「收不下」必须当场回给页面，NEVER 收下再在后台
    静默地把它丢掉。返回喂料线程名，便于日志对号。
    """
    sess = _session_for(session_id, cwd, title)
    _enqueue(sess, prompt)
    return sess.feeder.name if sess.feeder else f"coreagent-queue-{session_id[:16]}"


def _terminate(proc: subprocess.Popen) -> None:
    """关 stdin 让内核自己收场，等不到再一级一级动硬的（见 :func:`_let_it_go`）。"""
    _let_it_go(proc, _STOP_GRACE_S, "叫停")


def _drain_pending(sess: _Session) -> None:
    """排着还没轮到的话一并作废——这一场已经停了，那些话没有下一轮可等。"""
    dropped = 0
    while True:
        try:
            sess.pending.get_nowait()
            dropped += 1
        except queue.Empty:
            break
    if dropped:
        logger.info("叫停时丢掉这一场排队中的 %d 句话（session=%s）", dropped, sess.session_id)


def _note_stopped(session_id: str, cwd: str, by: str, busy: bool, dropped: int) -> None:
    """往会话记录里补一行：这一场是被人停的，顺带说清丢了几句话。

    不补这一行，翻记录的人看到的只有半截对话突然断掉，分不清是被人停的、自己崩的，
    还是撞了时限——三种的下一步处置完全不同。排队中那些没轮到的话一并作废，也得写进
    来：人刚发出去的话不见了，记录里一个字的交代都没有，是最难查的那种「静默丢失」。
    补不上只记日志，NEVER 让它把叫停带崩。
    """
    from frago.session import coreagent_store

    try:
        path = coreagent_store.find_session_file(session_id)
        if path is None:
            return
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        what = "正在跑的那一轮当场终止，这一轮没有结论" if busy else "当时没有在跑的一轮"
        if dropped:
            what += f"；另有 {dropped} 句话还没轮到就一并作废了，要说得重新发"
        row = {
            "type": "system",
            "subtype": "informational",
            "level": "warning",
            "isMeta": True,
            "content": f"这一场由{by}在 {when} 停下：{what}。",
            "sessionId": session_id,
            "cwd": cwd,
            "timestamp": when,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("往会话记录里写「被停」那一行失败（session=%s）", session_id, exc_info=True)


def stop(session_id: str, *, by: str = "页面上的人") -> dict[str, object]:
    """把这一场正在跑的那一轮当场停下。

    与空闲回收（:func:`_reclaim`）不是一回事：回收是关掉 stdin、等内核把手上一轮跑完再
    退，对「正在跑的一轮」等于没停——那一轮可能还要跑几十分钟，而人按这个按钮正是因为
    等不下去了。所以这里关掉 stdin 只等一小会儿（能自己干净收场最好），还不退就补一刀。

    停完把这一场从册子上摘掉、排队的句子作废，并往会话记录里补一行说明是谁停的。
    返回值只说这一场停之前是什么样，页面据此说话。

    在此之前页面上那个「关闭运行」只认 tmux 会话，而 CoreAgent 不跑在 tmux 里——按下去
    服务端回一句「这一场此刻没有在跑的会话」，实际什么都没停。
    """
    with _sessions_lock:
        sess = _sessions.pop(session_id, None)
    if sess is None:
        return {"running": False, "stopped": False, "busy": False, "dropped": 0}

    with sess.lock:
        busy = sess.state == "busy"
        proc = sess.proc
        sess.proc = None
        sess.state = "absent"
        sess.closed = True
        # 作废的话分两处：还在上边排队没轮到的，加上已经写进 stdin、内核还没读到就没了
        # 的（正在跑的那一轮本身不算，它由「当场终止」那句交代）。
        queued = sess.pending.qsize() + max(0, sess.in_flight - 1)
        sess.in_flight = 0
        if proc is not None:
            _terminate(proc)
        _drain_pending(sess)
        _wake_feeder(sess)  # 让挂在队列上的喂料线程看见 closed，自己退出去
        sess.turn_done.set()  # 正在等这一轮的人别再等下去
        cwd = sess.cwd

    if proc is not None:
        _note_stopped(session_id, cwd, by, busy, queued)
    logger.info("coreagent 叫停（session=%s busy=%s pid=%s）", session_id, busy, getattr(proc, "pid", None))
    return {"running": proc is not None, "stopped": proc is not None, "busy": busy, "dropped": queued}


def shutdown() -> None:
    """把全部常驻进程收掉（server 停机用）。"""
    with _sessions_lock:
        all_sessions = list(_sessions.values())
        _sessions.clear()
    for sess in all_sessions:
        with sess.lock:
            sess.closed = True
            _wake_feeder(sess)
            _reclaim(sess)
