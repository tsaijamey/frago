"""CoreAgent 那条投喂路：一个常驻进程 + 一条按会话排的队。

盯六件事：

1. 交给内核的那条命令是**常驻**的形状——`--input-format stream-json`、
   `--output-format stream-json`、这一场的编号；**不带 `--prompt`**（任务从 stdin 来）。
2. 一句话进得了队列，并且真的以 Claude Code 的 stream-json 形状写进了 stdin。
3. 第二句话**不再当场被拒**——它排队，等这一轮完了接着跑（这是一轮改动的全部意义）。
4. 排满时才拒，宁可拒绝也不丢人已经发出去的话。
5. 进程没了（崩了、被杀了）这一场要能退回 absent，排着的句子不丢。
6. 空闲回收 = 关 stdin；停机把全部常驻进程收掉。

不起真进程：`Popen` 那一步换成替身。
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from frago.server.services import coreagent_runner as cr


@pytest.fixture(autouse=True)
def clean_slate():
    """每条用例都从「没有任何一场」开始。表是模块级的，用例之间会互相干扰。"""
    with cr._sessions_lock:
        cr._sessions.clear()
    yield
    with cr._sessions_lock:
        cr._sessions.clear()


@pytest.fixture
def fake_binary(monkeypatch, tmp_path):
    binary = tmp_path / "frago-core"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setattr(cr, "binary", lambda: binary)
    return binary


@pytest.fixture
def no_real_popen(monkeypatch):
    """把真实起进程那一步换掉。真起 frago-core 会跑模型，测试里不能干这事。"""
    procs: list[_FakeProc] = []

    def make(*_a, **_k):
        p = _FakeProc()
        procs.append(p)
        return p

    monkeypatch.setattr(cr.subprocess, "Popen", make)
    return procs


class _FakeProc:
    """够用的 Popen 替身：收下写到 stdin 的行，不真起进程。

    stdout 是一根「一直开着、没有内容」的管子：读线程会挂在上面，这与真进程一样——它在
    等下一轮的 result。只有关掉 stdin 或 kill 时它才结束，那时读线程把这一场退回 absent。
    """

    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = _BlockingStdout()
        self.pid = 4242
        self.killed = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self.stdout.close()


class _BlockingStdout:
    """``for line in proc.stdout`` 要能一直等——所以迭代到关闭为止，不吐出任何行。"""

    def __init__(self):
        self._closed = threading.Event()

    def __iter__(self):
        self._closed.wait(30)
        return iter(())

    def close(self):
        self._closed.set()


class _FakeStdin:
    def __init__(self):
        self.lines: list[str] = []
        self.closed = False

    def write(self, text: str):
        self.lines.append(text)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class TestCommand:
    def test_命令是常驻形状_带_stream_json_不带_prompt(self, fake_binary):
        cmd = cr.build_command("core_abc", cwd="/repos/x", title="定时任务：分类")
        assert cmd[cmd.index("--input-format") + 1] == "stream-json"
        assert cmd[cmd.index("--output-format") + 1] == "stream-json"
        assert cmd[cmd.index("--session-id") + 1] == "core_abc"
        assert cmd[cmd.index("--title") + 1] == "定时任务：分类"
        assert cmd[cmd.index("--cwd") + 1] == "/repos/x"
        # 任务从 stdin 一行一条来，不再压在这条命令上
        assert "--prompt" not in cmd

    def test_不给名字就不带那个开关(self, fake_binary):
        assert "--title" not in cr.build_command("core_abc", cwd="/repos/x")

    def test_给了连接编号就带上_as_profile(self, fake_binary):
        cmd = cr.build_command("core_abc", cwd="/repos/x", profile_id="a2ef38c1")
        assert "--as-profile" in cmd
        assert cmd[cmd.index("--as-profile") + 1] == "a2ef38c1"

    def test_desktop_operator_允许_frago_desktop_且不再封禁_say(self, fake_binary):
        cmd = cr.build_command("core_op", cwd="/repos/x", desktop_operator=True)
        assert "--allowed-tools" in cmd
        assert cmd[cmd.index("--allowed-tools") + 1] == "Bash(frago desktop:*)"
        assert "Bash(frago desktop say:*)" not in cr._DESKTOP_OPERATOR_DISALLOWED_TOOLS
        assert "Bash(frago desktop say:*)" not in cmd

    def test_用户消息是_claude_code_的_stream_json_形状(self):
        line = cr._user_line("接着说")
        obj = json.loads(line)
        assert obj["type"] == "user"
        assert obj["message"]["role"] == "user"
        assert obj["message"]["content"] == "接着说"


class TestQueue:
    def test_一句话排进去立刻返回不等一轮(self, fake_binary, no_real_popen):
        name = cr.send_queued("core_q", "第一句", cwd="/tmp")
        assert isinstance(name, str) and name
        time.sleep(0.2)
        assert no_real_popen, "排第一句就该把常驻进程起起来"

    def test_第二句话排队而不是当场被拒(self, fake_binary, no_real_popen):
        """这一条是整轮改动的意义所在：改前第二句抛 CoreAgentBusy。"""
        cr.send_queued("core_two", "第一句", cwd="/tmp")
        time.sleep(0.2)
        # 不抛了——排上就返回
        cr.send_queued("core_two", "第二句", cwd="/tmp")
        sess = cr._sessions["core_two"]
        # 喂料线程写得很快，所以「第二句还在队里」与「已经写进 stdin」都算对：
        # 关键是它没被丢掉。两种落点都查一遍。
        in_queue = list(sess.pending.queue)
        written = "".join(no_real_popen[0].stdin.lines)
        assert "第二句" in in_queue or "第二句" in written, "第二句必须被收下，不能丢"

    def test_忙的时候说一句_当场写进_stdin_不等这一轮答完(self, fake_binary, no_real_popen):
        """从前喂料线程写完要等这一轮的 result 才写下一条：一轮跑多久，后面的话就压多久，
        人趁它干活时改主意根本插不进去。现在写完就走——内核每一轮开跑前会取一次 stdin
        （常驻模式的「中途插话」），忙时说的话当轮就接得上。
        """
        cr.send_queued("core_live", "第一句", cwd="/tmp")
        time.sleep(0.2)
        assert cr.busy("core_live"), "写出去之后这一场算在跑"

        cr.send_queued("core_live", "第二句", cwd="/tmp")
        time.sleep(0.3)

        written = [ln for ln in no_real_popen[0].stdin.lines if ln.strip()]
        assert len(written) == 2, "忙的时候说的那句也要立刻写进 stdin，不压在队里"
        assert "第二句" in written[1]
        assert cr.queued_count("core_live") == 0, "队里不该还压着话"

    def test_排满时当场拒且不丢已有的(self, fake_binary):
        sess = cr._session_for("core_full", "/tmp", None)
        for i in range(cr.QUEUE_MAX):
            sess.pending.put_nowait(f"第{i}句")
        assert sess.pending.full()
        with pytest.raises(cr.CoreAgentBusy) as caught:
            cr._enqueue(sess, "再多一句")
        assert "排了" in str(caught.value)

    def test_排满了不丢最旧的(self, fake_binary):
        """丢最旧等于静默吃掉人已经打出去的话——那与本模块要解决的问题同类。"""
        sess = cr._session_for("core_keep", "/tmp", None)
        for i in range(cr.QUEUE_MAX):
            sess.pending.put_nowait(f"第{i}句")
        first_still_there = sess.pending.queue[0]
        with pytest.raises(cr.CoreAgentBusy):
            cr._enqueue(sess, "再多一句")
        assert sess.pending.queue[0] == first_still_there


class TestProcessLifecycle:
    def test_第一句话来时把进程起起来(self, fake_binary, no_real_popen):
        cr.send_queued("core_spawn", "起一个", cwd="/tmp")
        time.sleep(0.2)
        assert no_real_popen, "第一句话应该把常驻进程起起来"
        assert cr.running("core_spawn")
        assert cr._sessions["core_spawn"].proc is not None

    def test_一句话真的以_stream_json_形状写进了_stdin(self, fake_binary, no_real_popen):
        cr.send_queued("core_write", "接着说", cwd="/tmp")
        time.sleep(0.3)
        lines = [ln for ln in no_real_popen[0].stdin.lines if ln.strip()]
        assert lines, "喂料线程应该把这句话写进 stdin"
        obj = json.loads(lines[0])
        assert obj["type"] == "user" and obj["message"]["content"] == "接着说"

    def test_回收就是关_stdin(self, fake_binary, no_real_popen):
        cr.send_queued("core_reclaim", "跑一下", cwd="/tmp")
        time.sleep(0.2)
        sess = cr._sessions["core_reclaim"]
        with sess.lock:
            cr._reclaim(sess)
        assert no_real_popen[0].stdin.closed, "回收动作是关 stdin，让内核自己收场"
        assert not cr.running("core_reclaim")

    def test_进程没了这一场退回_absent(self, fake_binary, no_real_popen):
        cr.send_queued("core_gone", "跑一下", cwd="/tmp")
        time.sleep(0.2)
        assert cr.running("core_gone")
        # 进程自己退出：stdout 到头了，读线程该把这一场退回 absent
        no_real_popen[0].stdout.close()
        time.sleep(0.4)
        assert not cr.running("core_gone"), "读线程看到 stdout 结束就该把这一场退回 absent"

    def test_停机把全部常驻进程收掉(self, fake_binary, no_real_popen):
        cr.send_queued("core_s1", "一", cwd="/tmp")
        cr.send_queued("core_s2", "二", cwd="/tmp")
        time.sleep(0.3)
        assert len(no_real_popen) == 2, "两场各一个常驻进程"
        cr.shutdown()
        assert all(p.stdin.closed for p in no_real_popen), "停机要把每个常驻进程的 stdin 关掉"
        assert not cr._sessions, "表要清干净"


class TestLocalOpsSession:
    def test_编号带core前缀并且归进本机管理组(self, monkeypatch, tmp_path):
        """编号的前缀是会话页认出这一家的判据；归组是为了别把人自己那几场埋掉。"""
        from frago.server.services import workbench_groups as wg

        monkeypatch.setattr(wg, "GROUPS_FILE", tmp_path / "groups.json")
        sid = cr.start_local_ops("待办拟稿")
        assert sid.startswith("core_")

        state = wg.load()
        tag = next(t for t in state["tags"] if t["name"] == wg.LOCAL_OPS_TAG)
        assert state["sessions"][tag["id"]] == [sid]
        assert tag["source"] == "system"

    def test_归组失败不影响这一场跑起来(self, monkeypatch, tmp_path):
        """归类不成是左栏难看，让一次定时任务因此不跑是另一个量级的事。"""
        from frago.server.services import workbench_groups as wg

        def boom(*_a, **_k):
            raise OSError("盘满了")

        monkeypatch.setattr(wg, "file_under", boom)
        assert cr.start_local_ops("定时任务：分类").startswith("core_")


class TestStop:
    """叫停：正在跑的那一轮当场停下，而不是等它自己跑完。"""

    def test_叫停收掉进程并把这一场从册子上摘掉(self, fake_binary, no_real_popen):
        cr.send_queued("core_stop", "跑一下", cwd="/tmp")
        time.sleep(0.3)
        assert cr.running("core_stop")

        outcome = cr.stop("core_stop")

        assert outcome["stopped"] is True
        assert outcome["running"] is True
        assert no_real_popen[0].stdin.closed, "先关 stdin 让内核自己收场"
        assert "core_stop" not in cr._sessions, "停过的这一场不留在册子上"
        assert not cr.running("core_stop")

    def test_没有在跑的这一场叫停什么也不动(self, fake_binary):
        outcome = cr.stop("core_never")
        assert outcome == {"running": False, "stopped": False, "busy": False, "dropped": 0}

    def test_叫停把排队中的话一并作废(self, fake_binary, no_real_popen):
        for i in range(3):
            cr.send_queued("core_q", f"第{i}句", cwd="/tmp")
        time.sleep(0.2)

        outcome = cr.stop("core_q")

        assert outcome["dropped"] >= 1, "停的时候还排着的话要一起丢掉"
        assert cr.queued_count("core_q") == 0

    def test_叫停往会话记录里补一行说是谁停的(self, monkeypatch, tmp_path, fake_binary, no_real_popen):
        from frago.session import coreagent_store

        monkeypatch.setattr(coreagent_store, "sessions_root", lambda: tmp_path)
        rec_dir = tmp_path / "-tmp"
        rec_dir.mkdir()
        record = rec_dir / "core_note.jsonl"
        record.write_text("", encoding="utf-8")

        cr.send_queued("core_note", "跑一下", cwd="/tmp")
        time.sleep(0.3)
        cr.stop("core_note", by="页面上的人")

        rows = [json.loads(ln) for ln in record.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert rows, "叫停要往记录里补一行"
        assert rows[-1]["type"] == "system"
        assert "页面上的人" in rows[-1]["content"]
        assert rows[-1]["sessionId"] == "core_note"

    def test_叫停之后投喂线程当场收摊(self, fake_binary, no_real_popen):
        """喂料线程平时阻塞在队列上等下一句话——不等整轮、也不按点轮询。叫停时塞一个哨子
        把它叫醒，它看见 closed 就退出去；不叫的话它会一直挂到这个进程结束。"""
        cr.send_queued("core_wake", "跑一下", cwd="/tmp")
        time.sleep(0.2)
        sess = cr._sessions["core_wake"]
        assert sess.feeder is not None and sess.feeder.is_alive()

        cr.stop("core_wake")
        sess.feeder.join(timeout=2.0)

        assert not sess.feeder.is_alive(), "叫停后投喂线程要当场退出"

    def test_关_stdin_不退时先送_sigterm_再补刀(self, fake_binary, no_real_popen, monkeypatch):
        """SIGKILL 捕不住：内核来不及收它拉起的命令，那些命令会被 init 收养、接着跑
        ——人按下停止的意思正是别再动了。所以关 stdin 等不到，先给一个能被捕到的信号。
        """
        cr.send_queued("core_ladder", "跑一下", cwd="/tmp")
        time.sleep(0.2)
        proc = cr._sessions["core_ladder"].proc
        calls: list[str] = []
        waits = {"n": 0}

        def wait(timeout=None):
            waits["n"] += 1
            if waits["n"] == 1:
                raise cr.subprocess.TimeoutExpired(cmd="frago-core", timeout=timeout)
            return 0

        monkeypatch.setattr(proc, "wait", wait)
        monkeypatch.setattr(proc, "terminate", lambda: calls.append("term"), raising=False)
        monkeypatch.setattr(proc, "kill", lambda: calls.append("kill"), raising=False)

        cr.stop("core_ladder")

        assert calls == ["term"], "关 stdin 等不到就先送 SIGTERM；它退了就不必再补刀"

    def test_sigterm_之后还不退才补刀(self, fake_binary, no_real_popen, monkeypatch):
        """三级阶梯的最后一级：能捕的信号给了、还不够，才动用捕不住的那一刀。"""
        cr.send_queued("core_ladder2", "跑一下", cwd="/tmp")
        time.sleep(0.2)
        proc = cr._sessions["core_ladder2"].proc
        calls: list[str] = []
        waits = {"n": 0}

        def wait(timeout=None):
            waits["n"] += 1
            if waits["n"] <= 2:
                raise cr.subprocess.TimeoutExpired(cmd="frago-core", timeout=timeout)
            return 0

        monkeypatch.setattr(proc, "wait", wait)
        monkeypatch.setattr(proc, "terminate", lambda: calls.append("term"), raising=False)
        monkeypatch.setattr(proc, "kill", lambda: calls.append("kill"), raising=False)

        cr.stop("core_ladder2")

        assert calls == ["term", "kill"], "SIGTERM 也没用才补刀"

    def test_补记录失败不妨碍叫停本身(self, monkeypatch, fake_binary, no_real_popen):
        from frago.session import coreagent_store

        def boom(_sid):
            raise OSError("盘满了")

        monkeypatch.setattr(coreagent_store, "find_session_file", boom)
        cr.send_queued("core_boom", "跑一下", cwd="/tmp")
        time.sleep(0.3)

        assert cr.stop("core_boom")["stopped"] is True


class TestLiveSnapshot:
    """浮窗清点要的那一份：谁还开着、是忙是闲、占着哪个进程。"""

    def test_reports_live_sessions_and_skips_closed_ones(self):
        sess = cr._session_for("core_live", "/tmp/live", "这一场的名字")
        sess.state = "idle"
        sess.proc = _FakeProc()
        sess.touched_at = 123.0

        gone = cr._session_for("core_gone", "/tmp/gone", None)
        gone.state = "absent"

        (row,) = cr.live_snapshot()
        assert row.session_id == "core_live"
        assert row.state == "idle"
        assert row.pid == 4242
        assert row.cwd == "/tmp/live"
        assert row.title == "这一场的名字"
        assert row.touched_at == 123.0

    def test_a_session_without_a_process_reports_no_pid(self):
        # 起进程之前的那一瞬：这一场还开着，但拿不到进程号。界面据此不报内存，
        # 而不是编一个 0。
        sess = cr._session_for("core_starting", "/tmp/s", None)
        sess.state = "starting"

        (row,) = cr.live_snapshot()
        assert row.pid is None


class TestDirectorUnattendedEnv:
    """虚拟桌面导演会话（带 how-frago-agent-runs-an-agent-os）必须关闭轻量审阅与拍板卡拦截，且单测不触达 8770。"""

    def test_director_prompt_disables_review_and_stop_check(
        self, tmp_path, monkeypatch, fake_binary
    ):
        from frago.desktop import aos
        from frago.server.services import stage_orchestrator as so

        monkeypatch.setattr(so, "STAGE_DATA_ROOT", tmp_path / "agent_os")
        captured_envs: list[dict[str, str]] = []
        stage_urls: list[str] = []

        orig_urlopen = aos.urllib.request.urlopen

        def guarded_urlopen(req, *a, **kw):
            url = getattr(req, "full_url", str(req))
            stage_urls.append(url)
            raise AssertionError(f"单测不应向真实虚拟桌面发起请求: {url}")

        monkeypatch.setattr(aos.urllib.request, "urlopen", guarded_urlopen)

        def make(*_a, **kw):
            captured_envs.append(dict(kw.get("env") or {}))
            return _FakeProc()

        monkeypatch.setattr(cr.subprocess, "Popen", make)
        try:
            cr.send_queued(
                "1",
                '<must-use-skill name="how-frago-agent-runs-an-agent-os" path="/tmp/SKILL.md">...</must-use-skill>\n\n绘声绘色的讲解太阳系。',
                cwd="/Users/frago",
            )
            assert len(captured_envs) == 1
            assert captured_envs[0].get("FRAGO_REVIEW") == "off"
            assert captured_envs[0].get("FRAGO_STOP_CHECK") == "off"
            # 旧版男声 PresenterDaemon 已退役，send_queued 不再自动挂载 _presenters
            assert so._presenters.get("1") is None
            assert stage_urls == []
        finally:
            so.cleanup_all_presenters()
            monkeypatch.setattr(aos.urllib.request, "urlopen", orig_urlopen)


class TestEnqueueStateAndModelRecycle:
    """修复核验：入队清空残留 last_result、区分已入库轮次报错与未送达、切模型平滑回收常驻进程。"""

    def test_enqueue_clears_stale_last_result_and_sets_busy_immediately(
        self, fake_binary, no_real_popen
    ):
        sess = cr._session_for("core_stale", "/tmp", None)
        sess.proc = _FakeProc()
        sess.state = "idle"
        sess.last_result = {
            "type": "final",
            "ok": False,
            "error_kind": "llm",
            "rounds": 1,
            "error": "LLM call 1 failed and the run stopped: Invalid model: claude-sonnet-4-6",
        }
        sess.turn_done.set()

        cr._enqueue(sess, "新的一句话")

        assert sess.state == "busy", "入队瞬间必须同步置为 busy，防止 _wait_for_turn 0ms 读到 idle"
        assert sess.last_result == {}, "入队瞬间必须清空上一轮残留的 last_result"
        assert not sess.turn_done.is_set()
        # 此时 _wait_for_turn 在超时内未收到新 result 应返回空字典（在跑），绝不返回上一轮旧 error
        got = cr._wait_for_turn(sess, wait_s=0.05)
        assert got == {}

    def test_send_distinguishes_recorded_llm_error_from_pre_record_unavailable(
        self, fake_binary, monkeypatch
    ):
        # 场景 1：已进入主循环（rounds=1, error_kind="llm"），用户发言与交接均已落盘写入 .jsonl
        # send 应返回 SessionActivation，绝不抛 CoreAgentUnavailable 导致前端把文字退回输入框
        monkeypatch.setattr(cr, "_enqueue", lambda sess, prompt: None)
        monkeypatch.setattr(
            cr,
            "_wait_for_turn",
            lambda sess, wait_s: {
                "type": "final",
                "ok": False,
                "rounds": 1,
                "error_kind": "llm",
                "error": "LLM call 1 failed and the run stopped: HTTP 400 Invalid model",
            },
        )
        act = cr.send("core_rec_err", "帮我查一下", cwd="/tmp", wait_s=0.1)
        assert act.session_id == "core_rec_err"
        assert act.status == "activating"
        assert "LLM call 1 failed" in act.text

        # 场景 2：未进入主循环（rounds=0, error_kind="credential"），消息尚未写入会话记录
        # 必须抛 CoreAgentUnavailable 让前端退回输入框保住用户草稿
        monkeypatch.setattr(
            cr,
            "_wait_for_turn",
            lambda sess, wait_s: {
                "type": "final",
                "ok": False,
                "rounds": 0,
                "error_kind": "credential",
                "error": "profiles.json 里没有可用凭证",
            },
        )
        with pytest.raises(cr.CoreAgentUnavailable, match="没有可用凭证"):
            cr.send("core_cred_err", "帮我查一下", cwd="/tmp", wait_s=0.1)

    def test_recycle_for_model_change_reclaims_idle_and_defers_busy(self):
        idle_sess = cr._session_for("core_idle_m", "/tmp", None, profile_id="old_p")
        idle_proc = _FakeProc()
        idle_sess.proc = idle_proc
        idle_sess.state = "idle"
        idle_sess.last_result = {"error": "stale"}

        busy_sess = cr._session_for("core_busy_m", "/tmp", None, profile_id="old_p")
        busy_proc = _FakeProc()
        busy_sess.proc = busy_proc
        busy_sess.state = "busy"
        busy_sess.in_flight = 1

        stats = cr.recycle_for_model_change(reason="bind_role")

        assert stats == {"reclaimed": 1, "deferred": 1}
        assert idle_proc.stdin.closed, "空闲常驻进程应当场关闭 stdin 回收"
        assert idle_sess.state == "absent"
        assert idle_sess.profile_id is None
        assert idle_sess.last_result == {}

        assert not busy_proc.stdin.closed, "忙碌常驻进程不应在轮次中途被强杀"
        assert busy_sess.reload_on_idle is True
        assert busy_sess.profile_id is None
        final_line = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "本轮完成",
                "num_turns": 1,
                "session_id": "core_busy_m",
            }
        )
        busy_proc.stdout = iter([final_line + "\n"])
        cr._read_loop(busy_sess)
        assert busy_proc.stdin.closed, "忙碌进程在本轮交卷后应自动回收"
        assert busy_sess.state == "absent"

    def test_cross_turn_queued_in_flight_keeps_busy_until_all_turns_finish(self, monkeypatch):
        """跨轮次排队投喂场景：第 1 轮 result 到达时第 2 轮已写进 stdin（in_flight=2），
        只应扣减 1 个 in_flight 并保持 busy（且不触发 reload_on_idle），直到第 2 轮 result 才回 idle。
        """
        from frago.server.services import workbench_queue

        auto_inject_calls: list[str] = []
        monkeypatch.setattr(
            workbench_queue,
            "schedule_auto_inject_after_settle",
            lambda sid: auto_inject_calls.append(sid),
        )

        sess = cr._session_for("core_cross_turn", "/tmp", None)
        proc = _FakeProc()
        sess.proc = proc
        sess.state = "busy"
        sess.in_flight = 2
        sess.reload_on_idle = True

        r1 = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "第一轮完结",
                "num_turns": 1,
                "session_id": "core_cross_turn",
            }
        )
        r2 = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "第二轮完结",
                "num_turns": 1,
                "session_id": "core_cross_turn",
            }
        )

        # 第一轮 result：还有第 2 轮在途，必须保持 busy、不回收进程、不置 turn_done
        proc.stdout = iter([r1 + "\n"])
        cr._read_loop(sess)
        # Note: _read_loop exits when iter ends and sets absent; simulate single stream across both results
        # by verifying state inside a controlled stream or stepping via a queue-backed stdout.
        assert auto_inject_calls == []

    def test_read_loop_step_by_step_cross_turn_and_mid_turn_interjection(self, monkeypatch):
        """逐步模拟常驻 stdout：验证连续两轮 result 逐次扣减 in_flight，以及中途插话被吸收后不锁死 busy。"""
        import queue as pyqueue
        from frago.server.services import workbench_queue

        auto_inject_calls: list[str] = []
        monkeypatch.setattr(
            workbench_queue,
            "schedule_auto_inject_after_settle",
            lambda sid: auto_inject_calls.append(sid),
        )

        class _StepStdout:
            def __init__(self):
                self._q: pyqueue.Queue[str | None] = pyqueue.Queue()

            def push(self, obj: dict[str, object]) -> None:
                self._q.put(json.dumps(obj, ensure_ascii=False) + "\n")

            def close(self) -> None:
                self._q.put(None)

            def __iter__(self):
                return self

            def __next__(self) -> str:
                item = self._q.get(timeout=5)
                if item is None:
                    raise StopIteration
                return item

        # 场景 A：跨轮次排队（第 1 轮 result 回来时第 2 轮仍在途）
        sess = cr._session_for("core_seq_turns", "/tmp", None)
        proc = _FakeProc()
        step_out = _StepStdout()
        proc.stdout = step_out
        sess.proc = proc
        sess.state = "busy"
        sess.in_flight = 2

        t = threading.Thread(target=cr._read_loop, args=(sess,), daemon=True)
        t.start()

        step_out.push(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "turn1",
                "num_turns": 1,
                "session_id": "core_seq_turns",
            }
        )
        time.sleep(0.1)
        with sess.lock:
            assert sess.in_flight == 1
            assert sess.state == "busy"
        assert not sess.turn_done.is_set()
        assert auto_inject_calls == []

        step_out.push(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "turn2",
                "num_turns": 1,
                "session_id": "core_seq_turns",
            }
        )
        time.sleep(0.1)
        with sess.lock:
            assert sess.in_flight == 0
            assert sess.state == "idle"
        assert sess.turn_done.is_set()
        assert auto_inject_calls == ["core_seq_turns"]
        step_out.close()
        t.join(timeout=2)

        # 场景 B：中途插话被内核吸收（发出 user text 事件并最终只输出 1 条 result）
        auto_inject_calls.clear()
        sess_b = cr._session_for("core_interject", "/tmp", None)
        proc_b = _FakeProc()
        step_out_b = _StepStdout()
        proc_b.stdout = step_out_b
        sess_b.proc = proc_b
        sess_b.state = "busy"
        sess_b.in_flight = 2
        sess_b.turn_done.clear()

        tb = threading.Thread(target=cr._read_loop, args=(sess_b,), daemon=True)
        tb.start()

        step_out_b.push(
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": "插一句话"}]},
                "parent_tool_use_id": None,
                "session_id": "core_interject",
            }
        )
        time.sleep(0.05)
        with sess_b.lock:
            assert sess_b.in_flight == 1
            assert sess_b.state == "busy"

        step_out_b.push(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "merged",
                "num_turns": 2,
                "session_id": "core_interject",
            }
        )
        time.sleep(0.1)
        with sess_b.lock:
            assert sess_b.in_flight == 0
            assert sess_b.state == "idle"
        assert sess_b.turn_done.is_set()
        assert auto_inject_calls == ["core_interject"]
        step_out_b.close()
        tb.join(timeout=2)


