"""配方被重写之前，原件必须留得下来。

create / plan 是照规格把整份配方重新铺一遍，模板的覆盖范围包括 recipe.py、
recipe.md 与 assets/ 下的页面。规格里字段名改了一个（sentences→lines），
页面照旧按老名字读数，打开就是个空壳，而命令全程不报警——2026-09-06 两次事故
是把页面从会话记录里逐条重放才捞回来的。

这里守两件事：①重写前留一份能还原的原件，并把副本落在哪说出来；②plan 的
spec.md 落在配方自己的目录里，不另外造一个同名的空壳目录。
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from frago.cli import recipe_commands
from frago.cli.recipe_commands import SNAPSHOT_ROOT, recipe_group

MATURE_PAGE = "<html><body>213 句台词按 sentences 读数</body></html>\n"

SPEC = """# demo

```yaml
type: atomic
modes:
  fetch: export
page: true
```
"""


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """把 ~ 指到临时目录，配方目录跟着走。"""
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(recipe_commands, '_run_frago_agent', lambda *a, **kw: 0)
    (tmp_path / '.frago' / 'recipes' / 'atomic' / 'system').mkdir(parents=True)
    (tmp_path / '.frago' / 'recipes' / 'workflows').mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _mature_recipe(home, name: str, subdir: str = 'atomic/system'):
    d = home / '.frago' / 'recipes' / subdir / name
    (d / 'assets').mkdir(parents=True)
    (d / 'recipe.md').write_text(f'---\nname: {name}\ntype: atomic\n---\n', encoding='utf-8')
    (d / 'recipe.py').write_text('# 成熟实现，别被骨架冲掉\n', encoding='utf-8')
    (d / 'assets' / 'index.html').write_text(MATURE_PAGE, encoding='utf-8')
    (d / 'spec.md').write_text(SPEC, encoding='utf-8')
    return d


def test_force_create_keeps_the_originals(runner, home) -> None:
    d = _mature_recipe(home, 'demo_recipe')
    result = runner.invoke(recipe_group, ['create', 'demo_recipe', '--force'])
    assert result.exit_code == 0, result.output

    # 模板确实盖掉了原页面——这条闸管的是「留得下来」，不是「不许覆盖」
    assert (d / 'assets' / 'index.html').read_text(encoding='utf-8') != MATURE_PAGE

    snapshots = list((home / '.frago' / 'recipes' / SNAPSHOT_ROOT / 'demo_recipe').iterdir())
    assert len(snapshots) == 1
    assert (snapshots[0] / 'assets' / 'index.html').read_text(encoding='utf-8') == MATURE_PAGE
    assert (snapshots[0] / 'recipe.py').read_text(encoding='utf-8').startswith('# 成熟实现')
    assert str(snapshots[0]) in result.output


def test_create_without_force_refuses_and_writes_nothing(runner, home) -> None:
    d = _mature_recipe(home, 'demo_recipe')
    result = runner.invoke(recipe_group, ['create', 'demo_recipe'])
    assert result.exit_code != 0, result.output
    assert (d / 'assets' / 'index.html').read_text(encoding='utf-8') == MATURE_PAGE
    assert not (home / '.frago' / 'recipes' / SNAPSHOT_ROOT).exists()


def test_plan_lands_in_the_existing_recipe_dir(runner, home) -> None:
    d = _mature_recipe(home, 'demo_flow', subdir='workflows')
    result = runner.invoke(recipe_group, ['plan', 'demo_flow', '--prompt', '随便什么需求', '--force'])
    assert result.exit_code == 0, result.output
    assert (d / 'spec.md').exists()
    assert not (home / '.frago' / 'recipes' / 'atomic' / 'system' / 'demo_flow').exists()


def test_snapshot_is_skipped_for_an_empty_landing_dir(tmp_path, monkeypatch, home) -> None:
    empty = home / '.frago' / 'recipes' / 'workflows' / 'brand_new'
    empty.mkdir()
    assert recipe_commands._snapshot_recipe_dir(empty) is None
    assert recipe_commands._snapshot_recipe_dir(home / 'nowhere') is None
