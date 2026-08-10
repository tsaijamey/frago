#!/usr/bin/env python3
"""wechat_draft_create 共享浏览器管线：browser 调用、exec-js、等待、登录、保存。

文章和贴图两种编辑器的驱动都依赖这里的原语。改动会同时影响两条链路。
"""

import json
import re
import subprocess
import sys
import time

HOME_URL = "https://mp.weixin.qq.com/"

# 等条件的上限，单位秒。轮询间隔统一 0.5 秒。
TIMEOUT_HOME = 20
TIMEOUT_EDITOR = 30
TIMEOUT_READY = 30
TIMEOUT_SET = 20
# 点「保存为草稿」后页面先跑「自检中」（错别字自检），这段时间一个请求都不发。
# 实测冷页面能占到 20 秒左右，所以等提交请求发出的上限给到 120 秒。
TIMEOUT_SAVE_SUBMIT = 120
# 提交请求发出后等它回包。
TIMEOUT_SAVE_RESP = 60
# 保存落库后等地址里带出草稿 ID（新建才需要，更新时地址本来就有）。
TIMEOUT_SAVE_ID = 20
POLL = 0.5

WARNINGS = []

# 浏览器扩展桥只对当前活动的标签页求值，对非活动标签页会一直挂住不返回。
# 别的标签页一抢焦点，本配方的求值就全卡死。这里记住自己的标签页，必要时切回来。
#
# 切回去要连 group 一起报：tab 命令只在本 group 内生效，光有 tab_id 不够。
_TAB_ID = None
_GROUP = None
_ALWAYS_ACTIVATE = False
EJS_TIMEOUT = 20


def log(msg):
    print(msg, file=sys.stderr)


def die(msg, hint=""):
    out = {"success": False, "error": msg}
    if hint:
        out["hint"] = hint
    print(json.dumps(out, ensure_ascii=False))
    print(msg + (("\n" + hint) if hint else ""), file=sys.stderr)
    sys.exit(1)


def die_logged_out(where):
    die(f"公众号后台登录态失效（{where}）",
        "请在浏览器里打开 https://mp.weixin.qq.com 重新扫码登录，然后重跑本配方。")


def browser(args, timeout=120):
    """调 frago browser，返回 (成功与否, 解析后的 JSON 或原始文本)。超时返回 (None, None)。"""
    try:
        r = subprocess.run(["frago", "browser"] + args,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, None
    raw = (r.stdout or "").strip()
    if not raw:
        return False, (r.stderr or "").strip()
    try:
        return r.returncode == 0, json.loads(raw)
    except json.JSONDecodeError:
        return r.returncode == 0, raw


def navigate(url, group):
    """导航。全程只用一个标签页——不传 --new，每次都替换本 group 的当前页。"""
    global _TAB_ID, _GROUP
    ok, res = browser(["navigate", url, "--group", group])
    if not ok:
        die(f"导航失败：{url}", str(res)[:300])
    _GROUP = group
    if isinstance(res, dict) and res.get("tab_id"):
        _TAB_ID = res["tab_id"]
    return res


def activate():
    """把自己的标签页切回前台。扩展桥只服务活动标签页。

    switch-tab 默认只改「后续命令落在哪一页」，不动浏览器的可见状态，
    所以这里必须显式带 --activate 才真的切到前台。
    """
    if _TAB_ID and _GROUP:
        browser(["switch-tab", "--group", _GROUP, str(_TAB_ID), "--activate"],
                timeout=20)


def ejs(code, group, timeout=EJS_TIMEOUT):
    """在页面里求值。code 必须自带 IIFE 包裹——exec-js 多次执行共享页面全局作用域，
    裸的 const 声明第二次就会撞名。

    标签页不在前台时求值会挂住，所以超时后切回前台重试一次；一旦发生过，
    之后每次求值都先切，免得每一轮都白等一个超时。"""
    global _ALWAYS_ACTIVATE
    if _ALWAYS_ACTIVATE:
        activate()
    ok, res = browser(["exec-js", "--group", group, code, "--return-value"], timeout=timeout)
    if ok is None:
        activate()
        _ALWAYS_ACTIVATE = True
        ok, res = browser(["exec-js", "--group", group, code, "--return-value"], timeout=timeout)
        if ok is None:
            die("在页面里求值超时两次",
                "标签页可能已被关闭，或者浏览器扩展桥失联。先跑 frago browser status 看看。")
    if not ok:
        return None
    if isinstance(res, dict):
        return res.get("value")
    return res


def ejs_json(code, group, timeout=EJS_TIMEOUT):
    v = ejs(code, group, timeout)
    if not isinstance(v, str):
        return v
    try:
        return json.loads(v)
    except json.JSONDecodeError:
        return v


def wait_for(probe, limit, desc, group):
    """轮询到 probe 返回真值为止。超时报错时带上当时的地址，便于人判断卡在哪。"""
    deadline = time.time() + limit
    last = None
    while time.time() < deadline:
        last = probe()
        if last:
            return last
        time.sleep(POLL)
    here = ejs("(()=>location.href)()", group) or "地址读不到"
    die(f"等待超时：{desc}（上限 {limit} 秒）", f"当时的地址：{here}")


def current_url(group):
    return ejs("(()=>location.href)()", group) or ""


def get_token(group):
    """登录态有效时后台首页会重定向到带 token 的地址。取不到就是没登录。"""
    log("[1/8] 取后台 token")
    navigate(HOME_URL, group)

    deadline = time.time() + TIMEOUT_HOME
    token = None
    while time.time() < deadline:
        u = current_url(group)
        if u:
            if "/login" in u or "action=login" in u:
                die_logged_out("后台首页跳到了登录页")
            m = re.search(r"[?&]token=(\d+)", u)
            if m:
                token = m.group(1)
                break
        time.sleep(POLL)
    if not token:
        # 登录态有效时根路径必然重定向到带 token 的地址；等不到就是没登录。
        die_logged_out(f"{TIMEOUT_HOME} 秒内地址里没出现 token")
    log(f"    token={token}")
    return token


# 点保存前装的提交监听。
#
# 认「提交」不认地址：真正带着内容上行的那一发，请求体里必有 title0=。它落在哪个接口
# 不固定——错别字自检没开时直接走 /cgi-bin/operate_appmsg?sub=update，开着自检时整份
# 内容改由 /publicpoc/selfcheck?action=check 带上去（实测两种都能落库）。所以只认请求体，
# 不认 URL。自检的 pre_load_sentence 带的是 title= 不是 title0=，不会误判。
#
# 认「落库」看 get_appmsg_update_history：保存成功后页面会去刷「历史版本」，两条路径都刷。
_SAVE_WATCH = r"""(()=>{
if(window.__fragoSaveWatch){
  const s=window.__fragoSaveWatch;
  s.sent=false;s.title=null;s.ret=null;s.resp='';s.saved=false;
  return 'reset';
}
const st={sent:false,title:null,ret:null,resp:'',saved:false};
const XO=XMLHttpRequest.prototype.open, XS=XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open=function(m,u){this.__fragoUrl=u;return XO.apply(this,arguments)};
XMLHttpRequest.prototype.send=function(b){
  try{
    const u=String(this.__fragoUrl||'');
    const s=(typeof b==='string')?b:'';
    const m=/(?:^|&)title0=([^&]*)/.exec(s);
    const x=this;
    if(m){
      st.sent=true;
      st.title=decodeURIComponent(m[1].replace(/\+/g,' '));
      x.addEventListener('loadend',function(){
        let j=null;try{j=JSON.parse(x.responseText)}catch(e){}
        st.ret=(j&&j.base_resp)?j.base_resp.ret:(x.status===200?0:-1);
        st.resp=String(x.responseText||'').slice(0,300);
      });
    }else if(u.indexOf('get_appmsg_update_history')>=0){
      x.addEventListener('loadend',function(){st.saved=true});
    }
  }catch(e){}
  return XS.apply(this,arguments);
};
window.__fragoSaveWatch=st;
return 'installed';
})()"""


def _save_watch(group):
    """读提交监听的当前状态。返回 None 表示监听不在了——页面重载过。"""
    r = ejs_json("(()=>JSON.stringify(window.__fragoSaveWatch||null))()", group)
    return r if isinstance(r, dict) else None


def click_save(group):
    """点「保存为草稿」，等提交请求真正落库，再取草稿 ID。两种编辑器共用。

    别拿「地址里有 appmsgid」当保存完成的信号：更新已有草稿时地址一开始就带着
    appmsgid，那个判断立刻为真，调用方会在保存还没发出去时就导航走，把这一发掐掉。
    点击到提交之间隔着页面的「自检中」（错别字自检），实测能有二十秒。
    """
    log("[7/8] 点保存为草稿")
    before = current_url(group)
    had_id = bool(re.search(r"[?&]appmsgid=(\d+)", before))
    if ejs(_SAVE_WATCH, group) is None:
        die("装不上保存提交监听", "页面可能已失效，先跑 frago browser status 看看。")
    code = """(()=>{
const b=Array.from(document.querySelectorAll('button,.weui-desktop-btn,a'))
  .find(x=>x.innerText.trim()==='保存为草稿');
if(!b)return 'no-button';
const r=b.getBoundingClientRect();
const o={bubbles:true,cancelable:true,view:window,
         clientX:r.left+r.width/2,clientY:r.top+r.height/2};
['pointerdown','mousedown','pointerup','mouseup','click'].forEach(n=>
  b.dispatchEvent(n.startsWith('pointer')?new PointerEvent(n,o):new MouseEvent(n,o)));
return 'clicked';
})()"""
    if ejs(code, group) != "clicked":
        die("页面上找不到「保存为草稿」按钮",
            "公众号后台可能改版了，按钮文案变了。手动打开编辑器看一眼实际文案。")

    def submitted():
        u = current_url(group)
        if "/login" in u:
            die_logged_out("保存时跳到了登录页")
        st = _save_watch(group)
        if st is None:
            # 监听没了 = 页面重载过。重载只会发生在保存落库之后，按已提交处理。
            return {"reloaded": True}
        return st if st.get("sent") else None

    log("    等页面跑完错别字自检、把内容提交上去")
    st = wait_for(submitted, TIMEOUT_SAVE_SUBMIT,
                  "保存请求发出（页面卡在「自检中」超时）", group)

    if not st.get("reloaded"):
        log(f"    已提交，请求体里的标题是「{st.get('title')}」")

        def landed():
            cur = _save_watch(group)
            if cur is None:
                return {"reloaded": True}
            if cur.get("ret") not in (None, 0):
                die(f"后台没接受这次保存（ret={cur.get('ret')}）",
                    f"后台回的是：{cur.get('resp')}")
            return cur if cur.get("saved") else None

        st = wait_for(landed, TIMEOUT_SAVE_RESP, "保存落库（页面刷新历史版本）", group)

    def has_id():
        u = current_url(group)
        if "/login" in u:
            die_logged_out("保存后跳到了登录页")
        m = re.search(r"[?&]appmsgid=(\d+)", u)
        return m.group(1) if m else None

    if had_id:
        appmsgid = has_id()
        if not appmsgid:
            die("保存后地址里的草稿 ID 不见了", f"当时的地址：{current_url(group)}")
    else:
        appmsgid = wait_for(has_id, TIMEOUT_SAVE_ID, "保存后地址带出草稿 ID", group)
    return appmsgid, before
