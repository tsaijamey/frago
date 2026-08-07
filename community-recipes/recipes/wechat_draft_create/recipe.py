#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""wechat_draft_create — 把内容送进公众号草稿箱，支持文章（图文）与贴图两种类型。

走的是后台编辑器页面上的官方桥 window.__MP_Editor_JSAPI__（微信开给第三方插件用、
有正式文档），吃网页登录态，不碰 AppSecret、不碰 IP 白名单。

- content_type=article（默认）：把排好版的 HTML 送进标准图文编辑器，行内样式一个不掉。
- content_type=poster：送进贴图（createType=8）编辑器，支持标题/描述/多图。

链路：取 token → 打开目标类型编辑器 → 等就绪 → 填内容 → 存前自检 → 点保存
      → 取草稿 ID → 重开回读校验。

每一步等的是条件成立而不是固定时长；任何一步没达成预期都退出码非零，绝不静默成功。
"""

import base64
import json
import re
import subprocess
import sys
import time

from common import (WARNINGS, click_save, die, get_token, log)

from editors import article as article_driver
from editors import poster as poster_driver


def read_html_param(params):
    """取 html_path/content，抽出根容器那一段送进编辑器。"""
    html = params.get("content")
    if not html:
        path = params.get("html_path")
        if not path:
            die("html_path 与 content 至少给一个")
        try:
            with open(path, encoding="utf-8") as f:
                html = f.read()
        except OSError as e:
            die(f"读不到 HTML 文件：{e}")
    # 排版配方产出的是整页 HTML，这里只取根容器那一段送进编辑器。
    m = re.search(r'<section[^>]*id="frago-wechat".*</section>', html, re.S)
    if m:
        html = m.group(0)
    elif "<body" in html:
        m2 = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
        if m2:
            html = m2.group(1).strip()
    if not html.strip():
        die("要送进去的 HTML 是空的")
    return normalize_lists(html)


def normalize_images(params):
    """images 参数可以是单路径字符串或列表。"""
    imgs = params.get("images")
    if not imgs:
        return []
    if isinstance(imgs, str):
        return [imgs]
    if isinstance(imgs, list):
        out = []
        for x in imgs:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict) and x.get("path"):
                out.append(x["path"])
            else:
                die(f"images 项格式不对：{x!r}（应为路径字符串或 {{path}}）")
        return out
    die(f"images 参数格式不对：{type(imgs).__name__}")


# 朴素 <li>纯文本</li> → <li><section style=…>纯文本</section></li>。
# 公众号编辑器对没有 section 包裹的 li 会拆成「空 li + 文字 li」两段，项目符号落在空行上。
# 两个坑都实测过：
#   1) 没有 section 包裹的朴素 li 会被拆分；
#   2) li 之间的换行/缩进空白会被解析成空列表项（canonical 排版输出 li 全在一行所以没事）。
# 排版配方（markdown_to_wechat_html）的标准输出两者都规避，不受影响。
_LI_RE = re.compile(
    r"<li([^>]*)>((?:(?!</li>|</?section|<p[ >]|<div[ >]|<ul[ >]|<ol[ >]|<h[1-6][ >]|<table|<blockquote).)*?)</li>",
    re.S)
_UL_RE = re.compile(r"<ul[^>]*>[\s\S]*?</ul>", re.S)


def _wrap_li(m):
    li_attr = m.group(1)
    sm = re.search(r'style="([^"]*)"', li_attr)
    sec_style = sm.group(1) if sm else ""
    sec_attr = (' style="%s"' % sec_style) if sec_style else ""
    return "<li%s><section%s>%s</section></li>" % (li_attr, sec_attr, m.group(2))


def normalize_lists(html):
    def compact_ul(m):
        inner = re.sub(r">\s+<", "><", m.group(0))
        return inner
    html = _UL_RE.sub(compact_ul, html)
    return _LI_RE.sub(_wrap_li, html)


def run_article(params, group, dry_run, do_verify, appmsgid_in):
    drv = article_driver
    title = (params.get("title") or "").strip()
    if len(title) > drv.TITLE_MAX:
        die(f"标题 {len(title)} 字，超过公众号上限 {drv.TITLE_MAX} 字")
    author = (params.get("author") or "").strip()
    if len(author) > drv.AUTHOR_MAX:
        die(f"作者 {len(author)} 字，超过公众号上限 {drv.AUTHOR_MAX} 字")
    cover = (params.get("cover") or "").strip()
    html = read_html_param(params)
    sent = {
        "len": len(html),
        "styles": len(re.findall(r"style=", html)),
        "tables": len(re.findall(r"<table", html)),
        "images": len(re.findall(r"<img", html)),
        "cover": bool(cover),
    }

    token = get_token(group)
    drv.open_editor(token, group, appmsgid_in)
    drv.wait_editor_ready(group)
    drv.set_title(title, author, group)
    drv.set_content(html, group)
    if cover:
        drv.set_cover(cover, group)
    in_editor = drv.precheck(sent["len"], group)

    if dry_run:
        log("[干跑] 内容已填进编辑器，不点保存")
        return {
            "success": True, "dry_run": True, "appmsgid": appmsgid_in or "",
            "draft_url": drv.current_url(group), "title": title,
            "sent_chars": sent["len"], "stored_chars": in_editor["len"],
            "sent_styles": sent["styles"], "stored_styles": in_editor["styles"],
            "tables": in_editor["tables"], "images": in_editor["images"],
        }

    appmsgid, _ = click_save(group)
    stored = in_editor
    if do_verify:
        stored = drv.verify_stored(token, appmsgid, sent, group)

    return {
        "success": True, "dry_run": False, "appmsgid": appmsgid,
        "draft_url": drv.EDITOR_EDIT.format(appmsgid=appmsgid, token=token),
        "title": title, "cover": cover or "",
        "sent_chars": sent["len"], "stored_chars": stored["len"],
        "sent_styles": sent["styles"], "stored_styles": stored["styles"],
        "tables": stored["tables"], "images": stored["images"],
    }


def run_poster(params, group, dry_run, do_verify, appmsgid_in):
    drv = poster_driver
    title = (params.get("title") or "").strip()
    if not title:
        die("title 必填")
    if len(title) > drv.TITLE_MAX:
        die(f"贴图标题 {len(title)} 字，超过上限 {drv.TITLE_MAX} 字")
    desc = (params.get("description") or "").strip()
    if len(desc) > drv.DESC_MAX:
        die(f"贴图描述 {len(desc)} 字，超过上限 {drv.DESC_MAX} 字")
    image_paths = normalize_images(params)
    if not image_paths and not desc:
        die("贴图至少给 description 或 images 之一，否则存下来是空内容")

    sent = {
        "title": title,
        "desc": desc,
        "images": len(image_paths),
    }

    token = get_token(group)
    drv.open_editor(token, group, appmsgid_in)
    drv.wait_editor_ready(group)
    drv.set_title(title, group)
    if desc:
        drv.set_description(desc, group)
    uploaded, uploaded_info = drv.upload_images(image_paths, group)
    sent["images"] = len(uploaded)
    in_editor = drv.precheck(sent, group)

    if dry_run:
        log("[干跑] 内容已填进贴图编辑器，不点保存")
        return {
            "success": True, "dry_run": True, "appmsgid": appmsgid_in or "",
            "draft_url": drv.current_url(group), "title": title,
            "description": in_editor["desc"], "images": in_editor["images"],
            "uploaded_files": [x.get("file_id") for x in uploaded_info],
        }

    appmsgid, _ = click_save(group)
    stored = in_editor
    if do_verify:
        stored = drv.verify_stored(token, appmsgid, sent, group)

    return {
        "success": True, "dry_run": False, "appmsgid": appmsgid,
        "draft_url": drv.EDITOR_EDIT.format(appmsgid=appmsgid, token=token),
        "title": title,
        "description": stored["desc"], "images": stored["images"],
        "uploaded_files": [x.get("file_id") for x in uploaded_info],
    }


def main():
    started = time.time()
    params = {}
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            die(f"参数解析失败：{e}")

    content_type = (params.get("content_type") or "article").strip().lower()
    group = params.get("browser_group") or "wechat_draft"
    dry_run = bool(params.get("dry_run"))
    do_verify = params.get("verify", True)
    appmsgid_in = params.get("appmsgid")

    try:
        if content_type == "poster":
            result = run_poster(params, group, dry_run, do_verify, appmsgid_in)
        elif content_type == "article":
            result = run_article(params, group, dry_run, do_verify, appmsgid_in)
        else:
            die(f"content_type 不认识：{content_type}",
                "支持 article（默认）与 poster（贴图）两种。")
    except SystemExit:
        raise

    result["elapsed_sec"] = round(time.time() - started, 1)
    result["warnings"] = WARNINGS
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired as e:
        die(f"浏览器命令超时：{e}")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        die(f"未预期的错误：{type(e).__name__}: {e}")
