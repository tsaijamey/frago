"""内置 Excel 工作簿原位读写与公式求值能力（``frago app xlsx``）。

直接对本机任意路径的 ``.xlsx`` 文件执行只读元信息检查（``inspect``）、工作表读取与
公式当场求值（``sheet``）、新建空白工作簿（``create``）、二进制导入（``write-bytes``）
以及带指纹对账（``base_rev``）与整表公式平移的原位原子保存（``save``）。

配方在沙箱内通过 ``self.ask_frago(["app", "xlsx", ...])`` 调用本模块，无需将用户的
``.xlsx`` 复制到配方自身的数据目录，彻底消除副本脱钩与同名文件重复打开报错。
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import io
import json
import re
import shutil
import sys
import zipfile
from copy import copy
from pathlib import Path
from typing import Any

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup, BusinessError

#: 每个工作簿在备份目录最多保留最近几版。
KEEP_BACKUPS = 3

#: sheet 默认一次读取的行数。
DEFAULT_ROWS = 200

#: 单个区间求值最多扫描的单元格数。
MAX_SPAN_CELLS = 200_000

#: 求值器支持的函数集合。
FUNCS = ("SUM", "AVERAGE", "COUNT", "MIN", "MAX")

REF_ERR = "#REF!"

_ONE = r"\$?[A-Za-z]{1,3}\$?[0-9]{1,7}"

_PIECE = re.compile(
    r'(?P<text>"(?:[^"]|"")*")'
    r"|(?P<cross>(?:'[^']*'|[A-Za-z_一-鿿][\w一-鿿.]*)"
    r"!\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)"
    r"|(?P<broken>#(?:REF|DIV/0|NAME|VALUE|N/A|NUM|NULL)[!?])"
    rf"|(?P<span>(?<![\w$!.]){_ONE}:{_ONE}(?![\w(]))"
    rf"|(?P<cell>(?<![\w$!.]){_ONE}(?![\w(]))"
)

_ONE_PARTS = re.compile(r"(\$?)([A-Za-z]{1,3})(\$?)(\d+)")


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letter(index: int) -> int | str:
    out = ""
    while index > 0:
        index, rest = divmod(index - 1, 26)
        out = chr(65 + rest) + out
    return out


def take_ref(raw: str) -> tuple[str, int, str, int]:
    """``$B$7`` -> ``('$', 2, '$', 7)``。"""
    m = _ONE_PARTS.fullmatch(raw)
    if m is None:
        raise ValueError(raw)
    return m.group(1), col_index(m.group(2)), m.group(3), int(m.group(4))


def make_ref(cd: str, col: int, rd: str, row: int) -> str:
    return f"{cd}{col_letter(col)}{rd}{row}"


def move_one(col: int, row: int, axis: str, kind: str, at: int) -> tuple[int, int] | None:
    if axis == "col":
        if kind == "insert":
            return (col + 1 if col >= at else col), row
        if col == at:
            return None
        return (col - 1 if col > at else col), row
    if kind == "insert":
        return col, (row + 1 if row >= at else row)
    if row == at:
        return None
    return col, (row - 1 if row > at else row)


def move_span(lo: int, hi: int, kind: str, at: int) -> tuple[int, int] | None:
    if kind == "insert":
        return (lo + 1 if lo >= at else lo), (hi + 1 if hi >= at else hi)
    if lo == at and hi == at:
        return None
    if lo > at:
        return lo - 1, hi - 1
    if hi > at:
        return lo, hi - 1
    return lo, hi


def shift_text(text: str, axis: str, kind: str, at: int) -> tuple[str, bool]:
    """将公式中的引用按行列插入/删除平移。返回 ``(新公式, 是否含跨表引用)``。"""
    out: list[str] = []
    cross = False
    pos = 0
    for m in _PIECE.finditer(text):
        out.append(text[pos : m.start()])
        pos = m.end()
        raw = m.group()
        which = m.lastgroup
        if which == "cross":
            cross = True
            out.append(raw)
        elif which in ("text", "broken"):
            out.append(raw)
        elif which == "span":
            a, b = raw.split(":")
            acd, acol, ard, arow = take_ref(a)
            bcd, bcol, brd, brow = take_ref(b)
            lo_c, hi_c = min(acol, bcol), max(acol, bcol)
            lo_r, hi_r = min(arow, brow), max(arow, brow)
            if axis == "col":
                moved = move_span(lo_c, hi_c, kind, at)
                if moved is None:
                    out.append(REF_ERR)
                    continue
                lo_c, hi_c = moved
            else:
                moved = move_span(lo_r, hi_r, kind, at)
                if moved is None:
                    out.append(REF_ERR)
                    continue
                lo_r, hi_r = moved
            out.append(f"{make_ref(acd, lo_c, ard, lo_r)}:{make_ref(bcd, hi_c, brd, hi_r)}")
        else:
            cd, col, rd, row = take_ref(raw)
            moved = move_one(col, row, axis, kind, at)
            out.append(REF_ERR if moved is None else make_ref(cd, moved[0], rd, moved[1]))
    out.append(text[pos:])
    return "".join(out), cross


def offset_text(text: str, dr: int, dc: int) -> str:
    """粘贴时的相对引用位移平移（带 ``$`` 的绝对引用保持不动）。"""
    out: list[str] = []
    pos = 0
    for m in _PIECE.finditer(text):
        out.append(text[pos : m.start()])
        pos = m.end()
        raw = m.group()
        which = m.lastgroup
        if which in ("text", "broken", "cross"):
            out.append(raw)
            continue
        parts = raw.split(":") if which == "span" else [raw]
        moved: list[str] | None = []
        for one in parts:
            cd, col, rd, row = take_ref(one)
            col = col if cd else col + dc
            row = row if rd else row + dr
            if col < 1 or row < 1:
                moved = None
                break
            moved.append(make_ref(cd, col, rd, row))
        out.append(REF_ERR if moved is None else ":".join(moved))
    out.append(text[pos:])
    return "".join(out)


class _Unsupported(Exception):
    """公式超出内置求值范围，保留公式原文不动。"""


_LEX = re.compile(
    r"""\s+
      | (?P<num>\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|\.\d+)
      | (?P<span>\$?[A-Za-z]{1,3}\$?\d+:\$?[A-Za-z]{1,3}\$?\d+)(?![\w(])
      | (?P<cell>\$?[A-Za-z]{1,3}\$?\d+)(?![\w(])
      | (?P<name>[A-Za-z][A-Za-z0-9_.]*)
      | (?P<op>[-+*/^(),])
    """,
    re.X,
)


def _lex(body: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(body):
        m = _LEX.match(body, pos)
        if m is None:
            raise _Unsupported(body[pos:])
        pos = m.end()
        if m.lastgroup is not None:
            tokens.append((m.lastgroup, m.group()))
    return tokens


class _Parse:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.tokens = tokens
        self.i = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def eat(self, text: str | None = None) -> tuple[str, str]:
        tok = self.peek()
        if tok is None or (text is not None and tok[1] != text):
            raise _Unsupported(text or "结尾")
        self.i += 1
        return tok

    def expr(self):
        node = self.term()
        while (tok := self.peek()) and tok[1] in ("+", "-"):
            self.eat()
            node = ("bin", tok[1], node, self.term())
        return node

    def term(self):
        node = self.power()
        while (tok := self.peek()) and tok[1] in ("*", "/"):
            self.eat()
            node = ("bin", tok[1], node, self.power())
        return node

    def power(self):
        node = self.unary()
        if (tok := self.peek()) and tok[1] == "^":
            self.eat()
            node = ("bin", "^", node, self.power())
        return node

    def unary(self):
        tok = self.peek()
        if tok and tok[1] in ("+", "-"):
            self.eat()
            return ("neg", self.unary()) if tok[1] == "-" else self.unary()
        return self.primary()

    def primary(self):
        tok = self.peek()
        if tok is None:
            raise _Unsupported("结尾")
        kind, raw = tok
        if kind == "num":
            self.eat()
            return ("num", float(raw))
        if kind == "cell":
            self.eat()
            _, col, _, row = take_ref(raw)
            return ("cell", col, row)
        if kind == "span":
            self.eat()
            a, b = raw.split(":")
            _, ac, _, ar = take_ref(a)
            _, bc, _, br = take_ref(b)
            return ("span", min(ac, bc), min(ar, br), max(ac, bc), max(ar, br))
        if kind == "name":
            name = raw.upper()
            if name not in FUNCS:
                raise _Unsupported(raw)
            self.eat()
            self.eat("(")
            args = []
            if (nxt := self.peek()) and nxt[1] == ")":
                self.eat(")")
                return ("fn", name, args)
            args.append(self.expr())
            while (nxt := self.peek()) and nxt[1] == ",":
                self.eat()
                args.append(self.expr())
            self.eat(")")
            return ("fn", name, args)
        if raw == "(":
            self.eat()
            node = self.expr()
            self.eat(")")
            return node
        raise _Unsupported(raw)


def compiles(formula: str):
    body = formula[1:] if formula.startswith("=") else formula
    parser = _Parse(_lex(body))
    node = parser.expr()
    if parser.peek() is not None:
        raise _Unsupported(parser.peek()[1])
    return node


def parseable(formula: str) -> bool:
    try:
        compiles(formula)
    except (_Unsupported, ValueError):
        return False
    return True


class SheetEvaluator:
    """单张工作表上的公式求值器（求值结果只用于返回展示，绝不写回单元格）。"""

    def __init__(self, ws):
        self.ws = ws
        self.busy: set[tuple[int, int]] = set()
        self.done: dict[tuple[int, int], tuple] = {}

    def at(self, col: int, row: int) -> tuple:
        key = (col, row)
        if key in self.busy:
            return ("err", "cycle")
        if key in self.done:
            return self.done[key]
        if row > self.ws.max_row or col > self.ws.max_column:
            return ("empty", None)
        raw = self.ws.cell(row=row, column=col).value
        if raw is None:
            got: tuple = ("empty", None)
        elif isinstance(raw, str) and raw.startswith("="):
            self.busy.add(key)
            try:
                got = self.formula(raw)
            finally:
                self.busy.discard(key)
        elif isinstance(raw, bool):
            got = ("bool", raw)
        elif isinstance(raw, (int, float)):
            got = ("num", float(raw))
        elif isinstance(raw, (dt.datetime, dt.date, dt.time)):
            got = ("date", raw)
        else:
            got = ("text", str(raw))
        if not (got[0] == "err" and got[1] == "cycle"):
            self.done[key] = got
        return got

    def formula(self, text: str) -> tuple:
        try:
            node = compiles(text)
        except (_Unsupported, ValueError):
            return ("err", "unsupported")
        return self.walk(node)

    def walk(self, node) -> tuple:
        kind = node[0]
        if kind == "num":
            return ("num", node[1])
        if kind == "cell":
            return self.as_number(self.at(node[1], node[2]))
        if kind == "span":
            return ("err", "unsupported")
        if kind == "neg":
            got = self.walk(node[1])
            return got if got[0] == "err" else ("num", -got[1])
        if kind == "bin":
            return self.binary(node[1], node[2], node[3])
        return self.call(node[1], node[2])

    @staticmethod
    def as_number(got: tuple) -> tuple:
        if got[0] == "num":
            return got
        if got[0] == "empty":
            return ("num", 0.0)
        if got[0] == "err":
            return got
        return ("err", "value")

    def binary(self, op: str, left, right) -> tuple:
        a = self.walk(left)
        if a[0] == "err":
            return a
        b = self.walk(right)
        if b[0] == "err":
            return b
        x, y = a[1], b[1]
        if op == "+":
            return ("num", x + y)
        if op == "-":
            return ("num", x - y)
        if op == "*":
            return ("num", x * y)
        if op == "/":
            return ("err", "div0") if y == 0 else ("num", x / y)
        try:
            return ("num", float(x**y))
        except (OverflowError, ValueError, ZeroDivisionError):
            return ("err", "value")

    def span_numbers(self, node) -> tuple[list[float], str | None]:
        _, c1, r1, c2, r2 = node
        if (c2 - c1 + 1) * (r2 - r1 + 1) > MAX_SPAN_CELLS:
            return [], "unsupported"
        nums: list[float] = []
        for col in range(c1, c2 + 1):
            for row in range(r1, r2 + 1):
                got = self.at(col, row)
                if got[0] == "err":
                    return [], got[1]
                if got[0] == "num":
                    nums.append(got[1])
        return nums, None

    def call(self, name: str, args) -> tuple:
        nums: list[float] = []
        for arg in args:
            if arg[0] == "span":
                got, err = self.span_numbers(arg)
                if err:
                    return ("err", err)
                nums.extend(got)
            elif arg[0] == "cell":
                one = self.at(arg[1], arg[2])
                if one[0] == "err":
                    return one
                if one[0] == "num":
                    nums.append(one[1])
            else:
                one = self.walk(arg)
                if one[0] == "err":
                    return one
                nums.append(one[1])
        if name == "SUM":
            return ("num", float(sum(nums)))
        if name == "COUNT":
            return ("num", float(len(nums)))
        if name == "AVERAGE":
            return ("err", "div0") if not nums else ("num", sum(nums) / len(nums))
        if name == "MIN":
            return ("num", min(nums) if nums else 0.0)
        return ("num", max(nums) if nums else 0.0)

    def show(self, text: str) -> dict[str, Any]:
        got = self.formula(text)
        if got[0] == "err":
            return {"v": None, "err": got[1]}
        value = round(got[1], 10)
        return {"v": int(value) if float(value).is_integer() else value, "err": None}


def compute_rev(path: Path) -> str:
    """计算文件全部字节的 sha256 前 16 位指纹。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def resolve_target_path(raw: str) -> Path:
    text = (raw or "").strip()
    if not text:
        raise BusinessError(
            "文件路径不能为空。",
            "frago app xlsx inspect /path/to/workbook.xlsx",
        )
    p = Path(text).expanduser()
    return p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()


def inspect_one(path: Path) -> dict[str, Any]:
    """只读检查单个 .xlsx 文件的元信息与工作表列表，不改动任何字节。"""
    from openpyxl import load_workbook

    info: dict[str, Any] = {
        "path": str(path),
        "file": path.name,
        "folder": path.parent.name,
        "exists": False,
        "ok": False,
        "bytes": 0,
        "modified": "",
        "rev": "",
        "sheets": 0,
        "sheet_names": [],
        "error": "",
    }
    if not path.exists() or not path.is_file():
        info["error"] = f"文件不存在：{path}"
        return info

    stat = path.stat()
    info["exists"] = True
    info["bytes"] = stat.st_size
    info["modified"] = dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    info["rev"] = compute_rev(path)
    try:
        wb = load_workbook(path)
        info["sheet_names"] = list(wb.sheetnames)
        info["sheets"] = len(wb.sheetnames)
        info["ok"] = True
        wb.close()
    except Exception as err:
        info["ok"] = False
        info["error"] = str(err)
    return info


def read_sheet_data(
    path: Path,
    sheet_name: str | None = None,
    top_row: int = 1,
    rows: int = DEFAULT_ROWS,
) -> dict[str, Any]:
    """原位读取指定工作簿的工作表内容与公式求值结果（只读，一个字节都不写）。"""
    from openpyxl import load_workbook

    if not path.is_file():
        raise BusinessError(
            f"工作簿文件不存在：{path}",
            f"frago app xlsx inspect {path}",
        )

    rev = compute_rev(path)
    try:
        wb = load_workbook(path)
    except Exception as err:
        raise BusinessError(
            f"{path.name} 读不动：{err}。文件本身打不开（不是 zip 或结构损坏），原文未改动。",
        ) from err

    try:
        if not sheet_name:
            ws = wb[wb.sheetnames[0]]
        elif sheet_name not in wb.sheetnames:
            raise BusinessError(
                f"工作簿 {path.name} 里没有工作表 {sheet_name}。现有的是：{'、'.join(wb.sheetnames)}",
            )
        else:
            ws = wb[sheet_name]

        top = max(1, int(top_row or 1))
        span = max(1, int(rows or DEFAULT_ROWS))
        last = min(ws.max_row, top + span - 1)

        sums = SheetEvaluator(ws)
        cells: dict[str, dict[str, Any]] = {}
        for row in ws.iter_rows(min_row=top, max_row=last):
            for cell in row:
                raw = cell.value
                if raw is None and not cell.has_style:
                    continue
                one: dict[str, Any] = {
                    "fmt": cell.number_format,
                    "b": bool(cell.font.bold),
                    "i": bool(cell.font.italic),
                    "a": cell.alignment.horizontal or "",
                }
                if isinstance(raw, str) and raw.startswith("="):
                    one["t"] = "f"
                    one["f"] = raw
                    one["calc"] = sums.show(raw)
                elif raw is None:
                    one["t"] = "e"
                elif isinstance(raw, bool):
                    one["t"] = "b"
                    one["v"] = raw
                elif isinstance(raw, (int, float)):
                    one["t"] = "n"
                    one["v"] = raw
                elif isinstance(raw, (dt.datetime, dt.date, dt.time)):
                    one["t"] = "d"
                    one["v"] = raw.isoformat()
                else:
                    one["t"] = "s"
                    one["v"] = str(raw)
                cells[cell.coordinate] = one

        widths = {}
        for letter, dim in ws.column_dimensions.items():
            if dim.width:
                widths[letter] = round(float(dim.width), 2)

        return {
            "ok": True,
            "file": path.name,
            "path": str(path),
            "folder": path.parent.name,
            "rev": rev,
            "sheet": ws.title,
            "sheets": list(wb.sheetnames),
            "top_row": top,
            "rows": last - top + 1 if last >= top else 0,
            "max_row": ws.max_row,
            "max_col": ws.max_column,
            "cells": cells,
            "col_widths": widths,
            "merges": [str(one) for one in ws.merged_cells.ranges],
            "frozen": ws.freeze_panes or "",
        }
    finally:
        wb.close()


def _atomic_save_workbook(wb, path: Path) -> None:
    """在目标文件同目录写临时文件再原子替换，确保原文件永远完整。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    half = path.parent / f".{path.name}.writing"
    try:
        wb.save(half)
        half.replace(path)
    except OSError as err:
        half.unlink(missing_ok=True)
        raise BusinessError(
            f"写盘失败：{err}。原文件一个字节没动。",
        ) from err


def _backup_before_write(path: Path, rev: str, backup_dir: Path | None) -> None:
    if backup_dir is None or not path.is_file():
        return
    backup_dir.mkdir(parents=True, exist_ok=True)
    prefix = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:8]
    shutil.copy2(path, backup_dir / f"{path.name}.{prefix}.{rev}.xlsx")
    kept = sorted(
        backup_dir.glob(f"{path.name}.{prefix}.*.xlsx"),
        key=lambda p: p.stat().st_mtime,
    )
    for old in kept[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)


def _need_ws(wb, sheet_name: str | None, file_name: str):
    if not sheet_name:
        return wb[wb.sheetnames[0]]
    if sheet_name not in wb.sheetnames:
        raise BusinessError(
            f"工作簿 {file_name} 里没有工作表 {sheet_name}。现有的是：{'、'.join(wb.sheetnames)}"
        )
    return wb[sheet_name]


def _write_cell(ws, op: dict[str, Any], where: str) -> None:
    ref = str(op.get("ref") or "").strip().upper()
    if not _ONE_PARTS.fullmatch(ref):
        raise BusinessError(f"{where} 的 ref 要是一个格子地址，比如 B2。收到的是 {op.get('ref')!r}")
    kind = str(op.get("t") or "s").strip()
    raw = op.get("v")
    cell = ws[ref]
    if raw is None or raw == "":
        cell.value = None
        return
    if kind == "n":
        try:
            cell.value = (
                int(raw) if isinstance(raw, int) and not isinstance(raw, bool) else float(raw)
            )
        except (TypeError, ValueError) as err:
            raise BusinessError(f"{where} 说这格是数字，但 {raw!r} 不是数字：{err}") from err
    elif kind == "d":
        cell.value = _as_date(raw, where)
    elif kind == "f":
        text = str(raw)
        cell.value = text if text.startswith("=") else "=" + text
    else:
        cell.value = str(raw)


def _as_date(raw: Any, where: str):
    if isinstance(raw, (dt.datetime, dt.date)):
        return raw
    text = str(raw).strip().replace("/", "-")
    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, shape)
        except ValueError:
            continue
    raise BusinessError(f"{where} 说这格是日期，但 {raw!r} 解析不成日期")


def _format_cells(ws, op: dict[str, Any], where: str) -> None:
    from openpyxl.styles import Alignment, Font

    ref = str(op.get("ref") or "").strip().upper()
    if not ref:
        raise BusinessError(f"{where} 没给 ref")
    try:
        block = ws[ref]
    except (ValueError, KeyError) as err:
        raise BusinessError(f"{where} 的 ref {ref!r} 解析不了：{err}") from err
    rows = block if isinstance(block, tuple) else ((block,),)
    for row in rows:
        for cell in row if isinstance(row, tuple) else (row,):
            old = cell.font
            cell.font = Font(
                name=old.name,
                size=old.size,
                color=old.color,
                underline=old.underline,
                bold=old.bold if op.get("bold") is None else bool(op.get("bold")),
                italic=old.italic if op.get("italic") is None else bool(op.get("italic")),
            )
            if op.get("align") is not None:
                cell.alignment = Alignment(
                    horizontal=str(op.get("align")) or None,
                    vertical=cell.alignment.vertical,
                )
            if op.get("number_format"):
                cell.number_format = str(op.get("number_format"))


def _paste_cells(ws, op: dict[str, Any], where: str, warnings: list[str]) -> None:
    src = str(op.get("src") or "").strip().upper()
    to = str(op.get("to") or "").strip().upper()
    if ":" not in src or not _ONE_PARTS.fullmatch(to):
        raise BusinessError(f"{where} 要 src（像 A1:B3）和 to（像 D5）")
    a, b = src.split(":", 1)
    if not (_ONE_PARTS.fullmatch(a) and _ONE_PARTS.fullmatch(b)):
        raise BusinessError(f"{where} 的 src {src!r} 解析不了")
    _, ac, _, ar = take_ref(a)
    _, bc, _, br = take_ref(b)
    c1, c2 = min(ac, bc), max(ac, bc)
    r1, r2 = min(ar, br), max(ar, br)
    _, tc, _, tr = take_ref(to)
    dr, dc = tr - r1, tc - c1

    picked = []
    for row in range(r1, r2 + 1):
        for col in range(c1, c2 + 1):
            one = ws.cell(row=row, column=col)
            picked.append(
                (
                    row,
                    col,
                    one.value,
                    copy(one.font),
                    copy(one.alignment),
                    one.number_format,
                )
            )
    for row, col, value, font, align, fmt in picked:
        target = ws.cell(row=row + dr, column=col + dc)
        if isinstance(value, str) and value.startswith("="):
            if parseable(value):
                target.value = offset_text(value, dr, dc)
            else:
                target.value = value
                warnings.append(
                    f"{ws.title} 的 {col_letter(col)}{row} 那条公式平移不动（认不懂），"
                    f"原样粘了过去——它现在可能指着错的地方。"
                )
        else:
            target.value = value
        target.font = font
        target.alignment = align
        target.number_format = fmt


def _shift_sheet(ws, axis: str, doing: str, at: int, warnings: list[str]) -> None:
    for row in ws.iter_rows():
        for cell in row:
            text = cell.value
            if not (isinstance(text, str) and text.startswith("=")):
                continue
            if not parseable(text):
                warnings.append(
                    f"{ws.title} 的 {cell.coordinate} 那条公式平移不动（认不懂），原样留着了——"
                    f"它现在可能指着错的地方：{text}"
                )
                continue
            shifted, cross = shift_text(text, axis, doing, at)
            if cross:
                warnings.append(
                    f"{ws.title} 的 {cell.coordinate} 里有跨表引用，那一段没有平移：{text}"
                )
            if shifted != text:
                cell.value = shifted
            if REF_ERR in shifted and REF_ERR not in text:
                warnings.append(
                    f"{ws.title} 的 {cell.coordinate} 因为这次删除指向了 {REF_ERR}：{shifted}。"
                    f"这是 Excel 自己的行为，不是这次保存失败。"
                )


def _shift_dims(ws, axis: str, doing: str, at: int) -> None:
    holder = ws.column_dimensions if axis == "col" else ws.row_dimensions
    keep = []
    for key, dim in list(holder.items()):
        here = col_index(key) if axis == "col" else int(key)
        moved = (
            move_one(here, 1, "col", doing, at)
            if axis == "col"
            else move_one(1, here, "row", doing, at)
        )
        if moved is None:
            continue
        landed = moved[0] if axis == "col" else moved[1]
        fresh = copy(dim)
        fresh.index = col_letter(landed) if axis == "col" else landed
        fresh.min = fresh.max = landed
        keep.append((fresh.index, fresh))
    for key in list(holder.keys()):
        del holder[key]
    for key, dim in keep:
        holder[key] = dim


def _shift_merges(ws, was: list[tuple[int, int, int, int]], axis: str, doing: str, at: int) -> None:
    for c1, r1, c2, r2 in was:
        if axis == "col":
            moved = move_span(c1, c2, doing, at)
            if moved is None:
                continue
            c1, c2 = moved
        else:
            moved = move_span(r1, r2, doing, at)
            if moved is None:
                continue
            r1, r2 = moved
        if c1 == c2 and r1 == r2:
            continue
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)


def _structural(
    wb,
    ws,
    kind: str,
    op: dict[str, Any],
    where: str,
    warnings: list[str],
) -> None:
    try:
        at = int(op.get("at"))  # type: ignore[arg-type]
    except (TypeError, ValueError) as err:
        raise BusinessError(f"{where} 的 at 要是一个从 1 起算的行号或列号") from err
    if at < 1:
        raise BusinessError(f"{where} 的 at 要从 1 起算，收到的是 {at}")
    axis = "row" if kind.endswith("row") else "col"
    doing = "insert" if kind.startswith("insert") else "delete"

    merges = [
        (one.min_col, one.min_row, one.max_col, one.max_row)
        for one in list(ws.merged_cells.ranges)
    ]
    for one in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(one))

    if axis == "row":
        (ws.insert_rows if doing == "insert" else ws.delete_rows)(at)
    else:
        (ws.insert_cols if doing == "insert" else ws.delete_cols)(at)

    _shift_sheet(ws, axis, doing, at, warnings)
    _shift_dims(ws, axis, doing, at)
    _shift_merges(ws, merges, axis, doing, at)

    quoted = f"'{ws.title}'!"
    plain = f"{ws.title}!"
    for other in wb.worksheets:
        if other is ws:
            continue
        for row in other.iter_rows():
            for cell in row:
                text = cell.value
                if isinstance(text, str) and text.startswith("=") and (
                    quoted in text or plain in text
                ):
                    warnings.append(
                        f"{other.title} 的 {cell.coordinate} 指着 {ws.title}，"
                        f"跨表引用不会被平移——它现在可能指着错的地方。"
                    )


def _apply_op(
    wb,
    op: dict[str, Any],
    index: int,
    file_name: str,
    warnings: list[str],
) -> dict[str, Any] | None:
    kind = str(op.get("op") or "").strip()
    where = f"第 {index + 1} 条操作（{kind or '没写 op'}）"

    if kind == "add_sheet":
        name = str(op.get("name") or "").strip()
        if not name:
            raise BusinessError(f"{where} 没给 name")
        if name in wb.sheetnames:
            return {
                "ok": True,
                "refused": "name_taken",
                "message": f"这个工作簿里已经有工作表 {name} 了",
                "sheet": name,
            }
        wb.create_sheet(name)
        return None

    if kind == "rename_sheet":
        ws = _need_ws(wb, str(op.get("sheet") or "").strip() or None, file_name)
        name = str(op.get("name") or "").strip()
        if not name:
            raise BusinessError(f"{where} 没给 name")
        if name in wb.sheetnames and name != ws.title:
            return {
                "ok": True,
                "refused": "name_taken",
                "message": f"这个工作簿里已经有工作表 {name} 了",
                "sheet": name,
            }
        ws.title = name
        return None

    if kind == "delete_sheet":
        ws = _need_ws(wb, str(op.get("sheet") or "").strip() or None, file_name)
        if len(wb.sheetnames) <= 1:
            return {
                "ok": True,
                "refused": "last_sheet",
                "message": f"{ws.title} 是这个工作簿里最后一张表，一个工作簿至少要有一张表。",
                "sheet": ws.title,
            }
        wb.remove(ws)
        return None

    ws = _need_ws(wb, str(op.get("sheet") or "").strip() or None, file_name)

    if kind == "set":
        _write_cell(ws, op, where)
        return None

    if kind in ("insert_row", "delete_row", "insert_col", "delete_col"):
        _structural(wb, ws, kind, op, where, warnings)
        return None

    if kind == "col_width":
        letter = str(op.get("col") or "").strip().upper()
        if not letter.isalpha():
            raise BusinessError(f"{where} 的 col 要是一个列字母，收到的是 {op.get('col')!r}")
        ws.column_dimensions[letter].width = float(op.get("width") or 8.43)
        return None

    if kind == "format":
        _format_cells(ws, op, where)
        return None

    if kind == "paste":
        _paste_cells(ws, op, where, warnings)
        return None

    raise BusinessError(
        f"{where} 不认识。认得的是：set、paste、insert_row、delete_row、insert_col、"
        f"delete_col、col_width、format、add_sheet、rename_sheet、delete_sheet"
    )


def save_workbook_ops(
    path: Path,
    base_rev: str,
    ops: list[dict[str, Any]],
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    """按 base_rev 对账后将有序操作序列应用到原位工作簿并原子写盘。"""
    from openpyxl import load_workbook

    if not path.is_file():
        raise BusinessError(f"工作簿文件不存在：{path}")

    now = compute_rev(path)
    if now != base_rev:
        return {
            "ok": True,
            "refused": "stale",
            "file": path.name,
            "path": str(path),
            "rev": now,
            "message": (
                f"{path.name} 在别处被改过了（另一个标签页存过，或者人在 Excel 里存过）。"
                f"这次一个字节都没写，备份也没做。重新拉一遍再改。"
            ),
        }

    try:
        wb = load_workbook(path)
    except Exception as err:
        raise BusinessError(
            f"{path.name} 读不动：{err}。原文一个字节没动。"
        ) from err

    warnings: list[str] = []
    touched = 0
    try:
        for index, op in enumerate(ops):
            if not isinstance(op, dict):
                raise BusinessError(f"第 {index + 1} 条操作不是一个对象")
            stop = _apply_op(wb, op, index, path.name, warnings)
            if stop is not None:
                return stop
            touched += 1

        now = compute_rev(path)
        if now != base_rev:
            return {
                "ok": True,
                "refused": "stale",
                "file": path.name,
                "path": str(path),
                "rev": now,
                "message": (
                    f"{path.name} 在别处被改过了（另一个标签页存过，或者人在 Excel 里存过）。"
                    f"这次一个字节都没写，备份也没做。重新拉一遍再改。"
                ),
            }

        _backup_before_write(path, now, backup_dir)
        _atomic_save_workbook(wb, path)
    finally:
        wb.close()

    return {
        "ok": True,
        "file": path.name,
        "path": str(path),
        "rev": compute_rev(path),
        "base_rev": base_rev,
        "applied": touched,
        "saved_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "warnings": warnings,
    }


@click.group(name="xlsx", cls=AgentFriendlyGroup)
def xlsx_group() -> None:
    """In-place Excel (.xlsx) workbook reading, formula evaluation, and atomic saving."""


@xlsx_group.command("inspect", cls=AgentFriendlyCommand)
@click.argument("paths", nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True, default=True, help="Output as JSON")
def xlsx_inspect(paths: tuple[str, ...], as_json: bool) -> None:
    """Read-only inspection of one or more .xlsx files (rev, size, sheet names)."""
    items = [inspect_one(resolve_target_path(p)) for p in paths]
    payload = {"ok": True, "items": items}
    click.echo(json.dumps(payload, ensure_ascii=False))


@xlsx_group.command("sheet", cls=AgentFriendlyCommand)
@click.argument("path")
@click.option("--sheet-name", default=None, help="Worksheet name (defaults to first sheet)")
@click.option("--top-row", default=1, type=int, help="Starting row (1-based)")
@click.option("--rows", default=DEFAULT_ROWS, type=int, help="Number of rows to read")
@click.option("--json", "as_json", is_flag=True, default=True, help="Output as JSON")
def xlsx_sheet(
    path: str,
    sheet_name: str | None,
    top_row: int,
    rows: int,
    as_json: bool,
) -> None:
    """Read a worksheet in-place with formula evaluation (read-only, writes zero bytes)."""
    target = resolve_target_path(path)
    payload = read_sheet_data(target, sheet_name=sheet_name, top_row=top_row, rows=rows)
    click.echo(json.dumps(payload, ensure_ascii=False))


@xlsx_group.command("create", cls=AgentFriendlyCommand)
@click.argument("path")
@click.option("--sheet-name", default="Sheet1", help="Initial worksheet title")
@click.option("--overwrite", is_flag=True, help="Replace existing file if present")
@click.option("--json", "as_json", is_flag=True, default=True, help="Output as JSON")
def xlsx_create(
    path: str,
    sheet_name: str,
    overwrite: bool,
    as_json: bool,
) -> None:
    """Create a blank .xlsx workbook at PATH."""
    from openpyxl import Workbook

    target = resolve_target_path(path)
    if target.exists() and not overwrite:
        payload = {
            "ok": True,
            "refused": "name_taken",
            "file": target.name,
            "path": str(target),
            "rev": compute_rev(target) if target.is_file() else "",
            "message": f"目标位置已经有 {target.name} 了。",
        }
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    wb = Workbook()
    wb.active.title = sheet_name or "Sheet1"
    _atomic_save_workbook(wb, target)
    wb.close()
    stat = target.stat()
    payload = {
        "ok": True,
        "file": target.name,
        "path": str(target),
        "folder": target.parent.name,
        "rev": compute_rev(target),
        "bytes": stat.st_size,
        "modified": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "sheet": sheet_name or "Sheet1",
        "sheets": [sheet_name or "Sheet1"],
    }
    click.echo(json.dumps(payload, ensure_ascii=False))


@xlsx_group.command("write-bytes", cls=AgentFriendlyCommand)
@click.argument("path")
@click.option("--content-b64", required=True, help="Base64-encoded .xlsx content")
@click.option("--backup-dir", default=None, help="Optional backup directory before overwriting")
@click.option("--json", "as_json", is_flag=True, default=True, help="Output as JSON")
def xlsx_write_bytes(
    path: str,
    content_b64: str,
    backup_dir: str | None,
    as_json: bool,
) -> None:
    """Validate and atomically write base64 .xlsx bytes to PATH."""
    from openpyxl import load_workbook

    target = resolve_target_path(path)
    try:
        data = base64.b64decode(content_b64, validate=True)
    except (binascii.Error, ValueError) as err:
        raise BusinessError(f"content_b64 解不开：{err}") from err

    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise BusinessError("收到的内容不是一个 .xlsx（连 zip 都不是），一个字节都没写。")
    try:
        wb = load_workbook(io.BytesIO(data))
        sheets = list(wb.sheetnames)
        wb.close()
    except Exception as err:
        raise BusinessError(f"收到的内容打不开：{err}。一个字节都没写。") from err

    if target.is_file() and backup_dir:
        _backup_before_write(target, compute_rev(target), Path(backup_dir).expanduser().resolve())

    target.parent.mkdir(parents=True, exist_ok=True)
    half = target.parent / f".{target.name}.writing"
    try:
        half.write_bytes(data)
        half.replace(target)
    except OSError as err:
        half.unlink(missing_ok=True)
        raise BusinessError(f"写盘失败：{err}。半截文件已清理。") from err

    stat = target.stat()
    payload = {
        "ok": True,
        "file": target.name,
        "path": str(target),
        "folder": target.parent.name,
        "rev": compute_rev(target),
        "bytes": len(data),
        "modified": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "sheets": sheets,
    }
    click.echo(json.dumps(payload, ensure_ascii=False))


@xlsx_group.command("save", cls=AgentFriendlyCommand)
@click.argument("path")
@click.option("--base-rev", required=True, help="Expected sha256[:16] revision before saving")
@click.option("--ops", "ops_raw", required=True, help="JSON array of edit operations")
@click.option("--backup-dir", default=None, help="Optional directory to store recent backups")
@click.option("--json", "as_json", is_flag=True, default=True, help="Output as JSON")
def xlsx_save(
    path: str,
    base_rev: str,
    ops_raw: str,
    backup_dir: str | None,
    as_json: bool,
) -> None:
    """Apply ordered operations to PATH in-place after verifying base_rev."""
    target = resolve_target_path(path)
    try:
        ops = json.loads(ops_raw)
    except json.JSONDecodeError as err:
        raise BusinessError(f"--ops 不是合法 JSON：{err.msg}") from err
    if not isinstance(ops, list):
        raise BusinessError(f"--ops 必须是一个 JSON 数组，收到的是 {type(ops).__name__}")

    bdir = Path(backup_dir).expanduser().resolve() if backup_dir else None
    payload = save_workbook_ops(target, base_rev.strip(), ops, backup_dir=bdir)
    click.echo(json.dumps(payload, ensure_ascii=False))
