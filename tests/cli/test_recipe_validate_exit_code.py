"""recipe validate 的退出码契约。

validate 是"产出判断"的守卫命令，退出码本身就是被测对象：
CI / set -e / A && B / agent 都只认退出码，非法 recipe 必须退非零。
"""

from __future__ import annotations

import json
import textwrap

import pytest
from click.testing import CliRunner

from frago.cli.recipe_commands import recipe_group

VALID_FRONTMATTER = textwrap.dedent(
    """\
    ---
    name: demo_recipe
    type: atomic
    runtime: python
    version: "1.0"
    description: A demo recipe used by exit-code tests
    use_cases:
      - demo
    output_targets:
      - stdout
    ---

    # Demo
    """
)


def _write_recipe(base, frontmatter: str = VALID_FRONTMATTER, script: str = 'print("hi")\n'):
    base.mkdir(parents=True, exist_ok=True)
    (base / 'recipe.md').write_text(frontmatter, encoding='utf-8')
    (base / 'recipe.py').write_text(script, encoding='utf-8')
    return base


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_valid_recipe_exits_zero(runner, tmp_path) -> None:
    d = _write_recipe(tmp_path / 'ok')
    result = runner.invoke(recipe_group, ['validate', str(d)])
    assert result.exit_code == 0, result.output


def test_missing_frontmatter_exits_nonzero(runner, tmp_path) -> None:
    d = _write_recipe(tmp_path / 'nofm', frontmatter='# no frontmatter here\n')
    result = runner.invoke(recipe_group, ['validate', str(d)])
    assert result.exit_code != 0, result.output


def test_missing_required_field_exits_nonzero(runner, tmp_path) -> None:
    broken = VALID_FRONTMATTER.replace('runtime: python\n', '')
    d = _write_recipe(tmp_path / 'nofield', frontmatter=broken)
    result = runner.invoke(recipe_group, ['validate', str(d)])
    assert result.exit_code != 0, result.output


def test_warning_only_recipe_exits_zero(runner, tmp_path) -> None:
    d = _write_recipe(tmp_path / 'warn')
    (d / 'examples').mkdir()  # empty examples dir -> warning, not error
    result = runner.invoke(recipe_group, ['validate', str(d)])
    assert result.exit_code == 0, result.output
    assert 'Warnings' in result.output


def test_invalid_recipe_json_format_exits_nonzero_and_prints_json(runner, tmp_path) -> None:
    d = _write_recipe(tmp_path / 'jsonbad', frontmatter='# no frontmatter here\n')
    result = runner.invoke(recipe_group, ['validate', str(d), '--format', 'json'])
    assert result.exit_code != 0, result.output
    payload = json.loads(result.stdout)
    assert payload['valid'] is False
    assert payload['errors']


def test_valid_recipe_json_format_exits_zero(runner, tmp_path) -> None:
    d = _write_recipe(tmp_path / 'jsonok')
    result = runner.invoke(recipe_group, ['validate', str(d), '--format', 'json'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['valid'] is True


def test_missing_recipe_md_exits_nonzero(runner, tmp_path) -> None:
    d = tmp_path / 'empty'
    d.mkdir()
    result = runner.invoke(recipe_group, ['validate', str(d)])
    assert result.exit_code != 0, result.output


def test_wrong_file_name_exits_nonzero(runner, tmp_path) -> None:
    d = _write_recipe(tmp_path / 'wrongfile')
    result = runner.invoke(recipe_group, ['validate', str(d / 'recipe.py')])
    assert result.exit_code != 0, result.output
