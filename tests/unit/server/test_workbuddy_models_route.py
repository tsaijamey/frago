"""The WorkBuddy model list the connection form picks from."""

import json
import os
import time
from contextlib import ExitStack
from unittest.mock import patch

import pytest

#: 客户端菜单里能选的那些，带倍率。测试里固定这一份，不去读本机的客户端缓存。
OFFERED = {
    "fast": {"id": "fast", "name": "Fast", "credits": "x0.03", "credits_value": 0.03},
    "mid": {"id": "mid", "name": "Mid", "credits": "x0.50", "credits_value": 0.50},
    "dear": {"id": "dear", "name": "Dear", "credits": "x1.20", "credits_value": 1.20},
}


def _write_list(path, models, *, written=None):
    path.write_text(
        json.dumps({"probed_at": "2026-09-11T05:30:19.001591", "models": models}),
        encoding="utf-8",
    )
    if written is not None:
        os.utime(path, (written, written))
    return path


def _route(*, models_path, login_path, offered=None, balance=None):
    """把这条接口跟本机的三个外部来源隔开：清单文件、登录文件、菜单与余额。"""
    stack = ExitStack()
    stack.enter_context(patch("frago.init.profile_manager.WORKBUDDY_MODELS_PATH", models_path))
    stack.enter_context(
        patch("frago.init.profile_manager.workbuddy_login_path", return_value=login_path)
    )
    stack.enter_context(
        patch(
            "frago.server.services.workbuddy_service.chat_models",
            return_value=dict(OFFERED if offered is None else offered),
        )
    )
    stack.enter_context(
        patch("frago.server.services.workbuddy_service.credit_balance", return_value=balance)
    )
    return stack


@pytest.mark.asyncio
async def test_the_probe_time_is_the_local_time_the_list_was_written(tmp_path):
    """frago-core stamps the probe in UTC; the page shows local time everywhere else."""
    from frago.server.routes.settings import get_workbuddy_models

    path = _write_list(
        tmp_path / "workbuddy-models.json",
        [{"id": "fast", "ok": True, "wire": "openai"}, {"id": "mid", "ok": False}],
        written=time.mktime((2026, 9, 11, 13, 30, 19, 0, 0, -1)),
    )
    with _route(models_path=path, login_path=tmp_path / "none"):
        resp = await get_workbuddy_models()

    assert resp.probed_at == "2026-09-11T13:30:19"
    assert resp.logged_in is False
    assert [(m.id, m.ok) for m in resp.models] == [("fast", True), ("mid", False)]


@pytest.mark.asyncio
async def test_no_probe_yet_is_an_empty_list_not_an_error(tmp_path):
    from frago.server.routes.settings import get_workbuddy_models

    with _route(models_path=tmp_path / "none.json", login_path=tmp_path / "none"):
        resp = await get_workbuddy_models()

    assert resp.probed_at is None
    assert resp.models == []
    # 没探过时，菜单上每一个都是「还没探过」——那正是第一轮该走的名单。
    assert [m.id for m in resp.catalog_new] == ["fast", "mid", "dear"]


@pytest.mark.asyncio
async def test_the_dropdown_leads_with_the_cheapest_model(tmp_path):
    """倍率是花多少，是挑模型时先看的那一项；延迟仍然量着，只是不再当显示主角。"""
    from frago.server.routes.settings import get_workbuddy_models

    path = _write_list(
        tmp_path / "workbuddy-models.json",
        [
            {"id": "dear", "ok": True, "first_ms": 200},
            {"id": "fast", "ok": True, "first_ms": 9000},
            {"id": "mid", "ok": True, "first_ms": 500},
        ],
    )
    with _route(models_path=path, login_path=tmp_path / "none"):
        resp = await get_workbuddy_models()

    assert [m.id for m in resp.models] == ["fast", "mid", "dear"]
    assert [m.credits for m in resp.models] == ["x0.03", "x0.50", "x1.20"]
    # 延迟照旧带出来，页面自己决定显不显示。
    assert [m.first_ms for m in resp.models] == [9000, 500, 200]


@pytest.mark.asyncio
async def test_models_the_client_does_not_offer_never_reach_the_dropdown(tmp_path):
    """补全模型、小模型、图像模型在网关名单里，客户端菜单从不列它们。"""
    from frago.server.routes.settings import get_workbuddy_models

    path = _write_list(
        tmp_path / "workbuddy-models.json",
        [
            # 探得最快的三个都不是对话模型——照延迟排的话它们会排在最前面。
            {"id": "codewise-jump", "ok": True, "first_ms": 219},
            {"id": "codewise-rewrite", "ok": True, "first_ms": 226},
            {"id": "hunyuan-image-alpha", "ok": True, "first_ms": 249},
            {"id": "mid", "ok": True, "first_ms": 800},
        ],
    )
    with _route(models_path=path, login_path=tmp_path / "none"):
        resp = await get_workbuddy_models()

    assert [m.id for m in resp.models] == ["mid"]


@pytest.mark.asyncio
async def test_a_model_on_the_menu_but_never_probed_is_named_not_offered(tmp_path):
    """能不能用只有探过才知道，所以只报出来，不进可选项——但要带上倍率。"""
    from frago.server.routes.settings import get_workbuddy_models

    path = _write_list(tmp_path / "workbuddy-models.json", [{"id": "mid", "ok": True}])
    with _route(models_path=path, login_path=tmp_path / "none"):
        resp = await get_workbuddy_models()

    assert [(m.id, m.credits) for m in resp.catalog_new] == [("fast", "x0.03"), ("dear", "x1.20")]
    assert [m.id for m in resp.models] == ["mid"]


@pytest.mark.asyncio
async def test_the_balance_names_the_first_lot_to_expire_not_just_a_total(tmp_path):
    """积分按到期时间从早到晚烧，光报总数会让人以为攒着不会作废。"""
    from frago.server.routes.settings import get_workbuddy_models

    path = _write_list(tmp_path / "workbuddy-models.json", [{"id": "mid", "ok": True}])
    with _route(
        models_path=path,
        login_path=tmp_path / "none",
        balance={"remaining": 685, "expires_at": "2026-09-30", "expiring": 85},
    ):
        resp = await get_workbuddy_models()

    assert resp.balance is not None
    assert (resp.balance.remaining, resp.balance.expires_at, resp.balance.expiring) == (
        685,
        "2026-09-30",
        85,
    )


@pytest.mark.asyncio
async def test_a_balance_that_cannot_be_read_leaves_the_rest_of_the_page_working(tmp_path):
    from frago.server.routes.settings import get_workbuddy_models

    path = _write_list(tmp_path / "workbuddy-models.json", [{"id": "mid", "ok": True}])
    with _route(models_path=path, login_path=tmp_path / "none", balance=None):
        resp = await get_workbuddy_models()

    assert resp.balance is None
    assert [m.id for m in resp.models] == ["mid"]


@pytest.mark.asyncio
async def test_a_client_that_signed_out_is_not_reported_as_logged_in(tmp_path):
    """退出登录时文件还在，令牌字段变空。只看文件在不在，页面会说「已登录」。"""
    from frago.server.routes.settings import get_workbuddy_models

    login = tmp_path / "workbuddy-desktop.info"
    login.write_text(
        json.dumps({"account": {"uid": "u-1"}, "auth": {"accessToken": ""}}), encoding="utf-8"
    )
    with _route(models_path=tmp_path / "none.json", login_path=login):
        resp = await get_workbuddy_models()
    assert (resp.login_state, resp.logged_in) == ("logged_out", False)

    login.write_text(
        json.dumps({"account": {"uid": "u-1"}, "auth": {"accessToken": "tok"}}), encoding="utf-8"
    )
    with _route(models_path=tmp_path / "none.json", login_path=login):
        resp = await get_workbuddy_models()
    assert (resp.login_state, resp.logged_in) == ("ok", True)


@pytest.mark.asyncio
async def test_an_old_list_says_so_and_a_fresh_one_does_not(tmp_path):
    from frago.init.profile_manager import WORKBUDDY_STALE_DAYS
    from frago.server.routes.settings import get_workbuddy_models

    path = _write_list(tmp_path / "workbuddy-models.json", [{"id": "mid", "ok": True}])
    for age_days, expected in ((WORKBUDDY_STALE_DAYS + 1, True), (1, False)):
        written = time.time() - age_days * 86400
        os.utime(path, (written, written))
        with _route(models_path=path, login_path=tmp_path / "none"):
            resp = await get_workbuddy_models()
        assert resp.stale is expected, f"{age_days} 天前探的，stale 应为 {expected}"
        assert resp.stale_after_days == WORKBUDDY_STALE_DAYS


@pytest.mark.asyncio
async def test_probing_without_a_login_is_refused_before_anything_is_spent(tmp_path):
    """探一轮花的是真额度。没登录时对面一个都不会答，起它毫无意义。"""
    from frago.server.routes.settings import probe_workbuddy_models

    binary = tmp_path / "frago-core"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    with (
        patch("frago.server.services.workbuddy_service.core_binary", return_value=binary),
        patch("frago.init.profile_manager.workbuddy_login_path", return_value=tmp_path / "none"),
    ):
        resp = await probe_workbuddy_models()

    assert resp.status == "error"
    assert "登录" in (resp.error or "")


@pytest.mark.asyncio
async def test_probing_without_frago_core_says_so_rather_than_failing_silently(tmp_path):
    from frago.server.routes.settings import probe_workbuddy_models

    with patch(
        "frago.server.services.workbuddy_service.core_binary",
        return_value=tmp_path / "missing",
    ):
        resp = await probe_workbuddy_models()

    assert resp.status == "error"
    assert "frago-core" in (resp.error or "")


def _fake_login(tmp_path):
    login = tmp_path / "workbuddy-desktop.info"
    login.write_text(
        json.dumps({"account": {"uid": "u"}, "auth": {"accessToken": "t"}}), encoding="utf-8"
    )
    return login


def test_a_probe_carries_the_models_the_gateway_roster_would_miss(tmp_path):
    """探测命令只按网关那份名单探，新模型不在里面——不捎上它们，点完探测照样选不到。"""
    from frago.server.services import workbuddy_service

    binary = tmp_path / "frago-core"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    models = _write_list(tmp_path / "workbuddy-models.json", [{"id": "mid", "ok": True}])
    started_with: list[list[str]] = []

    with (
        patch.object(workbuddy_service, "core_binary", return_value=binary),
        patch.object(workbuddy_service, "chat_models", return_value=dict(OFFERED)),
        patch("frago.init.profile_manager.WORKBUDDY_MODELS_PATH", models),
        patch("frago.init.profile_manager.workbuddy_login_path", return_value=_fake_login(tmp_path)),
        patch.object(workbuddy_service, "_run_probe", side_effect=started_with.append),
    ):
        try:
            assert workbuddy_service.start_probe() == (True, None)
        finally:
            with workbuddy_service._probe_lock:
                workbuddy_service._probe.update(running=False, ok=None, error=None)

    # 线程里跑的是同一个被替掉的函数，参数拿得到。
    for _ in range(50):
        if started_with:
            break
        time.sleep(0.01)
    assert started_with, "探测没被起起来"
    argv = started_with[0]
    assert argv[1:3] == ["models", "probe-workbuddy"]
    assert argv[3] == "--also"
    assert sorted(argv[4].split(",")) == ["dear", "fast"]


def test_a_second_probe_is_refused_while_one_is_running(tmp_path):
    """两个进程抢着写同一份清单，写回时互相覆盖，哪一轮的结果都不算。"""
    from frago.server.services import workbuddy_service

    binary = tmp_path / "frago-core"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    with (
        patch.object(workbuddy_service, "core_binary", return_value=binary),
        patch.object(workbuddy_service, "chat_models", return_value={}),
        patch("frago.init.profile_manager.workbuddy_login_path", return_value=_fake_login(tmp_path)),
        patch.object(workbuddy_service, "_run_probe"),
    ):
        try:
            assert workbuddy_service.start_probe() == (True, None)
            started, error = workbuddy_service.start_probe()
        finally:
            with workbuddy_service._probe_lock:
                workbuddy_service._probe.update(running=False, ok=None, error=None)

    assert started is False
    assert "已经在探测" in (error or "")


def test_only_models_with_a_credit_rate_count_as_chat_models(tmp_path):
    """判据是带倍率：补全模型、小模型、图像模型都没有倍率，客户端菜单也不列它们。"""
    from frago.server.services import workbuddy_service

    config = tmp_path / "acc-product-config-v3.json"
    config.write_text(
        json.dumps(
            {
                "models": [
                    {"id": "glm-5.3", "name": "GLM-5.3", "credits": "x0.79"},
                    {"id": "codewise-jump", "name": "codewise-jump"},
                    {"id": "hunyuan-3b", "name": "hunyuan-3b"},
                    {"id": "deepseek-v4.1-flash", "name": "Deepseek-V4.1-Flash", "credits": "x0.03"},
                ]
            }
        ),
        encoding="utf-8",
    )
    with (
        patch.object(workbuddy_service, "PRODUCT_CONFIG", config),
        patch.object(workbuddy_service, "PRODUCT_CONFIG_SPILL", tmp_path / "nope"),
        patch.object(workbuddy_service, "fetch_roster", return_value=None),
    ):
        offered = workbuddy_service.chat_models()

    assert sorted(offered) == ["deepseek-v4.1-flash", "glm-5.3"]
    assert offered["glm-5.3"]["credits_value"] == 0.79


def test_the_menu_falls_back_to_the_newest_historical_copy(tmp_path):
    """客户端只在运行时写当前那份；它读不到时退到同目录里最新的历史副本。"""
    from frago.server.services import workbuddy_service

    spill = tmp_path / "conversation-product-spill"
    spill.mkdir()
    old = spill / "acc-product-config-v3-old.json"
    new = spill / "acc-product-config-v3-new.json"
    old.write_text(json.dumps({"models": [{"id": "stale", "credits": "x9.99"}]}), encoding="utf-8")
    new.write_text(json.dumps({"models": [{"id": "fresh", "credits": "x0.10"}]}), encoding="utf-8")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))

    with (
        patch.object(workbuddy_service, "PRODUCT_CONFIG", tmp_path / "missing.json"),
        patch.object(workbuddy_service, "PRODUCT_CONFIG_SPILL", spill),
        patch.object(workbuddy_service, "fetch_roster", return_value=None),
    ):
        assert sorted(workbuddy_service.chat_models()) == ["fresh"]


def test_the_user_agent_carries_both_versions_because_the_server_keys_on_it():
    """两段都在才拿到带倍率那份名单。只写一段回的是另一份、一个倍率都没有。"""
    from frago.server.services import workbuddy_service

    with patch.object(workbuddy_service, "local_versions", return_value=("5.5.4", "2.137.1")):
        ua = workbuddy_service.user_agent()

    assert ua == "WorkBuddy/5.5.4 CLI/2.137.1"


def test_the_roster_comes_from_the_gateway_and_falls_back_to_the_client_cache(tmp_path):
    """自己去要，客户端不开也能拿到最新的；要不到才退回客户端上次写下的那份。"""
    from frago.server.services import workbuddy_service

    config = tmp_path / "acc-product-config-v3.json"
    config.write_text(
        json.dumps({"models": [{"id": "from-cache", "credits": "x0.50"}]}), encoding="utf-8"
    )
    live = [{"id": "from-gateway", "credits": "x0.10"}]

    with (
        patch.object(workbuddy_service, "PRODUCT_CONFIG", config),
        patch.object(workbuddy_service, "PRODUCT_CONFIG_SPILL", tmp_path / "nope"),
    ):
        with patch.object(workbuddy_service, "fetch_roster", return_value=live):
            assert sorted(workbuddy_service.chat_models()) == ["from-gateway"]
        with patch.object(workbuddy_service, "fetch_roster", return_value=None):
            assert sorted(workbuddy_service.chat_models()) == ["from-cache"]
