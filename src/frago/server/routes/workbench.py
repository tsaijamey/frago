"""会话工作台的接口：四个只读 + 一个发送（spec 20260729-session-workbench-webui）。

只读那四个只做取用与序列化：把 :mod:`frago.session.record_reader` 给的数据类拍成
JSON，把它抛的异常翻成状态码。记录归类、字段推导、家族判定这些全在核心数据层做完了，
本模块 NEVER 重做一遍——重做两份判据迟早会各走各的。

发送那一个（``POST /workbench/sessions/{sid}/send``）从 ``/api/claude-sessions`` 那边
搬了过来，同时补上了另外两家。搬家的理由是名字得说真话：那条路的名字写着 claude，
而工作台的清单里躺着三家的会话，人对着 codex 的一行说话，请求却发去一个叫
claude-sessions 的地方，谁读都会以为发错了。判家族、查工作目录、挑 driver 都在
``services.session_send`` 里做完，本模块只做解码图片与翻状态码。

分层：服务层。可以 import ``session/``，NEVER import ``cli/``。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from frago.server.services import (
    coreagent_runner,
    session_send,
    workbench_agents,
    workbench_groups,
    workbench_new_session,
    workbench_pins,
    workbench_views,
)
from frago.server.services.webui_uploads import (
    ImageUploadError,
    build_prompt_with_attachments,
    save_uploaded_documents,
    save_uploaded_images,
)
from frago.session import record_reader
from frago.session import search as session_search
from frago.session.engine_cli import EngineCliFailed, EngineCliMissing
from frago.session.record_reader import DEFAULT_LIMIT, UnknownSessionFamily

router = APIRouter()


@router.get("/workbench/sessions")
async def list_workbench_sessions() -> list[dict[str, Any]]:
    """两家的会话合并成一份清单，按最后活动时刻倒序。

    每条卡片带四档状态与两格摘要（已完成 / 卡在）。这三样在核心数据层跟会话索引一起算、
    一起缓存，本模块一个字都不推导——判据摆在两处迟早各走各的。「要你做」那一格判不出来，
    连字段都不给。

    落盘扫描是同步的，丢进工作线程跑，免得清单一慢整个事件循环跟着停。

    ``in_tmux``：这一场此刻开在某个 tmux 会话里，左栏据此给卡片挂流光。**不进核心数据层
    的缓存**——它是 tmux 此刻的样子，不是记录文件推出来的，缓存一轮就不准了。只按名字
    对（``frago-agent-<编号>``），名字是业务把手的飞书、语音会话开着也是 false。
    """
    from frago.agent_driver.tmux_session import tmux_name_for
    from frago.server.services import tmux_sessions_service as tsvc

    cards, open_names = await asyncio.gather(
        asyncio.to_thread(record_reader.list_sessions),
        asyncio.to_thread(tsvc.open_session_names),
    )
    # ``tmux_name``：开着时那个 tmux 会话的名字，页面「关闭 tmux 会话」的弹窗原样摆出来，
    # 命名规则不在前端再抄一份。没开着为 null。
    rows = []
    for card in cards:
        name = tmux_name_for(card.session_id)
        alive = name in open_names
        rows.append({**asdict(card), "in_tmux": alive, "tmux_name": name if alive else None})
    return rows


@router.get("/workbench/agents")
async def list_workbench_agents() -> dict[str, Any]:
    """新建会话时能挑哪几家 CLI，各是什么状况。

    **挑不了的也回。** 藏起来等于告诉人"frago 不支持 codex"，而真相往往只是没装；
    每一行都带着挑不了的理由，界面原样转述。判据全在
    :mod:`~frago.server.services.workbench_agents`，本模块一个字都不推导——
    前端再写一张 agent 名单，接新家的人改完 driver 会发现界面上它根本不出现。

    ``default`` 是这台机器上该默认挑哪一家；一家都挑不了时为 null。
    """
    agents = await asyncio.to_thread(workbench_agents.list_agents)
    return {
        "agents": [asdict(agent) for agent in agents],
        "default": workbench_agents.default_agent(agents),
    }


class Document(BaseModel):
    """一份随这条消息附上的文档。

    ``name`` 是用户那边的原文件名，只用来给落盘文件起个有意义的名字——agent 在提示词
    里看到的是路径，路径上带着原名它才知道自己要打开的是什么。

    新建会话与发送共用这一份形状：两条路收的是同一种东西，各写一份迟早各走各的。
    """

    name: str = ""
    data: str = ""


class CreateSessionRequest(BaseModel):
    """``POST /workbench/sessions`` 的请求体。

    ``agent`` 是挑中的那一家（``/workbench/agents`` 里的 ``agent_type``）；
    ``cwd`` 是会话的起始目录；``text`` 是第一句话。

    ``images`` 与 ``documents`` 走的是与发送那条接口完全相同的一条路：内容以 base64
    传上来，服务端落盘成真实文件，绝对路径拼进投给 agent 的第一句话。第一句话最需要
    附件——人往往一上来就要交代"照着这张图改"，而从前这里只收文字，那张图只能等会话
    起来之后再补发一次。允许文字为空但带附件。
    """

    agent: str
    cwd: str
    text: str = ""
    images: list[str] = []
    documents: list[Document] = []


@router.post("/workbench/sessions", status_code=201)
async def create_workbench_session(request: CreateSessionRequest) -> dict[str, Any]:
    """起一场新会话并投进第一句话，**不等它答完**。

    回的东西有两种形状，因为三家的会话编号来路本来就是两种：

    - ``session_id`` 有值（claude）——编号是页面这边定的，界面直接跳进那一场；
    - ``session_id`` 为 null（codex / opencode）——编号由 agent 自己分配，frago 要等会话
      起来后认领，界面拿 ``handle`` 去 ``/workbench/sessions/pending/{handle}`` 问。

    那段空窗 MUST 如实呈现。假装编号已经有了，界面会跳进一场并不存在的会话，看到的是
    一片空记录流，而人以为自己刚开的会话丢了。

    挑不了的那一家回 400（带上为什么），NEVER 起了再说：人要等上一分钟才看得出这一场
    根本不会出现在左栏。
    """
    if not request.text.strip() and not request.images and not request.documents:
        raise HTTPException(status_code=400, detail="第一句话和附件不能都是空的")
    if not request.cwd.strip():
        raise HTTPException(status_code=400, detail="起始目录不能是空的")

    # 附件要落盘，落盘要有个目录名，而目录名该是这场会话自己的编号——事后回头看
    # ``~/.frago/webui_uploads/`` 时，一眼就知道这几张图是哪一场的。编号在这里先 mint
    # 出来：编号由页面定的那一家（claude）拿它当真编号，由 agent 自己分配编号的那两家
    # （codex / opencode）用不上它，附件目录仍归在这个名字下。
    launch_id = str(uuid.uuid4())
    try:
        image_paths = save_uploaded_images(request.images, launch_id)
        doc_paths = save_uploaded_documents([d.model_dump() for d in request.documents], launch_id)
    except ImageUploadError as e:
        raise HTTPException(status_code=400, detail=f"附件没收下：{e}") from e
    prompt = build_prompt_with_attachments(request.text.strip(), image_paths, doc_paths)

    try:
        launch = await asyncio.to_thread(
            workbench_new_session.start_with_id,
            request.agent,
            request.cwd,
            prompt,
            session_id=launch_id,
        )
    except workbench_agents.AgentUnavailable as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return _launch_payload(launch)


@router.get("/workbench/sessions/pending/{handle}")
async def read_pending_session(handle: str) -> dict[str, Any]:
    """这次新建到哪一步了：认到会话编号没有、还是已经起失败了。

    把手过期或压根没有过这么一次时回 404——界面据此停下来说"这次新建跟丢了"，
    比无限轮询一个永远不会有答案的把手强。
    """
    launch = await asyncio.to_thread(workbench_new_session.status, handle)
    if launch is None:
        raise HTTPException(status_code=404, detail=f"没有编号为 {handle} 的新建记录")
    return _launch_payload(launch)


def _launch_payload(launch: workbench_new_session.PendingLaunch) -> dict[str, Any]:
    """一次新建的对外形状。两条路共用一份，NEVER 各拍各的。"""
    return {
        "handle": launch.handle,
        "agent": launch.agent_type,
        "display_name": launch.display_name,
        "cwd": launch.cwd,
        "session_id": launch.session_id,
        "error": launch.error,
        "finished": launch.finished,
    }


@router.get("/workbench/sessions/{sid}/records")
async def read_workbench_records(
    sid: str,
    after: int = Query(0, description="本批第一条的 seq，闭区间起点"),
    limit: int = Query(
        DEFAULT_LIMIT,
        description=f"本批最多几条。默认 {DEFAULT_LIMIT}，超过 {record_reader.MAX_LIMIT} 一律截到上限",
    ),
    tail: bool = Query(False, description="为真时忽略 after，取整场最后 limit 条"),
) -> list[dict[str, Any]]:
    """取这场会话从 ``after`` 起的统一记录；``tail`` 为真时取整场最后 ``limit`` 条。

    ``limit`` 越界不报错，直接截到 :data:`~frago.session.record_reader.MAX_LIMIT`——
    界面传大了是它自己的事，服务端不该因此把这一屏内容整个扣下。截断本身由核心数据层
    执行，这里一个数字都不算，NEVER 在两处各写一遍上限。

    会话编号两家的形状都不像时回 404，NEVER 猜一家试试。
    """
    try:
        records = await asyncio.to_thread(record_reader.read_records, sid, after, limit, tail)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # Lazily start file watching for this session's project so that
    # subsequent record deltas are pushed via WebSocket instead of polling.
    _ensure_watching(sid)

    return [asdict(record) for record in records]


@router.get("/workbench/search")
async def search_workbench_sessions(
    q: str = Query(..., min_length=1, description="要找的一句话，照人话写，不必是关键词"),
    top: int = Query(20, ge=1, le=50, description="最多报几场"),
) -> dict[str, Any]:
    """搜会话，与 ``frago session search`` 是同一条路：模型先把这句话摊成一组关键词，再扫遍
    ``~/.frago/sessions`` 的会话备份，按命中的不同关键词数排序。

    界面与命令行必须搜出同一批结果——人在终端里搜到过的那一场，在网页上换个入口就该还在，
    所以这里不另写检索，只把 :func:`frago.session.search.search_sessions` 的结果原样交出去。

    一趟里模型扩展要十几秒，界面据此只在人按下回车时才发，不边敲边搜。

    ``warnings`` 里是这一趟没做全的地方（扩展失败退回原句切词、有几场只剩加工副本）。
    **NEVER 把它当可选字段丢掉**——做不全却不说，等于谎报覆盖面。
    """
    result = await asyncio.to_thread(session_search.search_sessions, q, top=top)
    return asdict(result)


@router.get("/workbench/pins")
async def list_workbench_pins() -> dict[str, list[str]]:
    """当前置顶了哪几场，最近置顶的在最前。

    只回编号，不回会话本身：清单那一条接口已经把每场的标题、状态、摘要都取齐了，这里
    再回一份等于同一份数据摆两处，迟早各说各的。界面拿编号去清单里对号入座。

    名单里的编号**不与清单核对**。会话档案随时可能被删或被滚删，核对过的名单会因为
    一次滚删悄悄变短，而人根本不知道自己的置顶被清了。
    """
    return {"pinned": await asyncio.to_thread(workbench_pins.list_pins)}


@router.put("/workbench/pins/{sid}")
async def pin_workbench_session(sid: str) -> dict[str, list[str]]:
    """把这场会话置顶，回置顶后的完整名单。

    回整份名单而不是"成功"：置顶会改次序（已经在名单里的会被挪到最前），只说一句成功
    的话，界面得自己猜新次序长什么样，猜错就是两边不一致。

    **不设数量上限。** 上限是替人做决定，而左栏本来就是窗口化渲染，多几行不额外花什么。

    编号三家的形状都不像时回 404：置顶一个不存在的编号，名单里会永远躺着一行谁都对不
    上的记录。
    """
    try:
        record_reader.detect_family(sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        pinned = await asyncio.to_thread(workbench_pins.pin, sid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"pinned": pinned}


@router.delete("/workbench/pins/{sid}")
async def unpin_workbench_session(sid: str) -> dict[str, list[str]]:
    """取消置顶，回剩下的名单。

    本来就不在名单里也回 200：这条接口承诺的是"结束时它不在名单里"，那个结果已经成立。
    为此回 404 只会让界面在连点两下时弹一句没有意义的报错。同理，这里**不校验编号属于
    哪一家**——不管什么形状，把它从名单里去掉都是对的。
    """
    return {"pinned": await asyncio.to_thread(workbench_pins.unpin, sid)}


@router.get("/workbench/views")
async def list_workbench_views() -> dict[str, dict[str, int]]:
    """每场会话你上次点开它的毫秒时刻。没点开过的不在里面。

    左栏拿它与清单里「最后一句回复的时刻」相比，判这一场有没有你还没看过的新回复。
    """
    return {"viewed": await asyncio.to_thread(workbench_views.list_views)}


@router.put("/workbench/views/{sid}")
async def mark_workbench_viewed(sid: str) -> dict[str, Any]:
    """记下此刻点开了这场会话。

    时刻由服务端取而不收页面给的：它要和会话记录里的时刻比大小，两边必须出自同一个钟。

    编号三家的形状都不像时回 404：记录里躺一行谁都对不上的编号，从此没人清得掉。
    """
    try:
        record_reader.detect_family(sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        return await asyncio.to_thread(workbench_views.mark_viewed, sid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _groups_payload(state: dict[str, Any], job: dict[str, Any] | None = None) -> dict[str, Any]:
    """分组的对外形状：整份分组，外加 AI 分组那一趟走到哪了。每条接口都回这一份。"""
    return {**state, "ai_job": job if job is not None else workbench_groups.job_state()}


@router.get("/workbench/groups")
async def list_workbench_groups() -> dict[str, Any]:
    """有哪些标签、每个标签下挂哪些会话编号，外加 AI 分组的进度。

    与置顶一样只回编号：会话本身由清单那条接口给，界面拿编号去对号入座。编号**不与清单
    核对**——Claude Code 清理掉原文件的会话备份里还在，一核对就会被悄悄踢出分组。
    """
    return _groups_payload(await asyncio.to_thread(workbench_groups.load))


class CreateTagRequest(BaseModel):
    name: str


@router.post("/workbench/groups/tags")
async def create_workbench_tag(request: CreateTagRequest) -> dict[str, Any]:
    """人建一个标签。重名回 409：两个同名分区，人分不清该往哪个里放。"""
    try:
        state = await asyncio.to_thread(workbench_groups.create_tag, request.name)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _groups_payload(state)


@router.delete("/workbench/groups/tags/{tag_id}")
async def delete_workbench_tag(tag_id: str) -> dict[str, Any]:
    """删一个标签，里面的会话回到未分组。本来就没有也回 200。"""
    return _groups_payload(await asyncio.to_thread(workbench_groups.delete_tag, tag_id))


class AssignRequest(BaseModel):
    """``tag_id`` 为 null 就是移出分组。"""

    tag_id: str | None = None


@router.put("/workbench/groups/sessions/{sid}")
async def assign_workbench_session(sid: str, request: AssignRequest) -> dict[str, Any]:
    """把这场会话放进某个组（从原来那组搬走），或移出分组。

    编号三家的形状都不像时回 404，标签不存在也回 404：分组里躺一行谁都对不上的记录，
    从此没人清得掉。
    """
    try:
        record_reader.detect_family(sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        state = await asyncio.to_thread(workbench_groups.assign, sid, request.tag_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"没有这个标签：{request.tag_id}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _groups_payload(state)


@router.post("/workbench/groups/ai")
async def start_workbench_ai_grouping() -> dict[str, Any]:
    """让 AI 把还没分组的主会话归进标签。在后台跑，立刻回进度，页面轮询取分组看它走到哪。

    已经在跑就不再起第二趟，照样回当前进度。
    """
    cards = await asyncio.to_thread(record_reader.list_sessions)
    job = workbench_groups.start_ai_grouping(cards)
    return _groups_payload(await asyncio.to_thread(workbench_groups.load), job)


class SendRequest(BaseModel):
    """``POST /workbench/sessions/{sid}/send`` 的请求体。

    ``images`` 与 ``documents`` 都是可选附件，内容以 base64 传上来，落盘后其绝对路径
    被拼进投给 agent 的提示词。浏览器读不到本机文件的真实路径（那是浏览器的安全边界，
    拖拽也拿不到），所以只能走这条"内容上传、路径下发"的路——agent 拿到的是一条它
    真的打得开的服务端路径。允许 text 为空但带附件。

    ``cwd`` 只在页面**新建**一场会话时给：那个编号是页面自己 mint 的，还没有任何
    记录，所以读不出目录。已经有记录的会话一律以档案里记着的目录为准。

    ``wait`` 为假时只排队不等答：判完落点就回 ``status: "queued"``。虚拟桌面上的人类
    输入行走这条路——人追加的那句话要排进主 agent 的队列，而主 agent 那一轮可能还要
    跑几十分钟。
    """

    text: str = ""
    images: list[str] = []
    documents: list[Document] = []
    cwd: str | None = None
    wait: bool = True


@router.post("/workbench/sessions/{sid}/send")
async def send_to_session(sid: str, request: SendRequest) -> dict:
    """把这段话投进那场会话（Claude Code / opencode / codex / CoreAgent 都走这里）。

    前三家：会话已经常驻就直接投喂（上下文原样保留），冷的那些由会话池按各家自己的续接
    命令重建之后再投。CoreAgent 每一轮新起一个进程，靠把那一场的记录读回来接上前文。
    返回激活态，页面据此在冷启动那一轮显示进度条。

    六类拒绝各有各的意思，NEVER 合并成一个 500：

    - 编号三家的形状都不像 → 404，这不是一场会话；
    - 记录已经不在了（用户删了那场会话）→ 409。**这一档最要紧**：驱动层遇到续不上的
      目标会自愈成裸起一场新的，那正是页面上最不该发生的事——人以为在跟原来那场说话；
    - 问不出这场会话当初跑在哪个目录 → 409，替它猜一个目录等于把 agent 挪进另一个仓库；
    - CoreAgent 那一场还在跑 → 409，等它答完就能发；
    - 内核不在或者 CoreAgent 没配连接 → 503，这一轮连记录都没留下，理由只能从这里带出去；
    - 一个字没有也没有附件 → 400，空轮次投进去只会白占一次冷启动。
    """
    if not request.text.strip() and not request.images and not request.documents:
        raise HTTPException(status_code=400, detail="要发的话和附件不能都是空的")

    try:
        image_paths = save_uploaded_images(request.images, sid)
        doc_paths = save_uploaded_documents([d.model_dump() for d in request.documents], sid)
    except ImageUploadError as e:
        raise HTTPException(status_code=400, detail=f"附件没收下：{e}") from e
    prompt = build_prompt_with_attachments(request.text, image_paths, doc_paths)

    try:
        if not request.wait:
            # 只排队：判落点仍会读盘，照样进工作线程；投喂本身由它自己开的线程做。
            await asyncio.to_thread(session_send.send_queued, sid, prompt, cwd_hint=request.cwd)
            return {"sid": sid, "status": "queued", "text": ""}
        # tmux + 轮询是阻塞的，丢进工作线程，免得一轮投喂把整个事件循环停住。
        activation = await asyncio.to_thread(session_send.send, sid, prompt, cwd_hint=request.cwd)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (
        session_send.SessionGone,
        session_send.SessionDirectoryUnknown,
        # 这一家的会话接不上话。照实说，NEVER 让它落进下面那个 500——那在页面上只剩
        # 一句"没发出去"，人会以为是出了故障。
        session_send.SessionNotResumable,
        # CoreAgent 那一场还在跑：等它答完就能发，跟"发失败"不是一回事。
        coreagent_runner.CoreAgentBusy,
    ) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except coreagent_runner.CoreAgentUnavailable as e:
        # 内核不在、或者 CoreAgent 还没配连接：这一轮在会话记录里一行都没留下，
        # 页面上除了这句话没有别的线索，所以理由必须原样带出去。
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — 驱动失败照实交代，NEVER 吞成"发出去了"
        raise HTTPException(status_code=500, detail=f"没发出去：{e}") from e

    return {
        "sid": activation.session_id,
        "status": activation.status,
        "text": activation.text,
    }


class StopRunRequest(BaseModel):
    """``POST /workbench/sessions/{sid}/stop`` 的请求体。

    ``force`` 是人第二次按下去时才带的：第一次按下若发现屏上还在干活，服务端不动它，
    把「还在干活」如实回给页面，由人自己决定要不要打断。
    """

    force: bool = False


@router.post("/workbench/sessions/{sid}/stop")
async def stop_session_run(sid: str, request: StopRunRequest) -> dict[str, Any]:
    """结束这一场会话此刻在 tmux 里的运行。

    **按下去才去找那具 tmux，页面不预先探测。** 打开一场会话是个高频动作，为了让按钮
    亮或灭而每次都去问一趟 tmux，代价摊在每一次点击上；而这个按钮一天按不了几次。
    代价是按钮恒亮，按下去才知道有没有关到——那句话由返回值如实说出来。

    **NEVER 拿会话卡片上那个「在跑」当判据。** 那一档是从记录文件推的，与 tmux 里
    有没有一具活着的会话是两回事：一场昨天的会话记录停在昨天而 tmux 早没了，反过来
    也有 tmux 活着、记录看着已终结的。

    关闭本身一个字都不新写，走的是清点浮窗那条既有的路：池子管着的交给池子驱逐
    （池的内存状态得跟着变，否则页面下次投喂会拿着一个死掉的把手去 send），池外的
    才落到单场 ``kill-session``。**NEVER kill-server。**

    三种结局，页面各说各的话：

    - ``alive`` 为假——这一场此刻没有在跑的会话，什么都没动；
    - ``alive`` 为真而 ``stopped`` 为假且 ``busy`` 为真——屏上还在干活，没动它，
      等人带 ``force`` 再按一次；
    - ``stopped`` 为真——关掉了，``via`` 说明走的是池的驱逐还是 tmux。
    """
    from frago.server.services import tmux_sessions_service as svc

    def _stop() -> dict[str, Any]:
        link = svc.find_for_session(sid)
        if link is None:
            return {
                "sid": sid,
                "alive": False,
                "busy": False,
                "stopped": False,
                "name": None,
                "via": None,
                "error": None,
            }
        if link.busy and not request.force:
            return {
                "sid": sid,
                "alive": True,
                "busy": True,
                "stopped": False,
                "name": link.name,
                "via": None,
                "error": None,
            }
        result = svc.close_sessions([link.name])[0]
        return {
            "sid": sid,
            "alive": True,
            "busy": link.busy,
            "stopped": bool(result["ok"]),
            "name": link.name,
            "via": result["via"],
            "error": result["error"],
        }

    # 找会话要跑 tmux、读屏，关闭要跑 ps 与 kill，整趟都是阻塞 IO。
    return await asyncio.to_thread(_stop)


@router.delete("/workbench/sessions/{sid}")
async def delete_workbench_session(sid: str) -> dict[str, Any]:
    """把一场会话从本机删掉，让它不再出现在会话清单里。

    三家都删，删法两家不同（详见 :func:`frago.session.record_reader.delete_session`）：
    Claude Code 的记录就是一个 JSONL 加一个同名目录，直接删干净；opencode 与 codex
    借引擎自己的删除命令。删完这一场从左栏消失，记录流也打不开。frago 在
    ``~/.frago/sessions/`` 下另存的副本不跟着动，命令行检索仍找得到它。

    **正在跑的会话不删，回 409。** 判据是 tmux 里此刻有没有一具活着的会话，与「结束运行」
    那个按钮问的是同一件事：那具壳还活着的话，它接着往新写出来的同名文件里落记录，人会
    以为删除没生效。NEVER 拿卡片上那个从记录文件推出来的「在跑」当判据——那条路和 tmux
    的真实情况对不上，一场昨天的会话记录还热着，tmux 早就没了。

    四种拒绝各有各的意思，NEVER 合并成一个 500：

    - 编号不属于任何一家 → 404；
    - 本机已经没有这场会话 → 404，要的结果已经成立，把人引到"失败"上是错的；
    - 这一场还在跑 → 409；
    - 引擎拒绝动手（没装那个命令、命令超时、它自己报错）→ 500，把它的话原样带出去。

    还有一条正常走不到的 400（``SessionDeleteUnsupported``）：将来 ``detect_family``
    多加一家而删除这条路还没跟上时，让它明着说不支持，好过落进别家的删法里。

    删掉之后再摘分组、置顶里那个编号，以及 frago 这边指着它的身份映射（后一件在
    ``delete_session`` 里做）。这些失败**不回滚删除也不报成失败**——会话已经不在盘上了，
    那句实话进 ``warnings`` 带回去，比假装整件事没做成有用。
    """
    try:
        record_reader.detect_family(sid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    from frago.server.services import tmux_sessions_service as tsvc

    # 读屏是阻塞 IO，且这条问路与「结束运行」共用同一份判据，两处 MUST 给出同一个答案。
    link = await asyncio.to_thread(tsvc.find_for_session, sid)
    if link is not None:
        raise HTTPException(
            status_code=409,
            detail=f"这一场还在跑（{link.name}），先结束运行再删",
        )

    try:
        removed = await asyncio.to_thread(record_reader.delete_session, sid)
    except record_reader.SessionDeleteUnsupported as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except record_reader.SessionFilesMissing as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (EngineCliMissing, EngineCliFailed) as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"没删掉：{e}") from e

    warnings = list(removed.problems)
    try:
        await asyncio.to_thread(workbench_groups.remove_session, sid)
    except Exception as e:  # noqa: BLE001 — 收尾没做干净要说出来，NEVER 吞掉
        warnings.append(f"分组里那个编号没摘掉：{e}")
    try:
        await asyncio.to_thread(workbench_pins.unpin, sid)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"置顶名单里那个编号没摘掉：{e}")

    return {
        "sid": removed.session_id,
        "family": removed.family,
        "removed": removed.removed,
        "warnings": warnings,
    }


@router.get("/workbench/records/{rid}/raw")
async def read_workbench_record_raw(
    rid: str,
    session_id: str = Query(..., description="这条记录属于哪一场会话"),
) -> dict[str, Any]:
    """取单条记录的原文。

    **报错类恒 403。** 那条原文的响应头里带着 Cloudflare 的登录凭据，服务端直接拒，
    NEVER 靠前端自觉不去点。上游对报错类返回空，这里把空翻成 403 而不是 200 加空值——
    200 加空值会让界面以为「这条没原文」而照常展开，判断权就又回到了前端手上。

    取不到的记录同样回 403 而不是 404：只有拿到原文才算放行，其余一律不放行。
    """
    try:
        raw = await asyncio.to_thread(record_reader.read_raw, session_id, rid)
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if raw is None:
        raise HTTPException(status_code=403, detail=f"记录 {rid} 的原文不予提供")
    return raw


# ── internal helpers ─────────────────────────────────────────────────


def _ensure_watching(session_id: str) -> None:
    """Trigger lazy file watching for the project of *session_id*.

    Claude Code sessions (UUID-shaped) start a ``SessionStream`` per project;
    opencode sessions (``ses_`` prefix) start a shared ``OpencodeStream``.
    """
    try:
        from frago.server.services.workbench_stream_bridge import (
            WorkbenchStreamBridge,
        )

        bridge = WorkbenchStreamBridge.get_instance()
        bridge.ensure_watching(session_id)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "Failed to start workbench watching for %s", session_id, exc_info=True
        )
