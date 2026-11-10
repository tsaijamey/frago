"""Unit tests for `frago calendar` store, CLI commands, and HTTP routes."""

import importlib
import json
import os
from pathlib import Path
import sys
import types
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frago.calendar import store
from frago.cli.calendar_commands import calendar_group
from frago.server.routes.calendar import router as calendar_router


@pytest.fixture
def isolated_cal_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FRAGO_CALENDAR_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def runner(isolated_cal_dir: Path) -> CliRunner:
    return CliRunner()


def test_store_add_and_idempotency(isolated_cal_dir: Path) -> None:
    # 1. 正常添加单条事务
    item1 = store.add_affair(
        title="实现 Agent Ontology 架构方案",
        date="2026-11-08",
        summary="排查多内核待输入状态盲区并设计四级能力矩阵",
        category="系统研发",
        employee="frago-developer",
        sessions=["c767deb5-f7af-499f-9377-24ffbc05315b"],
        artifacts=["/Users/frago/.frago/data/frago-dev/20261108-agent-ontology-design/notebook.md"],
    )
    assert item1.id.startswith("aff-20261108-")
    assert item1.title == "实现 Agent Ontology 架构方案"
    assert item1.category == "系统研发"
    assert item1.employee == "frago-developer"

    # 2. 同日同标题幂等添加，自动合并并更新摘要与会话
    item2 = store.add_affair(
        title="实现 Agent Ontology 架构方案",
        date="2026-11-08",
        summary="排查多内核盲区并完成容器回归验证全量通过",
        category="系统研发",
        employee="frago-developer",
        sessions=["core_65940cecebec48e2bbd73f9a19336d57"],
        artifacts=["/Users/frago/.frago/data/frago-dev/20261108-agent-ontology-design/vm-verify-report.md"],
    )
    assert item2.id == item1.id  # 保持相同 ID
    assert item2.summary == "排查多内核盲区并完成容器回归验证全量通过"
    assert "c767deb5-f7af-499f-9377-24ffbc05315b" in item2.sessions
    assert "core_65940cecebec48e2bbd73f9a19336d57" in item2.sessions
    assert len(item2.artifacts) == 2

    # 查询列表，总条数应为 1
    items = store.list_affairs(date="2026-11-08")
    assert len(items) == 1


def test_store_batch_write_modes(isolated_cal_dir: Path) -> None:
    items_data = [
        {
            "title": "任务一",
            "date": "2026-11-08",
            "category": "研发",
            "employee": "dev",
            "summary": "第一项任务完成",
        },
        {
            "title": "任务二",
            "date": "2026-11-08",
            "category": "宣发",
            "employee": "operator",
            "summary": "第二项任务完成",
        },
    ]

    # upsert 写入
    written = store.write_affairs(items_data, mode="upsert")
    assert len(written) == 2
    assert len(store.list_affairs(date="2026-11-08")) == 2

    # replace 写入新数据，原数据被替换
    new_data = [
        {
            "title": "新单一任务",
            "date": "2026-11-08",
            "category": "统筹",
            "summary": "覆写后的单一条目",
        }
    ]
    replaced = store.write_affairs(new_data, mode="replace")
    assert len(replaced) == 1
    current = store.list_affairs(date="2026-11-08")
    assert len(current) == 1
    assert current[0].title == "新单一任务"


def test_store_query_update_remove(isolated_cal_dir: Path) -> None:
    item = store.add_affair(
        title="暗光调光配方录制",
        date="2026-11-07",
        category="演示宣发",
        employee="desktop-operator",
        tags=["video", "desktop"],
    )

    # 检索命中
    res = store.list_affairs(query="调光")
    assert len(res) == 1
    assert res[0].id == item.id

    # 按员工筛选
    res_emp = store.list_affairs(employee="desktop-operator")
    assert len(res_emp) == 1

    # 修改
    updated = store.update_affair(item.id, title="暗光调光配方全流程剪辑成片", category="配方工程")
    assert updated is not None
    assert updated.title == "暗光调光配方全流程剪辑成片"
    assert updated.category == "配方工程"

    # 删除
    removed = store.remove_affair(item.id)
    assert removed is True
    assert len(store.list_affairs()) == 0


def test_cli_commands_roundtrip(runner: CliRunner, isolated_cal_dir: Path) -> None:
    # 1. calendar add
    res = runner.invoke(
        calendar_group,
        [
            "add",
            "-t",
            "补齐员工弹窗默认技能控件",
            "-d",
            "2026-11-08",
            "-c",
            "系统研发",
            "-e",
            "frago-developer",
            "-s",
            "前端控件补齐并跑通测试",
            "--session",
            "3d1c0959",
            "--artifact",
            "/Users/frago/test/notebook.md",
            "--json",
        ],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    aff_id = data["id"]
    assert data["title"] == "补齐员工弹窗默认技能控件"

    # 2. calendar list
    res_list = runner.invoke(calendar_group, ["list", "--date", "2026-11-08"])
    assert res_list.exit_code == 0
    assert "补齐员工弹窗默认技能控件" in res_list.output
    assert "frago-developer" in res_list.output

    # 3. calendar update
    res_up = runner.invoke(
        calendar_group,
        ["update", aff_id, "--summary", "已升级最新交互并完成构建", "--json"],
    )
    assert res_up.exit_code == 0
    up_data = json.loads(res_up.output)
    assert up_data["summary"] == "已升级最新交互并完成构建"

    # 4. calendar write
    batch_json = json.dumps(
        [
            {
                "title": "配方模型配置大弹窗改造",
                "date": "2026-11-08",
                "category": "配方工程",
                "employee": "recipe-builder",
                "summary": "遮罩占视口 80% 面积三栏居中卡片",
            }
        ]
    )
    res_write = runner.invoke(calendar_group, ["write", "--json", batch_json])
    assert res_write.exit_code == 0
    assert "成功写入 1 项事务" in res_write.output

    # 5. calendar remove
    res_rm = runner.invoke(calendar_group, ["remove", aff_id, "--json"])
    assert res_rm.exit_code == 0
    assert json.loads(res_rm.output)["ok"] is True


def test_api_routes(isolated_cal_dir: Path) -> None:
    app = FastAPI()
    app.include_router(calendar_router, prefix="/api")
    client = TestClient(app)

    # 1. POST /api/calendar/affairs (单条)
    create_resp = client.post(
        "/api/calendar/affairs",
        json={
            "title": "定时任务调度器假闭环排查",
            "date": "2026-11-08",
            "category": "系统研发",
            "employee": "frago-developer",
            "summary": "查明临时独立员工会话派发机制与全链路等待改进",
            "sessions": ["ac80fa5f-03dc-407a-b464-7c29ef5f456e"],
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    aff_id = create_resp.json()["item"]["id"]

    # 2. GET /api/calendar/affairs
    get_resp = client.get("/api/calendar/affairs?month=2026-11")
    assert get_resp.status_code == 200
    res_data = get_resp.json()
    assert res_data["summary"]["total_affairs"] == 1
    assert "2026-11-08" in res_data["by_date"]
    assert res_data["by_date"]["2026-11-08"]["count"] == 1

    # 3. PATCH /api/calendar/affairs/{item_id}
    patch_resp = client.patch(
        f"/api/calendar/affairs/{aff_id}",
        json={"summary": "提出方案1全链路树状等待治本机制"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["item"]["summary"] == "提出方案1全链路树状等待治本机制"

    # 4. DELETE /api/calendar/affairs/{item_id}
    del_resp = client.delete(f"/api/calendar/affairs/{aff_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True


def test_windows_store_locking_simulation(isolated_cal_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. 模拟 Windows 环境：屏蔽 fcntl，注入 mock msvcrt
    mock_msvcrt = types.ModuleType("msvcrt")
    mock_msvcrt.LK_LOCK = 1
    mock_msvcrt.LK_UNLCK = 2
    mock_msvcrt.locking = MagicMock()

    monkeypatch.setitem(sys.modules, "fcntl", None)
    monkeypatch.setitem(sys.modules, "msvcrt", mock_msvcrt)

    # 重新加载 store 模块以验证在无 fcntl 的 Windows 环境下导入零崩溃
    reloaded_store = importlib.reload(store)
    monkeypatch.setattr(reloaded_store, "_IS_WINDOWS", True)

    try:
        # 2. 验证 add_affair 调用触发 msvcrt.locking 加锁与解锁
        item = reloaded_store.add_affair(
            title="Windows 端跨平台文件锁验证",
            date="2026-11-10",
            category="系统验证",
            summary="模拟 Windows 环境无 fcntl 运行",
        )
        assert item.title == "Windows 端跨平台文件锁验证"

        # 断言 msvcrt.locking 调用记录
        locking_calls = mock_msvcrt.locking.call_args_list
        assert len(locking_calls) >= 2
        assert locking_calls[0].args[1] == mock_msvcrt.LK_LOCK
        assert locking_calls[1].args[1] == mock_msvcrt.LK_UNLCK
        assert locking_calls[0].args[2] == 1
        assert locking_calls[1].args[2] == 1
        mock_msvcrt.locking.reset_mock()

        # 3. 验证 write_affairs 调用触发加锁与解锁
        written = reloaded_store.write_affairs(
            [
                {
                    "title": "Windows 批量任务",
                    "date": "2026-11-10",
                    "category": "系统验证",
                }
            ],
            mode="upsert",
        )
        assert len(written) == 1
        locking_calls = mock_msvcrt.locking.call_args_list
        assert len(locking_calls) >= 2
        assert locking_calls[0].args[1] == mock_msvcrt.LK_LOCK
        assert locking_calls[1].args[1] == mock_msvcrt.LK_UNLCK
        mock_msvcrt.locking.reset_mock()

        # 4. 验证 update_affair 调用触发加锁与解锁
        updated = reloaded_store.update_affair(
            item.id,
            date="2026-11-10",
            summary="Windows 更新完成",
        )
        assert updated is not None
        assert updated.summary == "Windows 更新完成"
        locking_calls = mock_msvcrt.locking.call_args_list
        assert len(locking_calls) >= 2
        assert locking_calls[0].args[1] == mock_msvcrt.LK_LOCK
        assert locking_calls[1].args[1] == mock_msvcrt.LK_UNLCK
        mock_msvcrt.locking.reset_mock()

        # 5. 验证 remove_affair 调用触发加锁与解锁
        removed = reloaded_store.remove_affair(item.id, date="2026-11-10")
        assert removed is True
        locking_calls = mock_msvcrt.locking.call_args_list
        assert len(locking_calls) >= 2
        assert locking_calls[0].args[1] == mock_msvcrt.LK_LOCK
        assert locking_calls[1].args[1] == mock_msvcrt.LK_UNLCK
        mock_msvcrt.locking.reset_mock()

        # 6. 验证 _month_lock 在抛出异常时仍能可靠释放锁
        with pytest.raises(RuntimeError, match="测试中断"):
            with reloaded_store._month_lock("2026-11"):
                raise RuntimeError("测试中断")

        locking_calls = mock_msvcrt.locking.call_args_list
        assert len(locking_calls) == 2
        assert locking_calls[0].args[1] == mock_msvcrt.LK_LOCK
        assert locking_calls[1].args[1] == mock_msvcrt.LK_UNLCK
    finally:
        # 恢复环境以防影响其它测试
        monkeypatch.undo()
        importlib.reload(store)


def test_posix_month_lock_lifecycle_and_exception_safety(isolated_cal_dir: Path) -> None:
    # 验证 POSIX 原生环境下的 _month_lock 生命周期与异常安全性
    # 1. 正常加锁与释放
    with store._month_lock("2026-11"):
        lock_file = store.get_calendar_dir() / ".affairs-2026-11.lock"
        assert lock_file.exists()

    # 2. 异常路径下锁安全释放，不影响后续加锁与写入
    with pytest.raises(ValueError, match="事务模拟失败"):
        with store._month_lock("2026-11"):
            raise ValueError("事务模拟失败")

    # 后续操作仍然能够正常获取锁并成功写入
    item = store.add_affair(
        title="异常释放后正常重入写入",
        date="2026-11-10",
        category="系统验证",
    )
    assert item.title == "异常释放后正常重入写入"
    items = store.list_affairs(date="2026-11-10")
    assert len(items) == 1
    assert items[0].id == item.id
