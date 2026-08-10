"""`recipe open` 的参数契约。

这条命令一度把任何字符串都交给系统默认浏览器，包括配方名。macOS 的
默认浏览器拿到不带 scheme 的裸词只会开一个空白页，而命令照样打印
"Opened in default browser" 并退 0——调用方拿到成功回执，人拿到白页。

所以被测的是两件事：配方名要能开（agent 手里通常只有名字），开不了的
东西必须退非零，NEVER 假报成功。
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from frago.cli.recipe_commands import recipe_group
from frago.recipes import app_state


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def app_state_dir(tmp_path, monkeypatch):
    """把 app-state 根目录挪到 tmp，别碰用户真实的 ~/.frago/app-state。"""
    root = tmp_path / 'app-state'
    monkeypatch.setattr(app_state, 'APP_STATE_DIR', root)
    return root


@pytest.fixture()
def opened(monkeypatch) -> list[str]:
    """拦住真正的开浏览器动作，只记录它收到的地址。"""
    calls: list[str] = []

    def fake_open(url: str) -> bool:
        calls.append(url)
        return True

    monkeypatch.setattr('webbrowser.open', fake_open)
    return calls


def _publish(root, name: str, slot: str = 'default') -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f'{slot}.json').write_text(json.dumps({'ok': True}), encoding='utf-8')


def test_recipe_name_expands_to_page_url(runner, app_state_dir, opened) -> None:
    _publish(app_state_dir, 'demo_recipe')
    result = runner.invoke(recipe_group, ['open', 'demo_recipe'])
    assert result.exit_code == 0, result.output
    assert opened == ['http://localhost:8093/app/demo_recipe']


def test_slot_becomes_query_string(runner, app_state_dir, opened) -> None:
    _publish(app_state_dir, 'demo_recipe', slot='2024-2025')
    result = runner.invoke(recipe_group, ['open', 'demo_recipe', '--slot', '2024-2025'])
    assert result.exit_code == 0, result.output
    assert opened == ['http://localhost:8093/app/demo_recipe?key=2024-2025']


@pytest.mark.usefixtures('app_state_dir')
def test_full_url_passes_through_untouched(runner, opened) -> None:
    url = 'http://localhost:8093/app/demo_recipe?key=x'
    result = runner.invoke(recipe_group, ['open', url])
    assert result.exit_code == 0, result.output
    assert opened == [url]


@pytest.mark.usefixtures('app_state_dir')
def test_unpublished_recipe_is_refused_not_opened(runner, opened) -> None:
    result = runner.invoke(recipe_group, ['open', 'never_ran'])
    assert result.exit_code != 0, result.output
    assert opened == []
    assert 'frago recipe run never_ran' in result.output


def test_unknown_slot_lists_the_published_ones(runner, app_state_dir, opened) -> None:
    _publish(app_state_dir, 'demo_recipe', slot='2024-2025')
    result = runner.invoke(recipe_group, ['open', 'demo_recipe', '--slot', 'nope'])
    assert result.exit_code != 0, result.output
    assert opened == []
    assert '2024-2025' in result.output


@pytest.mark.usefixtures('app_state_dir')
def test_bare_host_port_is_refused(runner, opened) -> None:
    """localhost:8093/... 会被 urlsplit 读成 scheme=localhost，不能放过去。"""
    result = runner.invoke(recipe_group, ['open', 'localhost:8093/app/demo'])
    assert result.exit_code != 0, result.output
    assert opened == []


@pytest.mark.usefixtures('app_state_dir')
def test_path_shaped_target_is_refused(runner, opened) -> None:
    result = runner.invoke(recipe_group, ['open', 'app/demo_recipe'])
    assert result.exit_code != 0, result.output
    assert opened == []


@pytest.mark.usefixtures('app_state_dir')
def test_slot_with_full_url_is_refused(runner, opened) -> None:
    result = runner.invoke(
        recipe_group,
        ['open', 'http://localhost:8093/app/demo', '--slot', 'x'],
    )
    assert result.exit_code != 0, result.output
    assert opened == []


def test_browser_refusal_still_exits_nonzero(runner, app_state_dir, monkeypatch) -> None:
    _publish(app_state_dir, 'demo_recipe')
    monkeypatch.setattr('webbrowser.open', lambda _url: False)
    result = runner.invoke(recipe_group, ['open', 'demo_recipe'])
    assert result.exit_code != 0, result.output
