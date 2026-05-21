# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""diagnose_timeline_pa — 按时间窗采集 timeline / PA 运行数据，打成模板化诊断包。

只做采集 + 结构化 + 轻量索引：多源 JSONL/日志按窗口过滤、跨格式时间戳归一、
脱敏与安全红线过滤、打包 zip、生成 manifest.json / SUMMARY.md。
"""

import contextlib
import json
import os
import platform
import re
import shutil
import sys
import zipfile
from collections import Counter, OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

TOOL_VERSION = "1.0"

# 系统本地时区（aware），所有时间戳归一的目标
LOCAL_TZ = datetime.now().astimezone().tzinfo

FRAGO_HOME = Path.home() / ".frago"

# 正文类字段名：redact 时这些字段的值替换为 <redacted len=N>
BODY_FIELDS = {
    "prompt", "text", "result_summary", "summary",
    "prompt_hint", "reason", "content", "root_summary",
}

# 安全红线：runtime/ 内 JSON 递归剔除 key 名（小写）含这些子串的字段
SECRET_KEY_SUBSTR = ("secret", "token", "key", "password")

# 生命周期状态枚举（对照 codebase: server/services/taskboard/models.py）
MSG_TERMINAL = {"closed", "dismissed"}
TASK_TERMINAL = {"completed", "failed", "resume_failed", "replied"}

SINCE_RE = re.compile(r"^(\d+)([smhd])$")
SERVER_HEADER_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3})\]\s+(\S+)"
)
SINCE_UNIT = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}

# 日志消息聚合：把变量片段（uuid / 含字母+数字的 id / 纯数字）归一为占位符，
# 使重复刷屏的告警折叠成一个模式。
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
MIXED_ID_RE = re.compile(r"\b(?=[0-9A-Za-z]*[0-9])(?=[0-9A-Za-z]*[A-Za-z])[0-9A-Za-z]{5,}\b")
NUM_RE = re.compile(r"\b\d+\b")


def normalize_msg(s):
    """归一日志消息正文，便于按模式聚合。"""
    s = UUID_RE.sub("<uuid>", s)
    s = MIXED_ID_RE.sub("<id>", s)
    s = NUM_RE.sub("<n>", s)
    return s.strip()


# 从日志文本里抽 task_id 前缀（ULID 截断成 8 位、含字母+数字、大写 base32）
LOG_TASKID_RE = re.compile(r"\b[0-9A-Z]{8}\b")


def extract_task_prefixes(headers):
    """从一组日志行抽出疑似 task_id 8 位前缀（既含数字又含字母）。"""
    out = set()
    for line in headers:
        for tok in LOG_TASKID_RE.findall(line):
            if any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok):
                out.add(tok)
    return out


def top_patterns(headers, top_n=10):
    """把一组日志首行按归一后的消息体聚合，返回 [(pattern, count, example)]。"""
    groups = {}  # norm_msg -> [count, first_raw_example]
    for line in headers:
        # 去掉 "[ts] LEVEL logger: " 前缀，只归一消息体
        body = re.sub(r"^\[[^]]+\]\s+\S+\s+\S+?:\s*", "", line)
        key = normalize_msg(body)
        if key not in groups:
            groups[key] = [0, line]
        groups[key][0] += 1
    ranked = sorted(groups.items(), key=lambda kv: kv[1][0], reverse=True)
    return [(k, v[0], v[1]) for k, v in ranked[:top_n]]


def log(msg):
    print(msg, file=sys.stderr)


def die(msg):
    print(json.dumps({"success": False, "error": msg}, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)


def normalize_to_local_aware(dt):
    """naive -> 附本地时区；aware -> 原样。比较前必经此函数。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt


# --------------------------------------------------------------------------- #
# 窗口解析
# --------------------------------------------------------------------------- #
def resolve_window(params):
    """优先级 since > (start[,end]) > 默认 since=2h。返回 (start, end) 本地 aware。"""
    now = datetime.now().astimezone()
    since = params.get("since")
    start_raw = params.get("start")
    end_raw = params.get("end")

    if since is not None:
        m = SINCE_RE.match(str(since).strip())
        if not m:
            die(f"非法 since 格式: {since!r}（应匹配 \\d+[smhd]，如 2h/30m/90s/1d）")
        delta = timedelta(**{SINCE_UNIT[m.group(2)]: int(m.group(1))})
        return now - delta, now

    if start_raw is not None:
        try:
            window_start = normalize_to_local_aware(datetime.fromisoformat(str(start_raw)))
        except ValueError as e:
            die(f"start 解析失败: {start_raw!r} ({e})")
        if end_raw is not None:
            try:
                window_end = normalize_to_local_aware(datetime.fromisoformat(str(end_raw)))
            except ValueError as e:
                die(f"end 解析失败: {end_raw!r} ({e})")
        else:
            window_end = now
        if window_start > window_end:
            die(f"窗口区间非法: start({window_start.isoformat()}) 晚于 end({window_end.isoformat()})")
        return window_start, window_end

    # 默认 since=2h
    return now - timedelta(hours=2), now


def in_window(dt, window):
    """闭区间 [start, end] 判定。"""
    return window[0] <= dt <= window[1]


def parse_ts(value):
    """解析任意源时间戳为本地 aware；失败返回 None。"""
    if not value:
        return None
    try:
        return normalize_to_local_aware(datetime.fromisoformat(str(value)))
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# 脱敏 / 安全红线
# --------------------------------------------------------------------------- #
def redact_body(obj):
    """递归把正文类字段值替换为 <redacted len=N>。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in BODY_FIELDS:
                n = len(v) if isinstance(v, str) else len(json.dumps(v, ensure_ascii=False))
                out[k] = f"<redacted len={n}>"
            else:
                out[k] = redact_body(v)
        return out
    if isinstance(obj, list):
        return [redact_body(x) for x in obj]
    return obj


def strip_secret_keys(obj):
    """递归剔除 key 名（小写）含 secret/token/key/password 的字段。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(s in kl for s in SECRET_KEY_SUBSTR):
                continue
            out[k] = strip_secret_keys(v)
        return out
    if isinstance(obj, list):
        return [strip_secret_keys(x) for x in obj]
    return obj


# --------------------------------------------------------------------------- #
# 采集：timeline
# --------------------------------------------------------------------------- #
def read_jsonl(path):
    """逐行读 JSONL，产出 (entry, parse_error_count)。坏行跳过并计数。"""
    entries, errors = [], 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    errors += 1
    except OSError:
        pass
    return entries, errors


def collect_timeline(window):
    """返回 (all_entries, window_entries, parse_errors)。all 用于生命周期重建。"""
    path = FRAGO_HOME / "timeline" / "timeline.jsonl"
    all_entries, errors = read_jsonl(path)
    win = []
    for e in all_entries:
        dt = parse_ts(e.get("ts"))
        if dt is not None and in_window(dt, window):
            win.append(e)
    return all_entries, win, errors


def collect_traces(window):
    """合并 trace-*.jsonl，窗口过滤后按 ts 排序。返回 (window_entries, parse_errors)。"""
    traces_dir = FRAGO_HOME / "traces"
    merged, errors = [], 0
    if traces_dir.is_dir():
        for path in sorted(traces_dir.glob("trace-*.jsonl")):
            entries, errs = read_jsonl(path)
            errors += errs
            for e in entries:
                dt = parse_ts(e.get("ts"))
                if dt is not None and in_window(dt, window):
                    merged.append((dt, e))
    merged.sort(key=lambda x: x[0])
    return [e for _, e in merged], errors


# --------------------------------------------------------------------------- #
# 采集：server.log（含轮转 + traceback 续行）
# --------------------------------------------------------------------------- #
def collect_server_log(window):
    """返回 (in_window_lines, total, error_count, warning_count, error_headers, warning_headers)。

    轮转顺序旧->新：server.log.3 -> .2 -> .1 -> server.log。
    每条记录由首行时间戳判定窗口；无时间戳的续行跟随当前记录。
    *_headers 是各 ERROR/WARNING 记录的首行，供调用方做模式聚合。
    """
    files = []
    for name in ("server.log.3", "server.log.2", "server.log.1", "server.log"):
        p = FRAGO_HOME / name
        if p.exists():
            files.append(p)

    records = []  # [(dt_or_None, level_or_None, [lines])]
    cur = None
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.rstrip("\n")
                    m = SERVER_HEADER_RE.match(line)
                    if m:
                        ts_str = f"{m.group(1)}.{m.group(2)}"
                        dt = parse_ts(ts_str)
                        cur = [dt, m.group(3), [line]]
                        records.append(cur)
                    else:
                        if cur is None:
                            cur = [None, None, [line]]
                            records.append(cur)
                        else:
                            cur[2].append(line)
        except OSError:
            continue

    out_lines, total, errors, warnings = [], 0, 0, 0
    error_headers, warning_headers = [], []
    for dt, level, lines in records:
        if dt is None or not in_window(dt, window):
            continue
        total += 1
        out_lines.extend(lines)
        if level == "ERROR":
            errors += 1
            error_headers.append(lines[0])
        elif level == "WARNING":
            warnings += 1
            warning_headers.append(lines[0])
    return out_lines, total, errors, warnings, error_headers, warning_headers


# --------------------------------------------------------------------------- #
# 采集：agents/
# --------------------------------------------------------------------------- #
def collect_agent_files(window, window_task_id8):
    """挑选 logs/ 下纳入的 agent 自由文本文件。返回 [Path]。

    纳入条件（满足其一）：mtime 落在窗口内；或文件名含窗口内 task_id 前 8 位。
    """
    logs_dir = FRAGO_HOME / "logs"
    if not logs_dir.is_dir():
        return []
    patterns = ("agent-*.log", "agent-attached-*.txt", "prompt-*.txt", "console-*.txt")
    candidates = {}
    for pat in patterns:
        for p in logs_dir.glob(pat):
            candidates[p.name] = p
    selected = []
    for name, p in sorted(candidates.items()):
        try:
            mtime = normalize_to_local_aware(datetime.fromtimestamp(p.stat().st_mtime))
        except OSError:
            continue
        include = in_window(mtime, window) or any(t8 in name for t8 in window_task_id8)
        if include:
            selected.append(p)
    return selected


# --------------------------------------------------------------------------- #
# 生命周期重建（基于完整 timeline）
# --------------------------------------------------------------------------- #
def fold_lifecycle(all_entries):
    """按 msg_id / task_id 折叠到最终状态。返回 (msg_status, task_status)。

    状态来源（对照 codebase board._apply_entry）：
      msg : msg_received(awaiting_decision) / task_appended(dispatched) /
            msg_closed(closed) / msg_dismissed(dismissed)
      task: task_appended(queued) / task_started(executing) / task_state(data.status) /
            task_finished(data.status) / task_replied(replied)
    按 timeline 原序重放，last-write-wins。
    """
    msg_status, task_status = {}, {}
    for e in all_entries:
        dt = e.get("data_type")
        data = e.get("data") or {}
        mid = e.get("msg_id")
        tid = e.get("task_id")
        if dt == "msg_received" and mid:
            msg_status[mid] = data.get("status", "awaiting_decision")
        elif dt == "msg_closed" and mid:
            msg_status[mid] = data.get("status", "closed")
        elif dt == "msg_dismissed" and mid:
            msg_status[mid] = data.get("status", "dismissed")
        elif dt == "task_appended":
            if mid:
                # task_appended 首次 append 使 msg 进入 dispatched（data.status 即 msg 新态）
                msg_status[mid] = data.get("status", "dispatched")
            if tid:
                task_status[tid] = "queued"
        elif dt == "task_started" and tid:
            task_status[tid] = data.get("status", "executing")
        elif dt == "task_state" and tid:
            task_status[tid] = data.get("status", task_status.get(tid))
        elif dt == "task_finished" and tid:
            task_status[tid] = data.get("status", "completed")
        elif dt == "task_replied" and tid:
            task_status[tid] = data.get("status", "replied")
    return msg_status, task_status


def build_task_csid_map(all_entries):
    """task_id -> csid（取该 task 最后一条 task_session_updated 的 csid）。"""
    m = {}
    for e in all_entries:
        if e.get("data_type") == "task_session_updated":
            tid = e.get("task_id")
            csid = (e.get("data") or {}).get("csid")
            if tid and csid:
                m[tid] = csid
    return m


def count_recoveries_in_window(win_entries):
    """窗口内每个 task 的 task_recovery 次数。"""
    counts = Counter()
    for e in win_entries:
        if e.get("data_type") == "task_recovery" and e.get("task_id"):
            counts[e["task_id"]] += 1
    return counts


# --------------------------------------------------------------------------- #
# 采集：sessions/（csid 精确关联）
# --------------------------------------------------------------------------- #
def collect_sessions(csids, dest_dir, redact):
    """按 csid 拷贝 ~/.frago/sessions/claude/<csid>/。返回已采集 csid 列表。

    非 redact：拷 metadata.json / summary.json / steps.jsonl。
    redact：只拷 metadata.json / summary.json（纯结构，无正文），不拷 steps.jsonl。
    """
    sessions_root = FRAGO_HOME / "sessions" / "claude"
    collected = []
    for csid in sorted(csids):
        src = sessions_root / csid
        if not src.is_dir():
            continue
        dst = dest_dir / csid
        dst.mkdir(parents=True, exist_ok=True)
        names = ["metadata.json", "summary.json"]
        if not redact:
            names.append("steps.jsonl")
        copied_any = False
        for name in names:
            sp = src / name
            if sp.exists():
                try:
                    shutil.copy2(sp, dst / name)
                    copied_any = True
                except OSError:
                    pass
        if copied_any:
            collected.append(csid)
        elif dst.exists() and not any(dst.iterdir()):
            dst.rmdir()
    return collected


# --------------------------------------------------------------------------- #
# runtime/ 快照
# --------------------------------------------------------------------------- #
def snapshot_runtime(runtime_dir):
    """拷贝（脱敏后）运行时文件。返回 server 存活信息 dict。"""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    json_files = [
        "runtime.json", "config.json", "schedules.json",
        "feishu_poll_state.json", "telemetry.json",
    ]
    for name in json_files:
        src = FRAGO_HOME / name
        if not src.exists():
            continue
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cleaned = strip_secret_keys(data)
        (runtime_dir / name).write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    device_src = FRAGO_HOME / ".device_id"
    if device_src.exists():
        with contextlib.suppress(OSError):
            shutil.copy2(device_src, runtime_dir / ".device_id")

    return probe_server()


def probe_server():
    """读 server.pid 内容并探测进程存活。"""
    pid_path = FRAGO_HOME / "server.pid"
    pid, alive = None, False
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = None
        if pid is not None:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
    return {"pid": pid, "alive": alive}


def read_device_id():
    p = FRAGO_HOME / ".device_id"
    if p.exists():
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            return None
    return None


def read_frago_version():
    """从 config.json resources_version 取，取不到置 None。"""
    p = FRAGO_HOME / "config.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            v = data.get("resources_version")
            if v:
                return v
        except (OSError, json.JSONDecodeError):
            pass
    return None


def read_pa_session_id():
    """config.json primary_agent.session_id（PA 自身会话 csid），取不到置 None。"""
    p = FRAGO_HOME / "config.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return ((data.get("primary_agent") or {}).get("session_id")) or None
        except (OSError, json.JSONDecodeError):
            pass
    return None


# --------------------------------------------------------------------------- #
# 模板产出
# --------------------------------------------------------------------------- #
def build_summary(ctx):
    """生成 SUMMARY.md 文本（模板化，跨机器格式一致）。"""
    w = ctx["window"]
    lines = []
    lines.append("# frago 诊断包概要 (diagnose_timeline_pa)")
    lines.append("")
    lines.append("## 窗口与环境")
    lines.append(f"- 窗口: `{w['start']}` ~ `{w['end']}`")
    plat = ctx["platform"]
    lines.append(f"- 平台: {plat['system']} {plat['release']} / {plat['machine']} / Python {plat['python']}")
    lines.append(f"- frago 版本: {ctx['frago_version']}")
    lines.append(f"- hostname: {ctx['hostname']}")
    lines.append(f"- device_id: {ctx['device_id']}")
    srv = ctx["server"]
    lines.append(f"- server: pid={srv['pid']} alive={srv['alive']}")
    lines.append(f"- 生成时间: {ctx['generated_at']}")
    lines.append(f"- 脱敏 (redact): {ctx['redact']}")
    lines.append("")

    lines.append("## 计数")
    lines.append("")
    lines.append("### timeline (按 data_type)")
    if ctx["timeline_by_type"]:
        for k, v in ctx["timeline_by_type"].items():
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- (空)")
    lines.append("")

    lines.append("### traces (按 data_type / subkind)")
    if ctx["traces_by_type"]:
        for (dtp, sk), v in ctx["traces_by_type"].items():
            lines.append(f"- {dtp} / {sk}: {v}")
    else:
        lines.append("- (空)")
    lines.append("")

    lines.append("### server.log")
    lines.append(f"- 总记录数: {ctx['server_total']}")
    lines.append(f"- ERROR: {ctx['server_errors']}")
    lines.append(f"- WARNING: {ctx['server_warnings']}")
    lines.append("")

    lines.append("### sessions (csid 精确关联)")
    lines.append(f"- 采集会话数: {len(ctx['sessions_collected'])}")
    lines.append("")

    lines.append("### agents (mtime 弱关联)")
    lines.append(f"- 纳入文件数: {ctx['agents_count']}")
    lines.append("")

    if ctx["parse_errors"]:
        lines.append(f"### 解析错误 (跳过的坏行): {ctx['parse_errors']}")
        lines.append("")

    lines.append("## 生命周期扫描 (诊断重点)")
    lines.append("")
    lines.append(f"- 窗口内活跃 msg: {ctx['window_msg_count']}，task: {ctx['window_task_count']}")
    lines.append("")

    lines.append(f"### 卡在非终态的 msg ({len(ctx['stuck_msgs'])})")
    lines.append(f"  (终态集合: {sorted(MSG_TERMINAL)})")
    if ctx["stuck_msgs"]:
        for mid, st in ctx["stuck_msgs"]:
            lines.append(f"- `{mid}` -> {st}")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append(f"### 卡在非终态的 task ({len(ctx['stuck_tasks'])})")
    lines.append(f"  (终态集合: {sorted(TASK_TERMINAL)})")
    if ctx["stuck_tasks"]:
        for tid, st in ctx["stuck_tasks"]:
            lines.append(f"- `{tid}` -> {st}")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append(f"### 失败任务 (窗口内活跃, {len(ctx['failed_tasks'])})")
    lines.append("  (失败任务常触发恢复风暴，对照下方 server.log 聚合)")
    if ctx["failed_tasks"]:
        for ft in ctx["failed_tasks"]:
            sess = "已采集" if ft["session_collected"] else "未采集"
            src = "" if ft["in_window_timeline"] else " [仅窗口内日志引用]"
            lines.append(
                f"- `{ft['task_id']}` -> {ft['status']} | 窗口内 recovery {ft['recoveries_in_window']} 次"
                f" | csid={ft['csid']} (session {sess}){src}"
            )
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("### boot / fold 次数")
    if ctx["folds"]:
        lines.append(f"- startup_fold_completed 共 {len(ctx['folds'])} 次:")
        for f in ctx["folds"]:
            lines.append(
                f"  - {f['ts']}: entries_read={f['entries_read']} entries_skipped={f['entries_skipped']}"
            )
    else:
        lines.append("- 无")
    lines.append("")

    lines.append(f"### reflection tick 次数: {ctx['reflection_ticks']}")
    lines.append("")

    lines.append(f"### server.log ERROR 模式聚合 (共 {ctx['server_errors']} 条)")
    if ctx["error_patterns"]:
        for pat, cnt, example in ctx["error_patterns"]:
            lines.append(f"- ×{cnt}  `{pat}`")
            lines.append(f"    例: {example}")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append(f"### server.log WARNING 模式聚合 (共 {ctx['server_warnings']} 条)")
    if ctx["warning_patterns"]:
        for pat, cnt, example in ctx["warning_patterns"]:
            lines.append(f"- ×{cnt}  `{pat}`")
            lines.append(f"    例: {example}")
    else:
        lines.append("- 无")
    lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    if len(sys.argv) < 2:
        params = {}
    else:
        try:
            params = json.loads(sys.argv[1])
        except json.JSONDecodeError as e:
            die(f"参数解析失败: {e}")

    redact = bool(params.get("redact", False))
    output_dir = Path(params.get("output_dir") or (FRAGO_HOME / ".diagnostics")).expanduser()

    window = resolve_window(params)
    log(f"[window] {window[0].isoformat()} ~ {window[1].isoformat()}")

    # 输出目录可写性检查
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        probe = output_dir / ".write_probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        die(f"output_dir 不可写: {output_dir} ({e})")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bundle_name = f"dia-{stamp}"
    bundle_dir = output_dir / bundle_name
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "agents").mkdir(exist_ok=True)
    (bundle_dir / "sessions").mkdir(exist_ok=True)
    (bundle_dir / "runtime").mkdir(exist_ok=True)

    parse_errors = 0

    # ---- timeline ----
    log("[collect] timeline")
    all_timeline, win_timeline, err = collect_timeline(window)
    parse_errors += err
    timeline_out = [redact_body(e) for e in win_timeline] if redact else win_timeline
    with open(bundle_dir / "timeline.jsonl", "w", encoding="utf-8") as f:
        for e in timeline_out:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # ---- traces ----
    log("[collect] traces")
    win_traces, err = collect_traces(window)
    parse_errors += err
    traces_out = [redact_body(e) for e in win_traces] if redact else win_traces
    with open(bundle_dir / "traces.jsonl", "w", encoding="utf-8") as f:
        for e in traces_out:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # ---- server.log ----
    log("[collect] server.log")
    srv_lines, srv_total, srv_errors, srv_warnings, error_headers, warning_headers = \
        collect_server_log(window)
    with open(bundle_dir / "server.log", "w", encoding="utf-8") as f:
        if srv_lines:
            f.write("\n".join(srv_lines) + "\n")

    # ---- 窗口内 task_id 前 8 位（timeline + traces 并集），供 agents 纳入 ----
    window_task_id8 = set()
    for e in win_timeline:
        tid = e.get("task_id")
        if tid:
            window_task_id8.add(str(tid)[:8])
    for e in win_traces:
        tid = e.get("task_id")
        if tid:
            window_task_id8.add(str(tid)[:8])

    # ---- agents/ ----
    log("[collect] agents")
    agent_files = collect_agent_files(window, window_task_id8)
    agents_dir = bundle_dir / "agents"
    if redact:
        manifest_items = []
        for p in agent_files:
            try:
                st = p.stat()
                manifest_items.append({
                    "name": p.name,
                    "size_bytes": st.st_size,
                    "mtime": normalize_to_local_aware(
                        datetime.fromtimestamp(st.st_mtime)
                    ).isoformat(),
                })
            except OSError:
                continue
        (agents_dir / "manifest.json").write_text(
            json.dumps(manifest_items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        for p in agent_files:
            try:
                shutil.copy2(p, agents_dir / p.name)
            except OSError:
                continue
    agents_count = len(agent_files)

    # ---- runtime/ ----
    log("[collect] runtime")
    server_info = snapshot_runtime(bundle_dir / "runtime")

    # ---- 生命周期重建 ----
    log("[analyze] lifecycle fold")
    msg_status, task_status = fold_lifecycle(all_timeline)
    window_msg_ids = OrderedDict()
    window_task_ids = OrderedDict()
    for e in win_timeline:
        mid = e.get("msg_id")
        if mid:
            window_msg_ids.setdefault(mid, True)
        tid = e.get("task_id")
        if tid:
            window_task_ids.setdefault(tid, True)
    for e in win_traces:  # traces 也可能引用 task_id
        tid = e.get("task_id")
        if tid:
            window_task_ids.setdefault(tid, True)
    stuck_msgs = [
        (mid, msg_status.get(mid, "unknown"))
        for mid in window_msg_ids
        if msg_status.get(mid, "unknown") not in MSG_TERMINAL
    ]
    stuck_tasks = [
        (tid, task_status.get(tid, "unknown"))
        for tid in window_task_ids
        if task_status.get(tid, "unknown") not in TASK_TERMINAL
    ]

    # ---- 窗口内 server.log ERROR/WARNING 文本里引用到的 task（病灶常只在日志里现身）----
    #   把 timeline 全量 task_id 建 8 位前缀索引（一个前缀可能对应多个 task：ULID 同毫秒
    #   生成的姊妹任务前 8 位相同，而 server.log 只截断到 8 位无法区分，故同前缀全部纳入）。
    task_prefix_map = {}
    for e in all_timeline:
        tid = e.get("task_id")
        if tid:
            task_prefix_map.setdefault(str(tid)[:8], set()).add(tid)
    log_task_prefixes = extract_task_prefixes(error_headers + warning_headers)
    log_referenced_tids = set()
    for p in log_task_prefixes:
        log_referenced_tids |= task_prefix_map.get(p, set())

    # 关注的 task = 窗口内 timeline/traces 活跃 + 窗口内日志引用，二者并集
    tasks_of_interest = list(window_task_ids)
    for t in log_referenced_tids:
        if t not in window_task_ids:
            tasks_of_interest.append(t)

    # ---- sessions/（csid 精确关联，诊断主证据）----
    log("[collect] sessions (csid-correlated)")
    task_csid_map = build_task_csid_map(all_timeline)
    window_csids = set()
    for tid in tasks_of_interest:  # 关注 task -> 其 csid（从完整 timeline 反查）
        c = task_csid_map.get(tid)
        if c:
            window_csids.add(c)
    for e in win_timeline:  # 窗口内直接出现的 task_session_updated.csid
        if e.get("data_type") == "task_session_updated":
            c = (e.get("data") or {}).get("csid")
            if c:
                window_csids.add(c)
    pa_session_id = read_pa_session_id()
    if pa_session_id:
        window_csids.add(pa_session_id)
    collected_csids = collect_sessions(window_csids, bundle_dir / "sessions", redact)

    # ---- 失败任务（关注 task 中终态 failed/resume_failed）----
    recovery_counts = count_recoveries_in_window(win_timeline)
    FAILED_STATES = {"failed", "resume_failed"}
    failed_tasks = [
        {
            "task_id": tid,
            "status": task_status.get(tid),
            "csid": task_csid_map.get(tid),
            "recoveries_in_window": recovery_counts.get(tid, 0),
            "in_window_timeline": tid in window_task_ids,
            "session_collected": task_csid_map.get(tid) in collected_csids,
        }
        for tid in tasks_of_interest
        if task_status.get(tid) in FAILED_STATES
    ]

    # boot / fold（窗口内）
    folds = []
    for e in win_timeline:
        if e.get("data_type") == "startup_fold_completed":
            d = e.get("data") or {}
            folds.append({
                "ts": e.get("ts"),
                "entries_read": d.get("entries_read"),
                "entries_skipped": d.get("entries_skipped"),
            })

    # reflection ticks（窗口内 traces subkind=reflection）
    reflection_ticks = sum(1 for e in win_traces if e.get("subkind") == "reflection")

    # server.log 信号聚合（模式 + 计数 + 原文样例）
    warning_patterns = top_patterns(warning_headers, top_n=10)
    error_patterns = top_patterns(error_headers, top_n=10)

    # ---- 计数 ----
    timeline_by_type = Counter(e.get("data_type") for e in win_timeline)
    traces_by_type = Counter(
        (e.get("data_type"), e.get("subkind")) for e in win_traces
    )
    counts = {
        "timeline": len(win_timeline),
        "traces": len(win_traces),
        "server_log": srv_total,
        "sessions": len(collected_csids),
        "agents": agents_count,
        "server_log_errors": srv_errors,
        "server_log_warnings": srv_warnings,
        "parse_errors": parse_errors,
        "stuck_msgs": len(stuck_msgs),
        "stuck_tasks": len(stuck_tasks),
        "failed_tasks": len(failed_tasks),
    }

    # ---- 模板：manifest.json ----
    plat = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    manifest = {
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "params_raw": params,
        "window": {"start": window[0].isoformat(), "end": window[1].isoformat()},
        "frago_version": read_frago_version(),
        "platform": plat,
        "hostname": platform.node(),
        "device_id": read_device_id(),
        "server": server_info,
        "counts": counts,
        "failed_tasks": failed_tasks,
        "sessions_collected": collected_csids,
        "pa_session_id": pa_session_id,
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- 模板：SUMMARY.md ----
    summary_ctx = {
        "window": manifest["window"],
        "platform": plat,
        "frago_version": manifest["frago_version"],
        "hostname": manifest["hostname"],
        "device_id": manifest["device_id"],
        "server": server_info,
        "generated_at": manifest["generated_at"],
        "redact": redact,
        "timeline_by_type": dict(timeline_by_type),
        "traces_by_type": traces_by_type,
        "server_total": srv_total,
        "server_errors": srv_errors,
        "server_warnings": srv_warnings,
        "agents_count": agents_count,
        "parse_errors": parse_errors,
        "window_msg_count": len(window_msg_ids),
        "window_task_count": len(window_task_ids),
        "stuck_msgs": stuck_msgs,
        "stuck_tasks": stuck_tasks,
        "failed_tasks": failed_tasks,
        "sessions_collected": collected_csids,
        "pa_session_id": pa_session_id,
        "folds": folds,
        "reflection_ticks": reflection_ticks,
        "warning_patterns": warning_patterns,
        "error_patterns": error_patterns,
    }
    (bundle_dir / "SUMMARY.md").write_text(build_summary(summary_ctx), encoding="utf-8")

    # ---- 打包 zip（归档根目录即 dia-{stamp}/）----
    log("[archive] zip")
    archive_path = output_dir / f"{bundle_name}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(bundle_dir.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=str(p.relative_to(output_dir)))

    print(json.dumps({
        "success": True,
        "bundle_dir": str(bundle_dir.resolve()),
        "archive": str(archive_path.resolve()),
        "counts": counts,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
