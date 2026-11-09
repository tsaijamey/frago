"""frago calendar — 每日完成事务（Completed Affairs）持久化存储层。

数据按月落盘至 ``~/.frago/data/calendar/affairs-YYYY-MM.json``（受 ``FRAGO_CALENDAR_DIR`` 覆盖），
保证跨设备同步（遵循 AGENTS.md 同步规范），带原子写入与文件锁保护。
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date as dt_date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def get_calendar_dir() -> Path:
    """获取日历数据存储根目录。支持环境变量 FRAGO_CALENDAR_DIR 覆盖。"""
    override = os.environ.get("FRAGO_CALENDAR_DIR")
    path = Path(override).expanduser() if override else Path.home() / ".frago" / "data" / "calendar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _today_str() -> str:
    return dt_date.today().strftime("%Y-%m-%d")


def _generate_affair_id(date_str: str, title: str) -> str:
    """基于日期和标题哈希生成稳定唯一的短 ID。"""
    token = hashlib.sha256(f"{date_str}:{title.strip()}".encode()).hexdigest()[:8]
    date_compact = date_str.replace("-", "")
    return f"aff-{date_compact}-{token}"


@dataclass
class CompletedAffair:
    """每日完成事务模型。"""

    id: str
    date: str
    title: str
    summary: str = ""
    category: str = "未分类"
    tags: list[str] = field(default_factory=list)
    employee: str | None = None
    sessions: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    completed_at: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompletedAffair:
        # 兼容标签、会话和工件的单数或逗号分隔传入
        tags = data.get("tags") or data.get("tag") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        sessions = data.get("sessions") or data.get("session") or []
        if isinstance(sessions, str):
            sessions = [s.strip() for s in sessions.split(",") if s.strip()]

        artifacts = data.get("artifacts") or data.get("artifact") or []
        if isinstance(artifacts, str):
            artifacts = [a.strip() for a in artifacts.split(",") if a.strip()]

        date_val = str(data.get("date") or _today_str()).strip()
        title_val = str(data.get("title") or "").strip()
        aff_id = str(data.get("id") or "").strip() or _generate_affair_id(date_val, title_val)

        created = str(data.get("created_at") or _now_iso())
        updated = str(data.get("updated_at") or created)
        completed = str(data.get("completed_at") or created)

        # 兼容简短时间格式如 14:30 自动拼上日期
        if completed and len(completed) <= 8 and ":" in completed:
            completed = f"{date_val}T{completed}"

        return cls(
            id=aff_id,
            date=date_val,
            title=title_val,
            summary=str(data.get("summary") or "").strip(),
            category=str(data.get("category") or "未分类").strip() or "未分类",
            tags=list(tags),
            employee=str(data["employee"]).strip() if data.get("employee") else None,
            sessions=list(sessions),
            artifacts=list(artifacts),
            completed_at=completed,
            created_at=created,
            updated_at=updated,
        )


def _month_file(month: str) -> Path:
    return get_calendar_dir() / f"affairs-{month}.json"


def _read_month_file_locked(month: str) -> list[CompletedAffair]:
    target = _month_file(month)
    if not target.exists():
        # 兼容根目录下的统一 affairs.json
        legacy = get_calendar_dir() / "affairs.json"
        if legacy.exists():
            try:
                content = json.loads(legacy.read_text(encoding="utf-8"))
                raw_items = content.get("items", []) if isinstance(content, dict) else content
                return [
                    CompletedAffair.from_dict(item)
                    for item in raw_items
                    if isinstance(item, dict) and str(item.get("date", "")).startswith(month)
                ]
            except Exception:
                pass
        return []

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        raw_items = data.get("items", []) if isinstance(data, dict) else data
        return [CompletedAffair.from_dict(item) for item in raw_items if isinstance(item, dict)]
    except Exception:
        return []


def _write_month_file_atomic(month: str, affairs: list[CompletedAffair]) -> None:
    """原子写出月份数据文件（假设调用方已在锁保护下）。"""
    target = _month_file(month)

    # 按完成时间和 ID 稳定排序
    affairs_sorted = sorted(affairs, key=lambda a: (a.date, a.completed_at, a.id))
    payload = {
        "version": SCHEMA_VERSION,
        "month": month,
        "updated_at": _now_iso(),
        "total_items": len(affairs_sorted),
        "items": [a.to_dict() for a in affairs_sorted],
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    temp_fd, temp_path = tempfile.mkstemp(
        dir=str(get_calendar_dir()), prefix=f"tmp_affairs_{month}_", suffix=".json"
    )
    with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, target)


def add_affair(
    title: str,
    *,
    date: str | None = None,
    summary: str = "",
    category: str = "未分类",
    tags: list[str] | str | None = None,
    employee: str | None = None,
    sessions: list[str] | str | None = None,
    artifacts: list[str] | str | None = None,
    completed_at: str | None = None,
    affair_id: str | None = None,
) -> CompletedAffair:
    """添加单条已完成事务。具有幂等合并机制：同日期同标题会自动就地更新。"""
    date_val = (date or _today_str()).strip()
    month_val = date_val[:7]

    lock_file = get_calendar_dir() / f".affairs-{month_val}.lock"
    with open(lock_file, "w", encoding="utf-8") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            existing = _read_month_file_locked(month_val)

            # 规范化数组参数
            tag_list = tags if isinstance(tags, list) else ([t.strip() for t in str(tags).split(",") if t.strip()] if tags else [])
            session_list = sessions if isinstance(sessions, list) else ([s.strip() for s in str(sessions).split(",") if s.strip()] if sessions else [])
            artifact_list = artifacts if isinstance(artifacts, list) else ([a.strip() for a in str(artifacts).split(",") if a.strip()] if artifacts else [])

            # 寻找是否已有相同 ID 或同日期同标题的条目（幂等）
            matched_idx = -1
            clean_title = title.strip()

            for idx, item in enumerate(existing):
                if affair_id and item.id == affair_id:
                    matched_idx = idx
                    break
                if not affair_id and item.date == date_val and item.title.strip() == clean_title:
                    matched_idx = idx
                    break

            now = _now_iso()
            if matched_idx >= 0:
                old = existing[matched_idx]
                updated_item = CompletedAffair(
                    id=old.id,
                    date=date_val,
                    title=clean_title,
                    summary=summary.strip() if summary else old.summary,
                    category=category.strip() if (category and category != "未分类") else old.category,
                    tags=sorted(set(old.tags + tag_list)),
                    employee=employee.strip() if employee else old.employee,
                    sessions=sorted(set(old.sessions + session_list)),
                    artifacts=sorted(set(old.artifacts + artifact_list)),
                    completed_at=completed_at or old.completed_at or now,
                    created_at=old.created_at,
                    updated_at=now,
                )
                existing[matched_idx] = updated_item
                _write_month_file_atomic(month_val, existing)
                return updated_item

            new_id = affair_id or _generate_affair_id(date_val, clean_title)
            new_item = CompletedAffair(
                id=new_id,
                date=date_val,
                title=clean_title,
                summary=summary.strip(),
                category=category.strip() or "未分类",
                tags=list(set(tag_list)),
                employee=employee.strip() if employee else None,
                sessions=list(set(session_list)),
                artifacts=list(set(artifact_list)),
                completed_at=completed_at or now,
                created_at=now,
                updated_at=now,
            )
            existing.append(new_item)
            _write_month_file_atomic(month_val, existing)
            return new_item
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def write_affairs(
    items: list[dict[str, Any] | CompletedAffair],
    *,
    default_date: str | None = None,
    mode: str = "upsert",
) -> list[CompletedAffair]:
    """批量写入事务清单。支持 mode='upsert'（幂等合并）与 mode='replace'（覆写该日清单）。"""
    if not items:
        return []

    parsed_items: list[CompletedAffair] = []
    for raw in items:
        if isinstance(raw, CompletedAffair):
            parsed_items.append(raw)
        elif isinstance(raw, dict):
            d = dict(raw)
            if default_date and not d.get("date"):
                d["date"] = default_date
            parsed_items.append(CompletedAffair.from_dict(d))

    # 按月份分桶
    by_month: dict[str, list[CompletedAffair]] = {}
    for it in parsed_items:
        m = it.date[:7]
        by_month.setdefault(m, []).append(it)

    results: list[CompletedAffair] = []
    for month_val, month_items in by_month.items():
        lock_file = get_calendar_dir() / f".affairs-{month_val}.lock"
        with open(lock_file, "w", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                current_list = _read_month_file_locked(month_val)
                now = _now_iso()

                if mode == "replace":
                    target_dates = {it.date for it in month_items}
                    # 剔除目标日期的旧记录，完全替换
                    kept = [it for it in current_list if it.date not in target_dates]
                    for it in month_items:
                        if not it.created_at:
                            it.created_at = now
                        it.updated_at = now
                        kept.append(it)
                        results.append(it)
                    _write_month_file_atomic(month_val, kept)
                else:  # upsert 模式
                    merged_map: dict[str, CompletedAffair] = {it.id: it for it in current_list}
                    # 同时维护 (date, title) 索引用于无显式 ID 的合并
                    title_map: dict[tuple[str, str], str] = {
                        (it.date, it.title.strip()): it.id for it in current_list
                    }

                    for it in month_items:
                        target_id = it.id
                        if target_id not in merged_map:
                            key = (it.date, it.title.strip())
                            if key in title_map:
                                target_id = title_map[key]

                        if target_id in merged_map:
                            old = merged_map[target_id]
                            updated = CompletedAffair(
                                id=old.id,
                                date=it.date,
                                title=it.title.strip(),
                                summary=it.summary.strip() or old.summary,
                                category=it.category if it.category != "未分类" else old.category,
                                tags=sorted(set(old.tags + it.tags)),
                                employee=it.employee or old.employee,
                                sessions=sorted(set(old.sessions + it.sessions)),
                                artifacts=sorted(set(old.artifacts + it.artifacts)),
                                completed_at=it.completed_at or old.completed_at or now,
                                created_at=old.created_at or now,
                                updated_at=now,
                            )
                            merged_map[target_id] = updated
                            results.append(updated)
                        else:
                            if not it.created_at:
                                it.created_at = now
                            it.updated_at = now
                            merged_map[it.id] = it
                            title_map[(it.date, it.title.strip())] = it.id
                            results.append(it)

                    _write_month_file_atomic(month_val, list(merged_map.values()))
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    return results


def list_affairs(
    *,
    date: str | None = None,
    month: str | None = None,
    days: int | None = None,
    employee: str | None = None,
    category: str | None = None,
    query: str | None = None,
) -> list[CompletedAffair]:
    """查询事务列表，支持按日期、月份、天数窗口、员工、分类、关键词检索。"""
    all_affairs: list[CompletedAffair] = []

    # 确定要扫描的文件
    cal_dir = get_calendar_dir()
    month_files = sorted(cal_dir.glob("affairs-*.json"))

    if date:
        m = date[:7]
        target = _month_file(m)
        if target.exists():
            all_affairs.extend(_read_month_file_locked(m))
    elif month:
        target = _month_file(month)
        if target.exists():
            all_affairs.extend(_read_month_file_locked(month))
    else:
        # 扫描全部或最近月份
        for mf in month_files:
            m_str = mf.stem.replace("affairs-", "")
            all_affairs.extend(_read_month_file_locked(m_str))

        # 兼容 legacy affairs.json
        legacy = cal_dir / "affairs.json"
        if legacy.exists() and not month_files:
            try:
                data = json.loads(legacy.read_text(encoding="utf-8"))
                raw_items = data.get("items", []) if isinstance(data, dict) else data
                all_affairs.extend([CompletedAffair.from_dict(it) for it in raw_items])
            except Exception:
                pass

    # 过滤筛选
    filtered = all_affairs

    if date:
        filtered = [a for a in filtered if a.date == date]

    if month and not date:
        filtered = [a for a in filtered if a.date.startswith(month)]

    if days is not None and days > 0:
        cutoff = (dt_date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        filtered = [a for a in filtered if a.date >= cutoff]

    if employee:
        emp_clean = employee.strip().lower()
        filtered = [a for a in filtered if a.employee and emp_clean in a.employee.lower()]

    if category:
        cat_clean = category.strip().lower()
        filtered = [a for a in filtered if cat_clean in a.category.lower()]

    if query:
        q = query.strip().lower()
        filtered = [
            a
            for a in filtered
            if q in a.title.lower()
            or q in a.summary.lower()
            or any(q in t.lower() for t in a.tags)
            or any(q in s.lower() for s in a.sessions)
            or any(q in art.lower() for art in a.artifacts)
        ]

    # 排序：日期倒序，同日按 completed_at 倒序
    return sorted(filtered, key=lambda a: (a.date, a.completed_at, a.created_at), reverse=True)


def update_affair(affair_id: str, *, date: str | None = None, **kwargs) -> CompletedAffair | None:
    """根据 ID 修改单条记录。"""
    # 如果没提供 date，则在全部月份文件中寻找该 ID
    target_month: str | None = date[:7] if date else None
    cal_dir = get_calendar_dir()

    months_to_search: list[str] = [target_month] if target_month else []
    if not months_to_search:
        months_to_search = [
            p.stem.replace("affairs-", "") for p in sorted(cal_dir.glob("affairs-*.json"))
        ]

    for m in months_to_search:
        lock_file = cal_dir / f".affairs-{m}.lock"
        with open(lock_file, "w", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                items = _read_month_file_locked(m)
                for idx, item in enumerate(items):
                    if item.id == affair_id:
                        new_date = str(kwargs.get("date") or item.date).strip()
                        new_title = str(kwargs.get("title") or item.title).strip()
                        new_summary = (
                            kwargs["summary"].strip()
                            if "summary" in kwargs
                            else item.summary
                        )
                        new_category = (
                            kwargs["category"].strip()
                            if "category" in kwargs
                            else item.category
                        )

                        new_tags = item.tags
                        if "tags" in kwargs:
                            raw_tags = kwargs["tags"]
                            new_tags = raw_tags if isinstance(raw_tags, list) else [t.strip() for t in str(raw_tags).split(",") if t.strip()]

                        new_employee = kwargs.get("employee", item.employee)
                        if new_employee:
                            new_employee = str(new_employee).strip()

                        new_sessions = item.sessions
                        if "sessions" in kwargs:
                            raw_s = kwargs["sessions"]
                            new_sessions = raw_s if isinstance(raw_s, list) else [s.strip() for s in str(raw_s).split(",") if s.strip()]

                        new_artifacts = item.artifacts
                        if "artifacts" in kwargs:
                            raw_art = kwargs["artifacts"]
                            new_artifacts = raw_art if isinstance(raw_art, list) else [a.strip() for a in str(raw_art).split(",") if a.strip()]

                        new_completed = str(kwargs.get("completed_at") or item.completed_at)

                        updated_item = CompletedAffair(
                            id=item.id,
                            date=new_date,
                            title=new_title,
                            summary=new_summary,
                            category=new_category,
                            tags=list(set(new_tags)),
                            employee=new_employee,
                            sessions=list(set(new_sessions)),
                            artifacts=list(set(new_artifacts)),
                            completed_at=new_completed,
                            created_at=item.created_at,
                            updated_at=_now_iso(),
                        )

                        # 如果日期变迁到其他月份
                        if new_date[:7] != m:
                            items.pop(idx)
                            _write_month_file_atomic(m, items)
                            # 插入到新月份
                            add_affair(
                                updated_item.title,
                                date=updated_item.date,
                                summary=updated_item.summary,
                                category=updated_item.category,
                                tags=updated_item.tags,
                                employee=updated_item.employee,
                                sessions=updated_item.sessions,
                                artifacts=updated_item.artifacts,
                                completed_at=updated_item.completed_at,
                                affair_id=updated_item.id,
                            )
                        else:
                            items[idx] = updated_item
                            _write_month_file_atomic(m, items)

                        return updated_item
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    return None


def remove_affair(affair_id: str, *, date: str | None = None) -> bool:
    """根据 ID 删除单条记录。"""
    cal_dir = get_calendar_dir()
    months_to_search = [date[:7]] if date else [
        p.stem.replace("affairs-", "") for p in sorted(cal_dir.glob("affairs-*.json"))
    ]

    for m in months_to_search:
        lock_file = cal_dir / f".affairs-{m}.lock"
        with open(lock_file, "w", encoding="utf-8") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                items = _read_month_file_locked(m)
                original_len = len(items)
                items = [it for it in items if it.id != affair_id]
                if len(items) < original_len:
                    _write_month_file_atomic(m, items)
                    return True
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    return False


def get_calendar_summary(
    month: str | None = None,
    *,
    date: str | None = None,
    employee: str | None = None,
    category: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """生成按日聚合统计以及汇总概览（专供 WebUI 日历网格与统计卡片使用）。"""
    items = list_affairs(
        month=month, date=date, employee=employee, category=category, query=query
    )

    by_date: dict[str, dict[str, Any]] = {}
    categories_set: set[str] = set()
    employees_set: set[str] = set()

    for it in items:
        categories_set.add(it.category)
        if it.employee:
            employees_set.add(it.employee)

        bucket = by_date.setdefault(
            it.date,
            {
                "date": it.date,
                "count": 0,
                "categories": [],
                "employees": [],
                "previews": [],
            },
        )
        bucket["count"] += 1
        if it.category not in bucket["categories"]:
            bucket["categories"].append(it.category)
        if it.employee and it.employee not in bucket["employees"]:
            bucket["employees"].append(it.employee)
        if len(bucket["previews"]) < 3:
            bucket["previews"].append(it.title)

    return {
        "items": [it.to_dict() for it in items],
        "by_date": by_date,
        "summary": {
            "total_affairs": len(items),
            "active_days": len(by_date),
            "categories": sorted(categories_set),
            "employees": sorted(employees_set),
        },
        "cli_guide": {
            "add_example": 'frago calendar add --title "完成核心功能" --summary "业务结论" --category "系统研发" --employee "frago-developer"',
            "write_example": "frago calendar write --file affairs.json --mode upsert",
            "prompt_example": "把今天做完的事整理后写入日历",
        },
    }
