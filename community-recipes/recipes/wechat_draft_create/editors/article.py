#!/usr/bin/env python3
"""文章（图文，type=10/createType 无）编辑器驱动。

把排好版的 HTML 送进标准图文编辑器：官方桥 window.__MP_Editor_JSAPI__ 的
mp_editor_set_content 设全文，行内样式一个不掉。
"""

import json
import time

from common import (WARNINGS, POLL, TIMEOUT_EDITOR, TIMEOUT_READY, TIMEOUT_SET,
                    die, die_logged_out, ejs, ejs_json, navigate, wait_for, log)

EDITOR_NEW = ("https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2"
              "&action=edit&isNew=1&type=10&token={token}&lang=zh_CN")
EDITOR_EDIT = ("https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2"
               "&action=edit&type=77&appmsgid={appmsgid}&token={token}&lang=zh_CN")

TITLE_MAX = 64
AUTHOR_MAX = 8

# 动作之间的间隔。编辑器有自己的防抖和自动保存，抢太快会丢内容。
GAP_AFTER_TITLE = 1.0
GAP_AFTER_CONTENT = 2.0

TYPE = "article"


def current_url(group):
    return ejs("(()=>location.href)()", group) or ""


def open_editor(token, group, appmsgid=None):
    if appmsgid:
        url = EDITOR_EDIT.format(appmsgid=appmsgid, token=token)
        log("[2/8] 打开已有草稿 appmsgid={appmsgid}".format(appmsgid=appmsgid))
    else:
        url = EDITOR_NEW.format(token=token)
        log("[2/8] 打开新建编辑器")
    navigate(url, group)

    def probe():
        u = current_url(group)
        if "/login" in u:
            die_logged_out("编辑器页跳到了登录页")
        return ejs("(()=>!!document.querySelector('#title'))()", group) is True

    wait_for(probe, TIMEOUT_EDITOR, "编辑器页出现标题输入框", group)


def wait_editor_ready(group):
    log("[3/8] 等编辑器就绪")
    has_bridge = ejs("(()=>!!window.__MP_Editor_JSAPI__)()", group)
    if has_bridge is not True:
        die("编辑器页面上没有官方桥 __MP_Editor_JSAPI__",
            "可能是页面没加载完、公众号改版、或者登录态失效。先在浏览器里手动打开一次编辑器确认。")

    def probe():
        ejs("(()=>{window.__fr=window.__fr||{};"
            "window.__MP_Editor_JSAPI__.invoke({apiName:'mp_editor_get_isready',"
            "sucCb:r=>window.__fr.ready=r,errCb:e=>window.__fr.ready={err:1}});"
            "return 'sent'})()", group)
        time.sleep(POLL)
        r = ejs_json("(()=>JSON.stringify(window.__fr&&window.__fr.ready||null))()", group)
        if isinstance(r, dict) and r.get("isReady"):
            if not r.get("isNew"):
                WARNINGS.append("编辑器回报 isNew=false，设置全文内容的接口可能不可用")
            return True
        return False

    wait_for(probe, TIMEOUT_READY, "编辑器回报已就绪", group)


def set_title(title, author, group):
    log(f"[4/8] 设标题（{len(title)} 字）")
    code = """(()=>{
const t=document.querySelector('#title');
if(!t)return 'no-title';
t.focus();
const s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
s.call(t,%s);
t.dispatchEvent(new Event('input',{bubbles:true}));
t.dispatchEvent(new Event('change',{bubbles:true}));
let au='';
if(%s){
  const a=document.querySelector('#author');
  if(a){a.focus();
    const s2=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
    s2.call(a,%s);a.dispatchEvent(new Event('input',{bubbles:true}));au=a.value;}
}
return JSON.stringify({title:t.value,author:au});
})()""" % (json.dumps(title), json.dumps(bool(author)), json.dumps(author or ""))
    r = ejs_json(code, group)
    if not isinstance(r, dict) or r.get("title") != title:
        die("标题没能写进编辑器", f"编辑器里现在是：{r}")
    if author and not r.get("author"):
        WARNINGS.append("作者字段没找到输入框，已跳过")
    time.sleep(GAP_AFTER_TITLE)


def set_content(html, group):
    log(f"[5/8] 设正文（{len(html)} 字符）")
    code = """(()=>{
window.__fr=window.__fr||{};window.__fr.set=null;
window.__MP_Editor_JSAPI__.invoke({
  apiName:'mp_editor_set_content',
  apiParam:{content:%s},
  sucCb:r=>window.__fr.set=r||{msg:'ok'},
  errCb:e=>window.__fr.set={err:String(e&&e.msg||e)}
});
return 'sent';
})()""" % json.dumps(html)
    if ejs(code, group) is None:
        die("调用设置全文内容的接口失败", "HTML 可能过大导致传参被截断，或者页面已失效。")

    def probe():
        r = ejs_json("(()=>JSON.stringify(window.__fr&&window.__fr.set||null))()", group)
        if isinstance(r, dict) and r.get("err"):
            die("编辑器拒绝了这份内容", str(r.get("err"))[:300])
        return isinstance(r, dict)

    wait_for(probe, TIMEOUT_SET, "编辑器回报内容已设置", group)
    time.sleep(GAP_AFTER_CONTENT)


def set_cover(cover_path, group):
    """上传封面图并设到草稿上。两条链路：upload_material 上素材库拿 cdn_url，
    再调官方桥 mp_editor_change_cover({oriImgUrl})。scene=2 实测有效。"""
    log("[5/8] 设封面（%s）" % cover_path)
    import os
    import base64 as _b64
    if not os.path.isfile(cover_path):
        die(f"封面图片文件不存在：{cover_path}")
    try:
        with open(cover_path, "rb") as f:
            data = f.read()
    except OSError as e:
        die(f"读封面图片失败：{cover_path}：{e}")
    if len(data) > 700_000:
        die(f"封面图片 {len(data)} 字节，超过约 700KB 上限",
            "exec-js 命令行装不下太大的 base64，压缩后再试。")
    b64 = _b64.b64encode(data).decode()
    code = """(()=>{
window.__fr=window.__fr||{};window.__fr.cov={state:'start'};
const b64=%s;
const bin=atob(b64);const arr=new Uint8Array(bin.length);
for(let i=0;i<bin.length;i++)arr[i]=bin.charCodeAt(i);
const file=new File([arr],'cover.png',{type:'image/png'});
const fd=new FormData();
fd.append('file',file,'cover.png');
const url=wx.url('/cgi-bin/filetransfer?action=upload_material&f=json&scene=2'
  +'&writetype=doublewrite&groupid=1&ticket_id='+wx.data.user_name
  +'&ticket='+wx.data.ticket+'&svr_time='+wx.data.time);
window.__fr.cov.state='uploading';
fetch(url,{method:'POST',body:fd,credentials:'same-origin'})
 .then(function(r){return r.json()})
 .then(function(j){
   const ret=j&&j.base_resp?j.base_resp.ret:-1;
   if(ret!==0){window.__fr.cov={state:'up-error',ret:ret,resp:JSON.stringify(j).slice(0,200)};return}
   window.__fr.cov.cdn=j.cdn_url;
   window.__fr.cov.state='setting';
   window.__MP_Editor_JSAPI__.invoke({
     apiName:'mp_editor_change_cover',
     apiParam:{oriImgUrl:j.cdn_url},
     sucCb:function(r){window.__fr.cov={state:'done',msg:(r&&r.msg)||'ok'}},
     errCb:function(e){window.__fr.cov={state:'set-error',err:String(e&&e.msg||e)}}
   });
 })
 .catch(function(e){window.__fr.cov={state:'err',err:String(e)}});
return 'started';
})()""" % json.dumps(b64)
    if ejs(code, group) is None:
        die("封面脚本没跑起来", "图片注入失败，页面可能已失效。")

    deadline = time.time() + 60
    last = None
    while time.time() < deadline:
        time.sleep(1.0)
        last = ejs_json("(()=>JSON.stringify(window.__fr&&window.__fr.cov||null))()", group)
        if not isinstance(last, dict):
            continue
        if last.get("state") in ("up-error", "set-error", "err"):
            die(f"封面设置失败（{last.get('state')}）：{last.get('err') or last.get('resp') or last.get('ret')}",
                "上传素材库可能频控或登录态失效。")
        if last.get("state") == "done":
            log(f"    封面已设置（{last.get('msg')}）")
            return
    die("封面设置超时", f"最后状态：{last}")


def cover_set(group):
    """重开草稿后检查封面是否在：封面预览/侧栏缩略图带 mmbiz 背景图就算在。"""
    r = ejs_json("""(()=>{const els=Array.from(document.querySelectorAll(
'.js_cover_preview_new,.card_appmsg_thumb,.js_cover_preview,select-cover__preview'));
let hit=false;
for(const el of els){const bg=getComputedStyle(el).backgroundImage;
  if(bg.indexOf('mmbiz')>=0){hit=true;break}}
return JSON.stringify({hit})})()""", group)
    return isinstance(r, dict) and r.get("hit") is True


def read_content(group):
    """用官方接口读全文。NEVER 去读 .ProseMirror 容器的 innerHTML——那不是正文区。"""
    ejs("(()=>{window.__fr=window.__fr||{};window.__fr.got=null;"
        "window.__MP_Editor_JSAPI__.invoke({apiName:'mp_editor_get_content',"
        "sucCb:r=>window.__fr.got=r,errCb:e=>window.__fr.got={err:1}});return 'sent'})()", group)
    deadline = time.time() + TIMEOUT_SET
    while time.time() < deadline:
        time.sleep(POLL)
        r = ejs_json("(()=>{const g=window.__fr&&window.__fr.got;if(!g)return 'null';"
                     "const c=g.content||'';return JSON.stringify({len:c.length,"
                     "styles:(c.match(/style=/g)||[]).length,"
                     "tables:(c.match(/<table/g)||[]).length,"
                     "images:(c.match(/<img/g)||[]).length})})()", group)
        if isinstance(r, dict):
            return r
    return None


def precheck(sent_len, group):
    """点保存之前先确认内容真的进去了。空的就报错——点了就是一篇空草稿留在人家草稿箱。"""
    log("[6/8] 存前自检")
    got = read_content(group)
    if not got:
        die("存前自检读不回内容", "不点保存，避免在草稿箱留下空文章。")
    if got["len"] < sent_len * 0.5:
        die(f"存前自检不通过：送进去 {sent_len} 字符，编辑器里只有 {got['len']} 字符",
            "不点保存，避免在草稿箱留下残缺文章。")
    log(f"    编辑器里 {got['len']} 字符 / {got['styles']} 处行内样式")
    return got


def verify_stored(token, appmsgid, sent, group):
    log("[8/8] 重开草稿回读校验")
    navigate(EDITOR_EDIT.format(appmsgid=appmsgid, token=token), group)

    def probe():
        return ejs("(()=>!!(document.querySelector('#title')&&window.__MP_Editor_JSAPI__))()",
                   group) is True

    wait_for(probe, TIMEOUT_EDITOR, "草稿重新打开", group)
    got = read_content(group)
    if not got:
        WARNINGS.append("回读校验没读到内容，草稿可能已建成但内容存疑，请人工打开确认")
        return {"len": 0, "styles": 0, "tables": 0, "images": 0}

    # 服务器会剥掉根容器的 id、给文字节点包上自己的标记，字符数略有出入属正常。
    if sent["styles"] and got["styles"] < sent["styles"] * 0.5:
        die(f"回读校验不通过：送进去 {sent['styles']} 处行内样式，草稿里只剩 {got['styles']} 处",
            f"草稿已建成（ID {appmsgid}），但排版没保住，请人工打开确认。")
    # 服务器会做归一化（合并等价声明、剥掉根容器的 id），行内样式数差个一两处属正常，
    # 差 5% 以上才值得提醒。表格和图片是结构性的，少一个就该说。
    if abs(got["styles"] - sent["styles"]) > max(2, sent["styles"] * 0.05):
        WARNINGS.append(f"行内样式数量对不上：送进去 {sent['styles']}，草稿里 {got['styles']}")
    for key, label in (("tables", "表格"), ("images", "图片")):
        if got[key] != sent[key]:
            WARNINGS.append(f"{label}数量对不上：送进去 {sent[key]}，草稿里 {got[key]}")
    if sent.get("cover"):
        if cover_set(group):
            log("    封面在")
        else:
            die(f"回读校验不通过：封面没保住",
                f"草稿已建成（ID {appmsgid}），封面区仍是空的，请人工打开确认。")
    log(f"    草稿里 {got['len']} 字符 / {got['styles']} 处行内样式 / "
        f"{got['tables']} 个表格 / {got['images']} 张图")
    return got
