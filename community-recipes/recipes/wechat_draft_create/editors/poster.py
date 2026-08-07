#!/usr/bin/env python3
"""贴图（image post，createType=8）编辑器驱动。

贴图编辑器形态：标题是 contenteditable 的 ProseMirror（上限 20 字），描述是另一个
ProseMirror（上限 1000 字），主图区是 `.image-selector` Vue 组件。保存按钮与文章共用
「保存为草稿」，跳转后 URL 带 appmsgid。

图片上传走两条门（见 wechat-writing/mp-tietu-image-upload-path）：
  1. 上游 POST /cgi-bin/filetransfer?action=upload_material 上素材库（普通 multipart）
  2. 下游把结果按 WebUploader 事件语义喂给 `.image-selector` 的公开方法
     uploadSelect → uploadComplete → uploadAllComplete，组件自己补 seq/宽高/选中。
"""

import json
import os
import time

from common import (WARNINGS, POLL, TIMEOUT_EDITOR, TIMEOUT_READY, TIMEOUT_SET,
                    die, die_logged_out, ejs, ejs_json, navigate, wait_for, log)

POSTER_NEW = ("https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2"
              "&action=edit&isNew=1&type=10&createType=8&token={token}&lang=zh_CN")
EDITOR_EDIT = ("https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2"
               "&action=edit&type=77&appmsgid={appmsgid}&token={token}&lang=zh_CN")

TITLE_MAX = 20
DESC_MAX = 1000
IMG_MAX = 20

# 图片 base64 全量塞进一次 exec-js 参数。ARG_MAX 上限 1MB（macOS），留余量给其他参数和 env。
# 超过这个量直接报错，不静默截断。
B64_ARG_LIMIT = 500_000

# 上传完成（含 formatList 补宽高）需要的时间，单位秒。
WAIT_AFTER_UPLOAD_ALL = 1.5

# 上传图片时同一编辑会话内的间隔，避开后台频控（ret=200013）。
GAP_BETWEEN_UPLOADS = 0.8

TYPE = "poster"

# 页面内注入的上传器：上传素材库 + 喂给 Vue 组件，定义 window.__fragoTietu.addImages。
# 与 worker 2026-08-06 验证过的 tietu-image-upload.js 一致。
_INJECTOR = r"""function() {
  function b64ToFile(b64, name, type) {
    var bin = atob(b64);
    var arr = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new File([arr], name, { type: type || 'image/png' });
  }
  function vmOf() {
    var el = document.querySelector('#js_content_top .image-selector') ||
             document.querySelector('.image-selector');
    if (!el || !el.__vue__) throw new Error('image-selector Vue 实例找不到');
    return el.__vue__;
  }
  function uploadUrl(vm) {
    var q = vm.uploadQuery || { scene: 5, writetype: 'doublewrite', groupid: 1 };
    return wx.url('/cgi-bin/filetransfer?action=upload_material&f=json' +
      '&scene=' + q.scene + '&writetype=' + q.writetype + '&groupid=' + q.groupid +
      '&ticket_id=' + wx.data.user_name + '&ticket=' + wx.data.ticket +
      '&svr_time=' + wx.data.time);
  }
  function readSize(file) {
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () { URL.revokeObjectURL(url); resolve({ width: img.naturalWidth, height: img.naturalHeight }); };
      img.onerror = function () { URL.revokeObjectURL(url); resolve({ width: 0, height: 0 }); };
      img.src = url;
    });
  }
  function uploadOne(vm, file) {
    var fd = new FormData();
    fd.append('file', file, file.name);
    return fetch(uploadUrl(vm), { method: 'POST', body: fd, credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var ret = j && j.base_resp ? j.base_resp.ret : -1;
        if (ret !== 0) throw new Error('upload_material ret=' + ret + ' ' + JSON.stringify(j).slice(0,200));
        return j;
      });
  }
  function addImages(items) {
    var api = window.__fragoTietu;
    api.result = { state: 'running', uploaded: [], error: null };
    var vm;
    try { vm = vmOf(); } catch (e) { api.result = { state: 'error', error: '' + e }; return; }
    // 替换语义：传了图就先清空现有图片，再传新的。更新草稿时旧图不会残留成重复。
    // 不带图更新（只改文字）不会走到这里，旧图保留。
    vm.innerList = [];
    vm.selected = null;
    if (items.length > 20) {
      api.result = { state: 'error', error: '超过 20 张上限' };
      return;
    }
    var chain = Promise.resolve();
    items.forEach(function (it, idx) {
      chain = chain.then(function () {
        var file = b64ToFile(it.b64, it.name || ('img' + idx + '.png'), it.type);
        return readSize(file).then(function (sz) {
          return uploadOne(vm, file).then(function (resp) {
            var tmpId = 'FRAGO_' + idx + '_' + file.size;
            vm.uploadSelect({ id: tmpId, size: file.size,
              extension: (file.name.split('.').pop() || 'png').toLowerCase(),
              width: sz.width, height: sz.height });
            vm.uploadComplete({ id: tmpId }, { content: resp.content, cdn_url: resp.cdn_url });
            api.result.uploaded.push({ file_id: resp.content, cdn_url: resp.cdn_url, w: sz.width, h: sz.height });
          });
        });
      });
    });
    chain.then(function () {
      vm.uploadAllComplete();
      return new Promise(function (r) { setTimeout(r, 1500); });
    }).then(function () {
      api.result.state = 'done';
      api.result.innerList = vm.innerList.map(function (x) {
        return { file_id: x.file_id, seq: x.seq, loading: x.loading, width: x.width, height: x.height };
      });
      api.result.selected = vm.selected;
    }).catch(function (e) {
      api.result.state = 'error';
      api.result.error = '' + (e && e.message ? e.message : e);
    });
  }
  window.__fragoTietu = { addImages: addImages, result: null };
  return 'ready';
}"""


# 取编辑器组件本体的办法：给元素和想要的方法名，返回真正带这个方法的那个组件。
#
# 认方法不认层级，是因为层级不稳定：`.title-editor-overlay` 上挂的 __vue__ 不一定是
# mp-title-editor——外层匿名包装组件和它共用同一个根元素，__vue__ 谁后挂载谁写上去。
# 实测编辑已有草稿时拿到的是本体，新建时拿到的是外层包装，后者没有 getView，直接调
# 就报「不是函数」。
# 描述那边则是读写本来就分家：写要 getView（在里层 MpEditor 上），读要 getContent
# （在外层 mp-common-share-editor 上），同一个元素取不到两样东西。
_VM = """function(sel,m){
  const el=document.querySelector(sel);
  if(!el||!el.__vue__)return null;
  let v=el.__vue__;
  for(let i=0;i<5&&v&&typeof v[m]!=='function';i++)v=v.$refs&&v.$refs.editor;
  return (v&&typeof v[m]==='function')?v:null;
}"""
TITLE_SEL = "#js_title_main .title-editor-overlay"
DESC_SEL = ".share-text__area"        # 写：里层 MpEditor，有 getView
DESC_READ_SEL = "#guide_words_main"   # 读：外层 mp-common-share-editor，有 getContent

# 组件挂载完成的判据：本体拿得到，且它已经能交出 ProseMirror view。
_MOUNTED = ("(()=>{const vmOf=(%s);const v=vmOf(%%s,'getView');"
            "if(!v)return false;try{return !!v.getView()}catch(e){return false}})()" % _VM)


def current_url(group):
    return ejs("(()=>location.href)()", group) or ""


def open_editor(token, group, appmsgid=None):
    if appmsgid:
        url = EDITOR_EDIT.format(appmsgid=appmsgid, token=token)
        log("[2/8] 打开已有贴图草稿 appmsgid={appmsgid}".format(appmsgid=appmsgid))
    else:
        url = POSTER_NEW.format(token=token)
        log("[2/8] 打开新建贴图编辑器")
    navigate(url, group)

    # 光看到 .ProseMirror 还不算就绪：标题编辑器的 Vue 组件（往后所有写入都经它）
    # 挂载得比裸 DOM 晚，新建页尤其明显。等到组件挂上、且能拿出 view 才算数。
    def probe():
        u = current_url(group)
        if "/login" in u:
            die_logged_out("编辑器页跳到了登录页")
        return ejs(_MOUNTED % json.dumps(TITLE_SEL), group) is True

    wait_for(probe, TIMEOUT_EDITOR, "贴图编辑器的标题组件挂载完成", group)


def wait_editor_ready(group):
    log("[3/8] 等贴图编辑器就绪")
    has_bridge = ejs("(()=>!!window.__MP_Editor_JSAPI__)()", group)
    if has_bridge is not True:
        die("贴图编辑器页面上没有官方桥 __MP_Editor_JSAPI__",
            "可能是页面没加载完、公众号改版、或者登录态失效。先手动打开一次贴图编辑器确认。")

    def probe():
        ejs("(()=>{window.__fr=window.__fr||{};"
            "window.__MP_Editor_JSAPI__.invoke({apiName:'mp_editor_get_isready',"
            "sucCb:r=>window.__fr.ready=r,errCb:e=>window.__fr.ready={err:1}});"
            "return 'sent'})()", group)
        time.sleep(POLL)
        r = ejs_json("(()=>JSON.stringify(window.__fr&&window.__fr.ready||null))()", group)
        return isinstance(r, dict) and r.get("isReady") is True

    wait_for(probe, TIMEOUT_READY, "贴图编辑器回报已就绪", group)


def set_title(title, group):
    """标题分两步写进 mp-title-editor，两步都要，缺一个都会在更新草稿时出问题。

    保存时页面调的是组件的 getContent()，它实时序列化 ProseMirror view 的文档——
    view 才是权威。隐藏域 textarea#title 只是镜像（实测：把镜像改成别的字，
    提交上去的仍是 view 里的字），execCommand 只改 DOM 更是白改。

    但只 dispatch 也不够：组件 data 里的 currentContent 是渲染 ProseMirror 的数据源，
    dispatch 不会更新它。它一直停在打开草稿时的旧标题上，一旦组件重渲染就会把旧标题
    灌回 view。所以先 setContent 把 currentContent 对齐，再 dispatch 把 view 对齐
    并触发 input 事件同步镜像和字数统计。
    """
    log(f"[4/8] 设贴图标题（{len(title)} 字）")
    seed = """(()=>{
const v=(%s)(%s,'setContent');
if(!v)return JSON.stringify({ok:false,why:'no-component'});
v.setContent(%s);
return JSON.stringify({ok:true});
})()""" % (_VM, json.dumps(TITLE_SEL), json.dumps(title))
    r = ejs_json(seed, group)
    if not isinstance(r, dict) or not r.get("ok"):
        die("标题编辑器没找到", f"编辑器里现在是：{r}")
    time.sleep(POLL)

    code = """(()=>{
const v=(%s)(%s,'getView');
if(!v)return JSON.stringify({ok:false,why:'no-component'});
const view=v.getView();
if(!view)return JSON.stringify({ok:false,why:'no-view'});
const st=view.state;
view.dispatch(st.tr.insertText(%s,0,st.doc.content.size));
return JSON.stringify({ok:true});
})()""" % (_VM, json.dumps(TITLE_SEL), json.dumps(title))
    r = ejs_json(code, group)
    if not isinstance(r, dict) or not r.get("ok"):
        die("标题编辑器的 ProseMirror view 拿不到", f"编辑器里现在是：{r}")

    check = """(()=>{
const v=(%s)(%s,'getContent');
if(!v)return JSON.stringify({});
let g='';try{g=v.getContent()||''}catch(e){}
const ta=(document.querySelector('textarea#title')||{}).value||'';
return JSON.stringify({g:g.trim(),c:(v.currentPlainContent||'').trim(),ta:ta.trim()});
})()""" % (_VM, json.dumps(TITLE_SEL))

    def probe():
        rr = ejs_json(check, group)
        return (isinstance(rr, dict) and rr.get("g") == title
                and rr.get("c") == title and rr.get("ta") == title)

    wait_for(probe, TIMEOUT_SET, "标题写入并同步（view/组件数据/隐藏域三处一致）", group)
    time.sleep(0.5)


def set_description(desc, group):
    """描述走 MpEditor.getView() 的官方事务 API。execCommand 同样只改 DOM，更新时丢内容。"""
    log(f"[5/8] 设贴图描述（{len(desc)} 字）")

    def mounted():
        return ejs(_MOUNTED % json.dumps(DESC_SEL), group) is True

    wait_for(mounted, TIMEOUT_SET, "描述编辑器组件挂载完成", group)
    code = """(()=>{
const v=(%s)(%s,'getView');
if(!v)return JSON.stringify({ok:false,why:'no-component'});
const view=v.getView();
if(!view)return JSON.stringify({ok:false,why:'no-view'});
const st=view.state;
view.dispatch(st.tr.insertText(%s,0,st.doc.content.size));
return JSON.stringify({ok:true});
})()""" % (_VM, json.dumps(DESC_SEL), json.dumps(desc))
    r = ejs_json(code, group)
    if not isinstance(r, dict) or not r.get("ok"):
        die("描述编辑器没找到", f"编辑器里现在是：{r}")

    check = """(()=>{
const v=(%s)(%s,'getContent');
const d=(document.querySelector('.share-text__input .ProseMirror')||{}).innerText||'';
let c='';try{c=v?v.getContent()||'':''}catch(e){c='err:'+e.message}
return JSON.stringify({d:d.trim(),c:(c||'').trim()});
})()""" % (_VM, json.dumps(DESC_READ_SEL))

    def probe():
        rr = ejs_json(check, group)
        return (isinstance(rr, dict) and rr.get("d") == desc and rr.get("c") == desc)

    wait_for(probe, TIMEOUT_SET, "描述写入并同步", group)
    time.sleep(0.5)


def upload_images(image_paths, group):
    if not image_paths:
        return [], []
    log(f"[5/8] 上传 {len(image_paths)} 张图")

    items = []
    for path in image_paths:
        if not os.path.isfile(path):
            die(f"图片文件不存在：{path}")
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            die(f"读图片失败：{path}：{e}")
        ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
        items.append({
            "b64": __import__("base64").b64encode(data).decode(),
            "name": os.path.basename(path),
            "type": "image/png" if ext == "png" else "image/jpeg",
        })
    total_b64 = sum(len(it["b64"]) for it in items)
    if total_b64 > B64_ARG_LIMIT:
        die(f"图片 base64 共 {total_b64} 字符，超过 {B64_ARG_LIMIT} 上限",
            "图片可能过大，或一次传的图太多。单张控制在几百 KB 内，或分批调用。")
    if len(items) > IMG_MAX:
        die(f"一次最多 {IMG_MAX} 张图，收到 {len(items)} 张")

    payload = json.dumps(items, ensure_ascii=False)
    code = ("(function(){ var ready=(%s)();"
            "window.__fragoTietu.addImages(%s); return 'kicked'; })()"
            % (_INJECTOR, payload))
    if ejs(code, group) is None:
        die("上传脚本没跑起来", "图片注入脚本执行失败，页面可能已失效。")

    deadline = time.time() + 60 + 5 * len(items)
    last = None
    while time.time() < deadline:
        time.sleep(1.0)
        last = ejs_json("(()=>JSON.stringify(window.__fragoTietu&&window.__fragoTietu.result||null))()",
                        group)
        if isinstance(last, dict):
            if last.get("state") == "error":
                die("图片上传失败：" + str(last.get("error")),
                    "上传素材库接口可能频控（稍后重试）或登录态已失效。")
            if last.get("state") == "done":
                got = last.get("innerList") or []
                if len(got) != len(items):
                    die(f"图片进了 {len(got)} 张，预期 {len(items)} 张",
                        "改版会导致静默失败：上传成功但图不进 innerList。请人工打开编辑器确认。")
                log(f"    {len(got)} 张图已进编辑器（file_id: "
                    + ", ".join(str(x.get("file_id")) for x in got) + "）")
                return got, last.get("uploaded") or []
    die("图片上传超时", f"最后状态：{last}")

    return [], []  # unreachable


def read_state(group):
    """读回标题/描述/图片数。标题读 getContent()——保存时页面读的就是这一个，
    自检读它才等于自检了将要被提交的东西。currentPlainContent 只是它的缓存副本。"""
    code = """(()=>{
const vmOf=(%s);
const t=vmOf(%s,'getContent');
let title='';
if(t){try{title=(t.getContent()||'').trim()}catch(e){}}
const g=vmOf(%s,'getContent');
let desc='';
if(g){try{desc=(g.getContent()||'').trim()}catch(e){}}
const vm=document.querySelector('.image-selector');
return JSON.stringify({
  title:title,
  desc:desc,
  images:vm&&vm.__vue__&&vm.__vue__.innerList?vm.__vue__.innerList.length:0
});
})()""" % (_VM, json.dumps(TITLE_SEL), json.dumps(DESC_READ_SEL))
    r = ejs_json(code, group)
    if not isinstance(r, dict):
        return None
    if r.get("desc") == "填写描述信息，让大家了解更多内容":
        r["desc"] = ""
    return r


def precheck(sent, group):
    """点保存前确认标题/描述/图片都到位。空的就报错——不点保存。"""
    log("[6/8] 存前自检")
    got = read_state(group)
    if not got:
        die("存前自检读不回状态", "不点保存，避免在草稿箱留下空内容。")
    if got.get("title") != sent.get("title"):
        die(f"存前自检不通过：标题应为「{sent.get('title')}」，编辑器里是「{got.get('title')}」",
            "不点保存。")
    if sent.get("desc") and not got.get("desc"):
        die("存前自检不通过：描述没写进去", "不点保存。")
    if sent.get("images") and got.get("images") != sent.get("images"):
        die(f"存前自检不通过：图片应为 {sent.get('images')} 张，编辑器里 {got.get('images')} 张",
            "不点保存。")
    log(f"    编辑器里标题「{got.get('title')}」/ 描述 {len(got.get('desc'))} 字 / "
        f"{got.get('images')} 张图")
    return got


def verify_stored(token, appmsgid, sent, group):
    log("[8/8] 重开贴图草稿回读校验")
    url = EDITOR_EDIT.format(appmsgid=appmsgid, token=token)

    def open_and_read():
        navigate(url, group)

        def probe():
            if ejs("(()=>!!window.__MP_Editor_JSAPI__)()", group) is not True:
                return False
            return ejs(_MOUNTED % json.dumps(TITLE_SEL), group) is True

        wait_for(probe, TIMEOUT_EDITOR, "贴图草稿重新打开", group)
        time.sleep(0.5)
        return read_state(group)

    # 页面加载完就定死了这一份数据，原地轮询它一万年也不会变。要么这一次就对，
    # 要么重新导航再取一份。留两次重开的余地，兜住后台落库比回读慢半拍的情况。
    got = open_and_read()
    for _ in range(2):
        if got and got.get("title") == sent.get("title"):
            break
        log("    回读到的还是旧标题，重开一次再看")
        time.sleep(2)
        got = open_and_read()

    if not got:
        WARNINGS.append("回读校验没读到状态，草稿可能已建成但内容存疑，请人工打开确认")
        return {"title": "", "desc": "", "images": 0}
    if got.get("title") != sent.get("title"):
        die(f"回读校验不通过：标题应为「{sent.get('title')}」，草稿里是「{got.get('title')}」",
            f"草稿已建成（ID {appmsgid}），请人工打开确认。")
    if sent.get("desc") and sent.get("desc") not in (got.get("desc") or ""):
        die(f"回读校验不通过：描述内容没保住，草稿里是「{got.get('desc')}」",
            f"草稿已建成（ID {appmsgid}），请人工打开确认。")
    if sent.get("images") and got.get("images") != sent.get("images"):
        die(f"回读校验不通过：图片应为 {sent.get('images')} 张，草稿里 {got.get('images')} 张",
            f"草稿已建成（ID {appmsgid}），请人工打开确认。")
    log(f"    草稿里标题「{got.get('title')}」/ 描述 {len(got.get('desc'))} 字 / "
        f"{got.get('images')} 张图")
    return got
