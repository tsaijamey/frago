"""在图形界面里创建配方：导演会话的起法与任务书的硬约束。

任务书是导演唯一知道的东西，所以这里钉的是它**必须写着**的那几句：worker 借住桌面
终端（--tmux-target frago-stage）、舞台自己起起来之后就不许停、开口排在准备之前、
人追加的话怎么转达、没界面时 page 为假。起会话之前只剩一道闸（名字合不合法），
舞台在不在跑不再是拒绝的理由——它自己 up（2026-10-08 放开旧 409 预检）。
"""

from __future__ import annotations

import pytest

from frago.server.services import recipe_forge


def test_brief_pins_the_control_chain() -> None:
    brief = recipe_forge.build_brief(
        "每天抓一遍 ETF 净值画成走势图", page=True, name=None, session_id="sid-1"
    )
    assert "--tmux-target frago-stage" in brief
    assert "frago desktop down" in brief  # 铁律里点名禁止
    assert "run_in_background" in brief
    assert "frago desktop type" in brief and "frago desktop key Enter" in brief
    assert "~/.frago/forge/sid-1" in brief
    assert "由你定" in brief
    assert "browser open http://127.0.0.1:8093/app/<名字>/" in brief


def test_brief_lets_the_director_raise_the_stage_and_talk_first() -> None:
    """放开铁律 1 的上半条：自己 up；下半条（停了它）与首帧要求一个字都没松。"""
    brief = recipe_forge.build_brief("x", page=True, name=None, session_id="s")
    assert "frago desktop up" in brief
    assert "不要自己拉" not in brief  # 旧版那句「桌面上没有就汇报、不要自己拉」已撤
    assert "frago desktop down" in brief
    assert "frago server restart" in brief
    assert "首帧" in brief
    assert "voice synth" in brief  # 台词先合成
    assert "5–10 秒" in brief  # 看 worker 的节奏
    assert "elements" in brief  # 推近之前先取可寻址的名字


def test_brief_pins_the_four_showmanship_rules() -> None:
    """2026-10-08 那一轮人报的四处观感，逐条钉住：容器、措辞、指针、进度板。"""
    brief = recipe_forge.build_brief("x", page=True, name=None, session_id="s")
    # 容器：桌上至少两扇窗；关窗整场只允许一处（「需要界面：否」那一处）
    assert "至少两扇窗" in brief
    assert "window close 整场只允许用在这一处" in brief
    # 措辞：旁白主语是「我」，默认真开口
    assert "旁白是「我」" in brief
    assert "默认带 --speak" in brief
    # 指针：每说一句配一次指针动作，等的时间不许只 term read
    assert "mouse to --ref" in brief and "mouse drift" in brief
    assert "NEVER 只发" in brief
    # 进度板：三样数据、固定三步、停到终端右边
    assert "进度板" in brief
    assert "window move --target image" in brief
    for item in ("规格", "模式", "验收"):
        assert item in brief


def test_brief_embeds_a_runnable_board_script() -> None:
    """内嵌的板子脚本 MUST 是一段能编译的 python——占位符替换坏了，这里先红。"""
    import re as _re

    brief = recipe_forge.build_brief("x", page=True, name=None, session_id="s")
    assert "__BOARD_SCRIPT__" not in brief, "占位符没被替换"
    m = _re.search(r"```bash\n(.*?)\n```", brief, _re.S)
    assert m, "任务书里没有板子脚本"
    script = m.group(1)
    compile(script, "<board>", "exec")  # 语法不成立就当场炸
    for fn in ("read_spec_size", "read_modes", "read_checks", "main()"):
        assert fn in script


def test_the_board_script_actually_renders(tmp_path) -> None:
    """把内嵌的板子脚本抠出来真跑：出得了图、画得上字、内容变长画布跟着长（不裁字）。"""
    import re as _re
    import subprocess
    import sys as _sys

    pytest.importorskip("PIL")
    from PIL import Image

    brief = recipe_forge.build_brief("x", page=True, name=None, session_id="s")
    script = _re.search(r"```bash\n(.*?)\n```", brief, _re.S).group(1)
    board = tmp_path / "board.py"
    board.write_text(script, encoding="utf-8")

    def render(name: str, spec: str):
        rdir = tmp_path / name
        rdir.mkdir()
        (rdir / "spec.md").write_text(spec, encoding="utf-8")
        png = tmp_path / f"{name}.png"
        res = subprocess.run(
            [_sys.executable, str(board), str(rdir), str(png)], capture_output=True, text=True
        )
        assert res.returncode == 0, res.stderr
        im = Image.open(png).convert("RGB")
        px = im.load()
        w, h = im.size
        rows = [y for y in range(h) if any(px[x, y] != (24, 26, 32) for x in range(30, w - 30, 2))]
        return (w, h), len(rows), (h - 1 - max(rows) if rows else 0)

    size, ink_rows, bottom_margin = render(
        "plain", "```yaml\nmodes:\n  status: export\n```\nfrago recipe run a\n"
    )
    assert size[0] == 640
    assert ink_rows > 40  # 画上了东西，不是一张纯底色
    assert bottom_margin >= 10  # 底部留白在，字没被切在边界上

    long_spec = (
        "```yaml\nmodes:\n"
        + "".join(f"  very_long_mode_name_number_{i}: export\n" for i in range(8))
        + "```\n"
    )
    taller, ink_rows2, margin2 = render("long", long_spec)
    assert taller[1] > size[1], "内容长了画布没跟着长，字会被裁掉"
    assert ink_rows2 > ink_rows
    assert margin2 >= 10


def test_brief_without_page_asks_for_a_data_only_recipe() -> None:
    brief = recipe_forge.build_brief("x", page=False, name="etf_board", session_id="s")
    assert "page: false" in brief
    assert "window close --target browser" in brief
    assert "配方名：etf_board" in brief


def test_brief_makes_the_director_queue_its_speech_ahead() -> None:
    """2026-10-09 那一轮人报的「话不够多、经常有声音 gap」，钉住改后的工序。

    要害是说话**不再挂在模型的回合上**：先写话、切短句、逐句合成拿时长、排队放。
    上一版那句「读一次终端说一句」把说话的时机交给了 poll，而 poll 之间是思考，
    思考在桌面上就是静音。
    """
    brief = recipe_forge.build_brief("x", page=True, name=None, session_id="s")
    # 工序四步都在：写话落到文件、切成短句、逐句合成、排队
    assert "script.md" in brief
    assert "切短句" in brief
    assert "--async" in brief and "wait --speech" in brief
    assert "duration_ms" in brief
    # 队列不许空，且要边放边续
    assert "NEVER 让它空" in brief
    # 两类话分开：并行层与插播层
    assert "并行层" in brief and "插播" in brief
    # 插播用 --interject（掐当前、保住队列）；--interrupt 与 voice stop 禁用
    # ——那两条把排着的整队丢掉，正是要防的那种 gap
    assert "--interject" in brief
    assert "整队丢掉" in brief
    assert "NEVER 用 `--interrupt`" in brief
    # 同一个名词全篇一个意思：幕脚本第 9 步里的「插播」也是 --interject。
    # 一处说「掐当前立刻说」、另一处说「排到队尾」，导演按哪条做都有一半是错的。
    # 任务书是折行排的，跨行的那条把空白压平再断言，免得改个折行就把测试弄红。
    flat = " ".join(brief.split())
    assert "排到队尾" not in flat
    assert "变化来的话**插播**一句 （`--interject`" in flat
    # 插播的例句必须是英文：它同时就是字幕，而语音层只认英文——中文那句会被当场拒，
    # 并把同一条命令里余下的步骤一起带停
    assert '"The recipe is ready' in brief
    assert '"It failed: <one-line reason>"' in brief
    # 英文这条规矩要写明不达标的代价，别让人以为跟「合成失败」一样只停这一句
    assert "回执里 `not_reached`" in brief
    # 幕脚本从加分项提成主线
    assert "它是这场演出的主线，不是空档里的加分项" in brief
    # 一次排一长串：一批写进文件、一条命令整批发（一个回合排十几句）
    assert "一次排一长串" in brief
    assert "整批执行" in brief
    assert "10–20 句" in brief
    # 批长有上限的理由：插播不用等队列了，但队列压得越久、掉头越慢
    assert "转向变慢" in brief
    # 人类输入行（右下角客服式对话面板）写进任务书：导演知道可以问人，也知道去哪问
    assert "输入行" in brief and "人会跟你说话" in brief
    assert "右下角" in brief and "bottom-right corner" in brief


def test_brief_splits_generic_agent_os_skill_from_recipe_specific_task() -> None:
    """通用舞台能力抽进 how-frago-agent-runs-an-agent-os skill，场景任务书只留创建配方特异要求。

    两层合起来等于完整导演任务书；而 skill 单独拿去别的场景用时，不带任何创建配方的词。
    """
    from frago.skills.skill_prompt import load_skills, split_skill_blocks

    brief = recipe_forge.build_brief("做一个看板", page=True, name="my_board", session_id="sid-2")
    names, task = split_skill_blocks(brief)
    assert names == [recipe_forge.AGENT_OS_SKILL_NAME]
    assert task == recipe_forge.build_recipe_task(
        "做一个看板", page=True, name="my_board", session_id="sid-2"
    )

    skill_body = load_skills([recipe_forge.AGENT_OS_SKILL_NAME])[0].body
    # 1. skill 覆盖边干活边讲解演示 + 同步录制视频
    assert "How Frago Agent Runs an Agent OS" in skill_body
    assert "边执行事务边为用户讲解演示" in skill_body
    assert "同步录制视频" in skill_body
    assert "rec start" in skill_body and "rec stop" in skill_body
    assert "caffeinate -dimsu" in skill_body

    # 2. skill 不带任何 create recipe 的特异信息
    for leaked in ("配方", "recipe", "spec.md", "recipe.py", "board.py", "validate"):
        assert leaked not in skill_body.lower(), f"skill 混入了创建配方特异词: {leaked}"

    # 3. 场景任务书不再重复大段通用语音合成与舞台教程，但保留配方特定要求
    assert "## 话从哪来：先写话，再排音频" not in task
    assert "frago recipe create" in task
    assert "1/5 定名" in task and "5/5 完成" in task


def test_start_goes_ahead_when_the_stage_is_not_running(monkeypatch) -> None:
    """舞台没在跑不再是拒绝的理由：会话照起，起来之后由导演自己 frago desktop up。"""
    from frago.server.services import workbench_agents, workbench_new_session

    class _Agent:
        agent_type = "coreagent"
        id_origin = "caller"

    monkeypatch.setattr(workbench_agents, "require_selectable", lambda _t: _Agent())

    def fake_start_with_id(agent_type, cwd, prompt, *, session_id):
        return workbench_new_session.PendingLaunch(
            handle=session_id, agent_type=agent_type, display_name="CoreAgent",
            cwd=cwd, session_id=session_id,
        )

    monkeypatch.setattr(workbench_new_session, "start_with_id", fake_start_with_id)
    launch = recipe_forge.start("做一个看板")
    assert launch.session_id.startswith("core_")


def test_start_refuses_a_bad_name(monkeypatch) -> None:
    with pytest.raises(recipe_forge.BadRecipeName):
        recipe_forge.start("x", name="Not Snake")


def test_start_refuses_an_existing_name(monkeypatch) -> None:
    from frago.recipes import registry as recipe_registry

    class _Reg:
        def find(self, name):
            return object()

    monkeypatch.setattr(recipe_registry, "get_registry", lambda: _Reg())
    with pytest.raises(recipe_forge.BadRecipeName):
        recipe_forge.start("x", name="taken_name")


def test_start_hands_the_brief_to_a_coreagent_session_with_a_known_id(monkeypatch) -> None:
    from frago.server.services import workbench_agents, workbench_new_session

    requested: list[str] = []

    class _Agent:
        agent_type = "coreagent"
        id_origin = "caller"

    def fake_require_selectable(agent_type: str):
        requested.append(agent_type)
        return _Agent()

    monkeypatch.setattr(workbench_agents, "require_selectable", fake_require_selectable)
    seen: dict = {}

    def fake_start_with_id(agent_type, cwd, prompt, *, session_id):
        seen.update(agent_type=agent_type, cwd=cwd, prompt=prompt, session_id=session_id)
        return workbench_new_session.PendingLaunch(
            handle=session_id, agent_type=agent_type, display_name="CoreAgent",
            cwd=cwd, session_id=session_id,
        )

    monkeypatch.setattr(workbench_new_session, "start_with_id", fake_start_with_id)
    launch = recipe_forge.start("做一个看板", page=True)
    assert requested == ["coreagent"]
    assert seen["agent_type"] == "coreagent"
    assert launch.session_id.startswith("core_")
    assert seen["session_id"] == launch.session_id
    # 任务书里写的目录用的正是这场会话的编号。
    assert f"~/.frago/forge/{launch.session_id}" in seen["prompt"]
    assert launch.desktop_url == f"/app/agent_os?userInput=true&session={launch.session_id}"
    assert launch.recipe_name is None


def test_send_queued_returns_before_the_turn_ends(monkeypatch) -> None:
    """排队投喂：判完落点就返回；真正的投喂在别的线程里，本线程不等。"""
    import threading

    from frago.server.services import session_send, ui_session_runner

    monkeypatch.setattr(
        session_send,
        "resolve_target",
        lambda sid, cwd_hint=None: session_send.SendTarget(
            sid, "claude-code", "claude", "/tmp", is_new=False
        ),
    )
    started = threading.Event()
    release = threading.Event()

    class _Runner:
        def send(self, *_a, **_k):
            started.set()
            release.wait(timeout=5)

    monkeypatch.setattr(ui_session_runner, "get_runner", lambda: _Runner())
    name = session_send.send_queued("abc", "补一句")
    assert name.startswith("webui-queued-send-")
    assert started.wait(timeout=2)  # 投喂确实开始了
    release.set()
