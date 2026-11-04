"""点员工卡片起会话时，「在哪个目录里干活」这一栏怎么定。

盯的是这一栏的四档回退顺序，以及它只对员工会话生效：

1. 人写了路径 → 用他写的（手上写下的路径比岗位默认值更贴近这一场要做的事）；
2. 人没写、岗位配了 → 用岗位那一栏（"到那个员工的领地里去"）；
3. 人没写、岗位也没配 → 落到 ``~/.frago``，并且**先把目录建出来**。从前这一档回 400
   「起始目录不能是空的」，人点卡片、什么都没填，看到的是一句要他先去填一栏的话——
   而这一栏本来就该有默认值；
4. 人写的路径以 ``~`` 开头 → 展开成绝对路径再往下传。``~`` 是给人写的，起会话那一步
   认的是绝对路径，不展开的话它会被当成一个字面叫 ``~`` 的目录。

普通工作台会话（没有员工编号）不受这些回退影响：没填目录仍然回 400。那一档没有
"某个岗位的领地"可以退，退到哪儿都是凭空替人做了主。

全程打桩：不起真实 tmux，不碰真实员工编制。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frago.employee import EmployeePostRecord
from frago.server.services import workbench_new_session

POST_ID = "stock"


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """这一栏的回退落在 ``Path.home() / '.frago'``，用例得把家目录指到临时目录。

    打桩的是 ``HOME`` 而不是 ``Path.home``：``Path.home()`` 与 ``expanduser`` 都读这个
    环境变量，只换 ``Path.home`` 的话回退那一档会指到临时目录、而 ``~`` 展开那一档仍
    指向真人的家目录，两条用例各验一半，谁都没被验到。
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def launches(monkeypatch):
    """记下起会话那一步拿到的目录，不真起。"""
    calls: list[str] = []

    def fake_start(agent_type, cwd, prompt, *, session_id):
        calls.append(cwd)
        return workbench_new_session.PendingLaunch(
            handle=session_id,
            agent_type=agent_type,
            display_name="Claude Code",
            cwd=cwd,
            session_id=session_id,
        )

    monkeypatch.setattr(workbench_new_session, "start_with_id", fake_start)
    return calls


@pytest.fixture
def posts(monkeypatch):
    """一份可控的员工编制。用例往里放一条，就等于"这个岗位存在"。"""

    def _register(record: EmployeePostRecord | None):
        monkeypatch.setattr(
            "frago.server.routes.workbench.get_post", lambda _post_id: record, raising=True
        )

    monkeypatch.setattr("frago.server.routes.workbench.save_post", lambda _r: None)
    return _register


@pytest.fixture
def client(monkeypatch):
    # 员工语境块是另一条路的事，这里换成一句占位，用例只盯目录。
    class _FakeService:
        def build_business_context_block(self, _post_id):
            return "<frago-employee id='stock'>…</frago-employee>"

    monkeypatch.setattr("frago.server.routes.workbench.EmployeeOntologyService", _FakeService)

    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


def _start(client, *, cwd: str, employee: str = POST_ID):
    return client.post(
        "/api/workbench/sessions",
        json={"agent": "claude", "cwd": cwd, "text": "干活", "employee": employee},
    )


class TestEmployeeSession:
    def test_岗位没配目录时落到frago家目录(self, client, posts, launches, fake_home):
        """人什么都没填也该起得来：这一栏的默认值是 frago 家目录，不是一句必填提示。"""
        posts(EmployeePostRecord(member_post_id=POST_ID, title="Stock"))

        res = _start(client, cwd="")

        assert res.status_code == 201
        assert launches == [str(fake_home / ".frago")]
        assert res.json()["cwd"] == str(fake_home / ".frago")

    def test_回退的目录先建出来再用(self, client, posts, launches, fake_home):
        """不建的话，起会话那一步拿着一个不存在的目录去挂 TUI，失败的样子是"会话没起来"，
        与这一栏的关系谁都看不出来。"""
        posts(EmployeePostRecord(member_post_id=POST_ID, title="Stock"))
        assert not (fake_home / ".frago").exists()

        _start(client, cwd="")

        assert (fake_home / ".frago").is_dir()

    def test_岗位配了目录就用岗位那一栏(self, client, posts, launches, fake_home):
        stock = fake_home / "srv" / "stock"
        stock.mkdir(parents=True, exist_ok=True)
        posts(EmployeePostRecord(member_post_id=POST_ID, title="Stock", cwd=str(stock)))

        _start(client, cwd="")

        assert launches == [str(stock)]

    def test_人写的路径盖过岗位那一栏(self, client, posts, launches, fake_home):
        stock = fake_home / "srv" / "stock"
        stock.mkdir(parents=True, exist_ok=True)
        other = fake_home / "srv" / "other"
        other.mkdir(parents=True, exist_ok=True)
        posts(EmployeePostRecord(member_post_id=POST_ID, title="Stock", cwd=str(stock)))

        _start(client, cwd=str(other))

        assert launches == [str(other)]

    def test_人写的波浪号展开成绝对路径(self, client, posts, launches, fake_home):
        """``~`` 是给人写的，起会话那一步认的是绝对路径。不展开它就去找一个字面叫
        ``~`` 的目录。"""
        posts(EmployeePostRecord(member_post_id=POST_ID, title="Stock"))

        _start(client, cwd="~/.frago/data")

        assert launches == [str(fake_home / ".frago" / "data")]

    def test_岗位配的路径带波浪号也展开(self, client, posts, launches, fake_home):
        (fake_home / "work").mkdir(parents=True, exist_ok=True)
        posts(EmployeePostRecord(member_post_id=POST_ID, title="Stock", cwd="~/work"))

        _start(client, cwd="")

        assert launches == [str(fake_home / "work")]

    def test_只有空白的人手填写当没写(self, client, posts, launches, fake_home):
        posts(EmployeePostRecord(member_post_id=POST_ID, title="Stock"))

        _start(client, cwd="   ")

        assert launches == [str(fake_home / ".frago")]

    def test_位于frago家目录下的子目录尚不存在时自动建出来(
        self, client, posts, launches, fake_home
    ):
        """员工领地目录是随用随建的：人点卡片起会话时它多半还没建过，而 ``tmux`` 碰到
        不存在的目录会静默退回 ``$HOME``，认领型内核据此记错工作区，最终只报一句
        「会话没起来」。"""
        posts(EmployeePostRecord(member_post_id=POST_ID, title="Stock"))
        target = fake_home / ".frago" / "data" / "personal"
        assert not target.exists()

        res = _start(client, cwd="~/.frago/data/personal")

        assert res.status_code == 201
        assert target.is_dir()
        assert launches == [str(target)]

    def test_外部起始目录不存在时当场回400不让tmux静默退回主目录(
        self, client, posts, launches, fake_home
    ):
        """家目录外的目录不替人做主：把「目录写错了」留在它该出现的地方，而不是让它
        变形为一次认领超时。"""
        posts(EmployeePostRecord(member_post_id=POST_ID, title="Stock"))
        missing = fake_home / "no-such-dir"
        assert not missing.exists()

        res = _start(client, cwd=str(missing))

        assert res.status_code == 400
        assert "起始目录不存在" in res.json()["detail"]
        assert launches == []

    def test_员工配了默认技能与舞台技能时自动嵌入并触发三角色舞台编排(
        self, client, posts, monkeypatch, fake_home
    ):
        """员工编制自带的 `skills` 在起会话时自动并入，含舞台技能时自动触发 `orchestrate_stage_session`。"""
        from frago.server.services import stage_orchestrator
        from frago.skills.skill_prompt import EmbeddedSkill

        posts(
            EmployeePostRecord(
                member_post_id="demo-director",
                title="视频导演",
                agent_kernel="agy",
                skills=[
                    "how-frago-agent-runs-an-agent-os",
                    "frago-agent-os-twitter-demo",
                ],
            )
        )

        loaded_names: list[str] = []

        def fake_load_skills(names):
            loaded_names.extend(names)
            return [
                EmbeddedSkill(name=n, path=fake_home / f"{n}.md", body=f"# Skill {n}")
                for n in names
            ]

        monkeypatch.setattr("frago.server.routes.workbench.load_skills", fake_load_skills)

        orchestrated_calls: list[tuple[str, str, str]] = []

        def fake_orchestrate(session_id: str, prompt: str, user_text: str) -> str:
            orchestrated_calls.append((session_id, prompt, user_text))
            return f"{prompt}\n[STAGE_ORCHESTRATED]"

        monkeypatch.setattr(
            stage_orchestrator, "orchestrate_stage_session", fake_orchestrate
        )

        captured_prompts: list[str] = []

        def fake_start(agent_type, cwd, prompt, *, session_id):
            captured_prompts.append(prompt)
            return workbench_new_session.PendingLaunch(
                handle="webui-stage-handle",
                agent_type=agent_type,
                display_name="Antigravity",
                cwd=cwd,
                session_id=None,
            )

        monkeypatch.setattr(workbench_new_session, "start_with_id", fake_start)

        res = client.post(
            "/api/workbench/sessions",
            json={
                "agent": "agy",
                "cwd": "",
                "text": "录制新功能演示视频",
                "employee": "demo-director",
            },
        )
        assert res.status_code == 201
        assert loaded_names == [
            "how-frago-agent-runs-an-agent-os",
            "frago-agent-os-twitter-demo",
        ]
        assert len(orchestrated_calls) == 1
        assert orchestrated_calls[0][2] == "录制新功能演示视频"
        assert len(captured_prompts) == 1
        assert "[STAGE_ORCHESTRATED]" in captured_prompts[0]
        assert "# Skill how-frago-agent-runs-an-agent-os" in captured_prompts[0]

    def test_认领型内核在异步认到真编号后自动写回员工活跃会话清单(
        self, tmp_path, monkeypatch
    ):
        """agy / codex / opencode 起会话那一刻 `session_id` 为 None，待 `_adopt_claimed` 认到真编号后自动写回员工编制。"""
        from frago.employee import EmployeeOntologyService, get_post

        monkeypatch.setenv("FRAGO_HOME", str(tmp_path))
        monkeypatch.setenv("FRAGO_EMPLOYEES_DIR", str(tmp_path / "employees"))

        svc = EmployeeOntologyService()
        svc.hire("demo-director", title="视频导演", agent_kernel="agy")

        handle = "webui-async-claim-001"
        launch = workbench_new_session.PendingLaunch(
            handle=handle,
            agent_type="agy",
            display_name="Antigravity",
            cwd=str(tmp_path),
            session_id=None,
        )
        with workbench_new_session._lock:
            workbench_new_session._launches[handle] = launch

        workbench_new_session.bind_employee(handle, "demo-director")
        monkeypatch.setattr(
            workbench_new_session,
            "_resolve_claimed",
            lambda _agent, _handle: "agy-claimed-session-777",
        )

        claimed = workbench_new_session._adopt_claimed(launch)
        assert claimed is True
        assert launch.session_id == "agy-claimed-session-777"

        record = get_post("demo-director")
        assert record is not None
        assert "agy-claimed-session-777" in record.active_session_ids


class TestPlainSession:
    def test_普通会话没填目录仍然回400(self, client, launches):
        """没有员工可以退：退到哪儿都是凭空替人做了主。"""
        res = client.post(
            "/api/workbench/sessions", json={"agent": "claude", "cwd": "", "text": "干活"}
        )

        assert res.status_code == 400
        assert res.json()["detail"] == "起始目录不能是空的"
        assert launches == []

    def test_普通会话填了就照填的走(self, client, launches, fake_home):
        (fake_home / "repo").mkdir(parents=True, exist_ok=True)
        res = client.post(
            "/api/workbench/sessions",
            json={"agent": "claude", "cwd": "~/repo", "text": "干活"},
        )

        assert res.status_code == 201
        assert res.json()["cwd"].endswith("/repo")
        assert not res.json()["cwd"].startswith("~")
