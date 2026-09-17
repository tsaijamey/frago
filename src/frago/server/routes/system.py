"""System status and info API endpoints.

Provides endpoints for server health checks and information.
"""

import asyncio

from fastapi import APIRouter, Query

from frago.server.models import (
    ClaudeUsageResponse,
    CleanupThresholdRequest,
    CloseTmuxSessionsRequest,
    CloseTmuxSessionsResponse,
    DirectoryListingResponse,
    EnvironmentResponse,
    EnvironmentUpgradeRequest,
    EnvironmentUpgradeResponse,
    ServerInfoResponse,
    SystemDirectoriesResponse,
    SystemStatusResponse,
    TmuxSessionsCountResponse,
    TmuxSessionsResponse,
)
from frago.server.services.system_service import SystemService
from frago.server.utils import get_server_info

router = APIRouter()


@router.get("/status", response_model=SystemStatusResponse)
async def get_status() -> SystemStatusResponse:
    """Get system status.

    Returns information about Chrome availability,
    running tasks, and monitored projects.
    """
    status = SystemService.get_status()

    return SystemStatusResponse(
        cpu_percent=status.get("cpu_percent", 0.0),
        memory_percent=status.get("memory_percent", 0.0),
        browser_available=status.get("browser_available", False),
        browser_connected=status.get("browser_connected", False),
        projects_count=status.get("projects_count", 0),
        tasks_running=status.get("tasks_running", 0),
        tab_count=status.get("tab_count", 0),
    )


@router.get("/info", response_model=ServerInfoResponse)
async def get_info() -> ServerInfoResponse:
    """Get server information.

    Returns server version, host, port, and start time.
    """
    from datetime import datetime

    server_info = get_server_info()

    info = SystemService.get_info(
        host=server_info.get("host", "127.0.0.1"),
        port=server_info.get("port", 8080),
        started_at=server_info.get("started_at", datetime.now().isoformat()),
    )

    return ServerInfoResponse(
        version=info.get("version", "0.0.0"),
        host=info.get("host", "127.0.0.1"),
        port=info.get("port", 8080),
        started_at=datetime.fromisoformat(info.get("started_at", datetime.now().isoformat())),
    )


@router.get("/system/directories", response_model=SystemDirectoriesResponse)
async def get_directories() -> SystemDirectoriesResponse:
    """Get system default directories.

    Returns user home directory and current working directory.
    Used as fallback when no recent directories exist.
    """
    dirs = SystemService.get_directories()

    return SystemDirectoriesResponse(
        home=dirs.get("home", ""),
        cwd=dirs.get("cwd"),
    )


@router.get("/system/directories/browse", response_model=DirectoryListingResponse)
async def browse_directories(
    path: str = Query("", description="停在哪一层；留空从家目录起"),
) -> DirectoryListingResponse:
    """一层一层往下翻，挑一个工作目录。

    从前新建会话只能在"最近开过会话的几个目录"里挑，第一次用的人那份清单是空的，
    于是唯一的出路是手打一整条绝对路径。这条接口就是为了把那条独木桥换成一条路。

    只报子目录、不报文件，隐藏目录不报。读盘是阻塞 IO，整趟挪到线程里跑。
    """
    listing = await asyncio.to_thread(SystemService.browse_directory, path)
    return DirectoryListingResponse(**listing)


@router.get("/system/claude-usage", response_model=ClaudeUsageResponse)
async def get_claude_usage(refresh: bool = False) -> ClaudeUsageResponse:
    """本机 Claude Code 的订阅额度。

    读的是后台每十分钟探一次的缓存，不在请求路径上跑 claude——那要三秒钟，界面第一次
    画出来的时间不该押在它身上。`refresh=true` 才当场重探。
    """
    from frago.server.services.claude_usage_service import ClaudeUsageService

    service = ClaudeUsageService.get_instance()
    usage = await service.refresh() if refresh else service.get_usage()

    return ClaudeUsageResponse(**usage)


@router.get("/system/tmux-sessions", response_model=TmuxSessionsResponse)
async def list_tmux_sessions(
    excerpt_chars: int = Query(
        160,
        ge=20,
        le=600,
        description="最后一段回答截多长——够不够认出这是哪一场会话由调用方定，不写死",
    ),
) -> TmuxSessionsResponse:
    """清点本机全部 frago tmux 会话。

    每一行带最后一次说完话的时刻、当时说的是什么（截取）、这场会话占多少内存，以及
    此刻在不在干活。闲置时长的口径见 ``tmux_sessions_service`` 的模块说明——一句话，
    问的是会话自己的记录，不是 tmux 的活动时间。

    读盘 + 跑 ps + 逐个 capture-pane 都是阻塞 IO，整趟挪到线程里跑。
    """
    from frago.init.config_manager import load_config
    from frago.server.services import tmux_sessions_service as svc

    rows = await asyncio.to_thread(svc.list_sessions, excerpt_chars=excerpt_chars)
    return TmuxSessionsResponse(
        sessions=svc.as_dicts(rows),
        total=len(rows),
        total_memory_mb=sum(r.memory_mb for r in rows),
        cleanup_idle_hours=load_config().webui_sessions.cleanup_idle_hours,
    )


@router.post("/system/tmux-sessions/close", response_model=CloseTmuxSessionsResponse)
async def close_tmux_sessions(request: CloseTmuxSessionsRequest) -> CloseTmuxSessionsResponse:
    """逐条点名关闭选中的会话。

    NEVER kill-server：那会把没被选中的、正在干活的、以及虚拟桌面赖以存活的会话
    一起带走。一条失败继续下一条，逐条回报，人才知道哪些真关掉了。
    """
    from frago.server.services import tmux_sessions_service as svc

    results = await asyncio.to_thread(svc.close_sessions, request.names)
    return CloseTmuxSessionsResponse(
        results=results,
        closed=sum(1 for r in results if r["ok"]),
        failed=sum(1 for r in results if not r["ok"]),
    )


@router.put("/system/tmux-sessions/threshold", response_model=TmuxSessionsResponse)
async def set_cleanup_threshold(request: CleanupThresholdRequest) -> TmuxSessionsResponse:
    """改「闲了多久算该清」的门槛并落盘。

    **改的是手动清理的筛选口径，不是自动回收那条线**（``idle_timeout_secs``）。
    调这里不会让任何会话自己消失，只影响浮窗打开时默认把谁标出来。
    """
    from frago.init.config_manager import load_config, save_config
    from frago.server.services import tmux_sessions_service as svc

    def _persist() -> float:
        config = load_config()
        config.webui_sessions.cleanup_idle_hours = request.cleanup_idle_hours
        save_config(config)
        return config.webui_sessions.cleanup_idle_hours

    hours = await asyncio.to_thread(_persist)
    rows = await asyncio.to_thread(svc.list_sessions)
    return TmuxSessionsResponse(
        sessions=svc.as_dicts(rows),
        total=len(rows),
        total_memory_mb=sum(r.memory_mb for r in rows),
        cleanup_idle_hours=hours,
    )


@router.get("/system/tmux-sessions/count", response_model=TmuxSessionsCountResponse)
async def count_tmux_sessions() -> TmuxSessionsCountResponse:
    """本机现在有几场 tmux 会话、一共占多少内存。

    左下角常驻的那个数字问的是这条。它不读任何一份会话记录——那是点开浮窗才做的事。
    """
    from frago.server.services import tmux_sessions_service as svc

    return TmuxSessionsCountResponse(**await asyncio.to_thread(svc.count_sessions))


@router.get("/system/environment", response_model=EnvironmentResponse)
async def get_environment(refresh: bool = False) -> EnvironmentResponse:
    """跑 frago 需要的每样东西，本机装的是哪一版、外面出到哪一版。

    清单照装机向导那份探测脚本，两处必须一致。默认读缓存（外面的版本号六小时一轮、
    本机的一分钟一轮），`refresh=true` 才当场重问一遍。

    十来个子进程加十来次跨境请求都是阻塞 IO，整趟挪到线程里跑。
    """
    from frago.server.services.environment_service import EnvironmentService

    service = EnvironmentService.get_instance()
    return EnvironmentResponse(**await asyncio.to_thread(service.snapshot, refresh))


@router.post("/system/environment/upgrade", response_model=EnvironmentUpgradeResponse)
async def start_environment_upgrade(
    request: EnvironmentUpgradeRequest,
) -> EnvironmentUpgradeResponse:
    """把点名的那几样升到最新，活派给 agent 干。

    服务端不拼升级命令——同一个名字在不同机器上装法不同，猜错的代价是人看到一句
    「升级失败」。这里只把事实备齐（现在哪一版、外面到哪一版、这条命令的真实落点、
    本机有哪些包管理器）写成任务书，交给 agent 判断和执行。

    一次只跑一批，一样一样按顺序来：升级动的是共用的包管理器，并发会互相锁住。
    已经有一批在跑时不排第二个队，原样退回当前进度。
    """
    from frago.server.services.environment_upgrade_service import (
        EnvironmentUpgradeService,
    )

    service = EnvironmentUpgradeService.get_instance()
    return EnvironmentUpgradeResponse(**await service.start(request.ids))


@router.get("/system/environment/upgrade", response_model=EnvironmentUpgradeResponse)
async def get_environment_upgrade_status() -> EnvironmentUpgradeResponse:
    """这一批升级到哪一步了。界面开着的时候每两秒问一次。"""
    from frago.server.services.environment_upgrade_service import (
        EnvironmentUpgradeService,
    )

    service = EnvironmentUpgradeService.get_instance()
    return EnvironmentUpgradeResponse(accepted=True, **service.status())
