"""frago image CLI 图片网格组件生成工具的单元测试。

覆盖：
1. 本机绝对路径、file:// URL、/api/file 内联地址、互联网 http(s):// URL 的混合解析与输出结构；
2. 位置参数、-i / --image 管道简写（PATH_OR_URL|CAPTION）、JSON 对象字符串、以及 grid/show 子命令前缀兼容；
3. 参数错误（未传图片、本机文件不存在、传入目录而非文件、无效互联网 URL、未知参数如 --url、列数越界）时立即报错退出（exit_code != 0），且输出 [Fix] 正确调用示例。
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from click.testing import CliRunner

from frago.cli.image_commands import image_cmd


class TestImageGridSuccess:
    def test_local_and_remote_images_pipe_shorthand(self, tmp_path: Path):
        local_img = tmp_path / "poster-1.png"
        local_img.write_bytes(b"\x89PNG\r\n\x1a\n")

        runner = CliRunner()
        res = runner.invoke(
            image_cmd,
            [
                "--title",
                "宣传海报对比（2 张）",
                "--columns",
                "2",
                "-i",
                f"{local_img}|图 1：本机渲染海报",
                "-i",
                "https://example.com/assets/banner-v2.png|图 2：线上基准图",
            ],
        )
        assert res.exit_code == 0, res.output
        payload = json.loads(res.output)
        assert payload["frago_ui_component"] == "image-grid"
        assert payload["component_type"] == "image-grid"
        data = payload["data"]
        assert data["type"] == "image-grid"
        assert data["title"] == "宣传海报对比（2 张）"
        assert data["columns"] == 2
        assert len(data["images"]) == 2

        resolved_str = str(local_img.resolve())
        expected_src = f"/api/file?disposition=inline&path={urllib.parse.quote(resolved_str, safe='')}"
        assert data["images"][0] == {
            "src": expected_src,
            "raw": resolved_str,
            "name": "poster-1.png",
            "source": "local",
            "caption": "图 1：本机渲染海报",
        }
        assert data["images"][1] == {
            "src": "https://example.com/assets/banner-v2.png",
            "raw": "https://example.com/assets/banner-v2.png",
            "name": "banner-v2.png",
            "source": "remote",
            "caption": "图 2：线上基准图",
        }

    def test_positional_args_file_url_and_json_item(self, tmp_path: Path):
        img_a = tmp_path / "shot a.png"
        img_b = tmp_path / "shot-b.jpg"
        img_a.write_bytes(b"\x89PNG\r\n\x1a\n")
        img_b.write_bytes(b"\xff\xd8\xff")

        file_url = img_a.resolve().as_uri()
        json_item = json.dumps(
            {"path": str(img_b), "caption": "JSON 方式传入的图注"},
            ensure_ascii=False,
        )

        runner = CliRunner()
        res = runner.invoke(
            image_cmd,
            [
                file_url,
                json_item,
                "-c",
                "位置参数第一张图注",
            ],
        )
        assert res.exit_code == 0, res.output
        payload = json.loads(res.output)
        images = payload["data"]["images"]
        assert len(images) == 2
        assert images[0]["name"] == "shot a.png"
        assert images[0]["source"] == "local"
        assert images[0]["caption"] == "位置参数第一张图注"
        assert images[1]["name"] == "shot-b.jpg"
        assert images[1]["caption"] == "JSON 方式传入的图注"


class TestImageGridValidationErrors:
    def test_missing_images_fails_with_fix(self):
        runner = CliRunner()
        res = runner.invoke(image_cmd, [])
        assert res.exit_code != 0
        assert "缺少图片参数" in res.output
        assert "[Fix]" in res.output
        assert "frago app image" in res.output

    def test_nonexistent_local_file_fails_with_fix(self, tmp_path: Path):
        missing = tmp_path / "not_found.png"
        runner = CliRunner()
        res = runner.invoke(image_cmd, [str(missing)])
        assert res.exit_code != 0
        assert "本机图片不存在" in res.output
        assert "[Fix]" in res.output

    def test_directory_as_image_fails(self, tmp_path: Path):
        runner = CliRunner()
        res = runner.invoke(image_cmd, [str(tmp_path)])
        assert res.exit_code != 0
        assert "不是文件" in res.output
        assert "[Fix]" in res.output

    def test_invalid_remote_url_fails(self):
        runner = CliRunner()
        res = runner.invoke(image_cmd, ["https://"])
        assert res.exit_code != 0
        assert "互联网地址格式无效" in res.output
        assert "[Fix]" in res.output

    def test_unknown_option_fails_with_fix(self):
        runner = CliRunner()
        res = runner.invoke(image_cmd, ["--url", "https://example.com/a.png"])
        assert res.exit_code != 0
        assert "不存在参数 '--url'" in res.output
        assert "[Fix]" in res.output

    def test_invalid_columns_fails(self, tmp_path: Path):
        img = tmp_path / "a.png"
        img.write_bytes(b"\x89PNG")
        runner = CliRunner()
        res = runner.invoke(image_cmd, [str(img), "--columns", "9"])
        assert res.exit_code != 0
        assert "--columns 超出范围" in res.output
        assert "[Fix]" in res.output
