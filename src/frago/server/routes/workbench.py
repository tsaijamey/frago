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
    session_send,
    workbench_agents,
    workbench_groups,
    workbench_new_session,
    workbench_pins,
)
from frago.server.services.webui_uploads import (
    ImageUploadError,
    build_prompt_with_attachments,
    save_uploaded_documents,
    save_uploaded_images,
)
from frago.session import record_reader, record_search
from frago.session.record_reader import DEFAULT_LIMIT, UnknownSessionFamily

router = APIRouter()


@router.get("/workbench/sessions")
async def list_workbench_sessions() -> list[dict[str, Any]]:
    """两家的会话合并成一份清单，按最后活动时刻倒序。

    每条卡片带四档状态与两格摘要（已完成 / 卡在）。这三样在核心数据层跟会话索引一起算、
    一起缓存，本模块一个字都不推导——判据摆在两处迟早各走各的。「要你做」那一格判不出来，
    连字段都不给。

    落盘扫描是同步的，丢进工作线程跑，免得清单一慢整个事件循环跟着停。
    """
    cards = await asyncio.to_thread(record_reader.list_sessions)
    return [asdict(card) for card in cards]


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
        doc_paths = save_uploaded_documents(
            [d.model_dump() for d in request.documents], launch_id
        )
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
async def search_workbench_content(
    q: str = Query(..., description="要在会话内容里找的一句话，空格分开的多个词是「并且」"),
    limit: int = Query(60, ge=1, le=200, description="每一家最多报几场"),
    per_session: int = Query(2, ge=1, le=10, description="每场最多附几条摘要"),
) -> dict[str, Any]:
    """在会话内容里找一句话，只认提示词与 agent 回复正文。

    左栏原本只搜得到标题、目录、会话编号，可人记得住的往往是当时说过的那句话。搜的
    范围**刻意只有对话**：工具参数、工具输出、hook 注入体量是对话的几十倍，掺进来的
    结果人一条都认不出是自己要的。

    ``warnings`` 里是这一趟没做全的地方（没装 ripgrep、命中太多只报了一部分）。
    **NEVER 把它当可选字段丢掉**——做不全却不说，等于谎报覆盖面。

    落盘检索是同步的，丢进工作线程跑，免得一次搜索把整个事件循环停住。
    """
    outcome = await asyncio.to_thread(
        record_search.search_sessions, q, limit=limit, per_session=per_session
    )
    return {
        "query": outcome.query,
        "terms": record_search.split_terms(q),
        "sessions": [asdict(match) for match in outcome.matches],
        "scanned_files": outcome.scanned_files,
        "warnings": outcome.warnings,
    }


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
    """把这段话投进那场会话所属的 CLI（Claude Code / opencode / codex 都走这里）。

    会话已经常驻就直接投喂（上下文原样保留），冷的那些由会话池按各家自己的续接命令
    重建之后再投。返回激活态，页面据此在冷启动那一轮显示进度条。

    四类拒绝各有各的意思，NEVER 合并成一个 500：

    - 编号三家的形状都不像 → 404，这不是一场会话；
    - 记录已经不在了（用户删了那场会话）→ 409。**这一档最要紧**：驱动层遇到续不上的
      目标会自愈成裸起一场新的，那正是页面上最不该发生的事——人以为在跟原来那场说话；
    - 问不出这场会话当初跑在哪个目录 → 409，替它猜一个目录等于把 agent 挪进另一个仓库；
    - 一个字没有也没有附件 → 400，空轮次投进去只会白占一次冷启动。
    """
    if not request.text.strip() and not request.images and not request.documents:
        raise HTTPException(status_code=400, detail="要发的话和附件不能都是空的")

    try:
        image_paths = save_uploaded_images(request.images, sid)
        doc_paths = save_uploaded_documents(
            [d.model_dump() for d in request.documents], sid
        )
    except ImageUploadError as e:
        raise HTTPException(status_code=400, detail=f"附件没收下：{e}") from e
    prompt = build_prompt_with_attachments(request.text, image_paths, doc_paths)

    try:
        if not request.wait:
            # 只排队：判落点仍会读盘，照样进工作线程；投喂本身由它自己开的线程做。
            await asyncio.to_thread(
                session_send.send_queued, sid, prompt, cwd_hint=request.cwd
            )
            return {"sid": sid, "status": "queued", "text": ""}
        # tmux + 轮询是阻塞的，丢进工作线程，免得一轮投喂把整个事件循环停住。
        activation = await asyncio.to_thread(
            session_send.send, sid, prompt, cwd_hint=request.cwd
        )
    except UnknownSessionFamily as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (session_send.SessionGone, session_send.SessionDirectoryUnknown) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
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
