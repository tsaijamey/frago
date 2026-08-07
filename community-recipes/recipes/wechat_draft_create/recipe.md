---
name: wechat_draft_create
type: atomic
runtime: python
version: "1.1"
description: "把内容送进公众号草稿箱（文章/贴图两种类型）：走后台编辑器官方 JSAPI 与 Vue 组件接口，吃网页登录态，不需要 AppSecret 和 IP 白名单"
use_cases:
  - "接 markdown_to_wechat_html 的产出，一步把排好版的文章落成公众号草稿"
  - "建贴图（image post, createType=8）草稿：标题 + 描述 + 最多 20 张图"
  - "个人主体或未认证账号被回收发布接口权限时，绕开开放接口建草稿"
  - "干跑模式把内容填进编辑器不保存，人肉眼确认排版后再决定要不要落"
  - "拿草稿 ID 更新已有草稿，反复调整不产生新草稿"
tags:
  - wechat
  - mp
  - draft
  - publishing
  - browser
output_targets:
  - stdout
inputs:
  content_type:
    type: string
    required: false
    description: "article（默认，图文）或 poster（贴图）。贴图=图+标题(≤20字)+描述(≤1000字)"
  title:
    type: string
    required: true
    description: "标题。文章上限 64 字，贴图上限 20 字，超长直接报错"
  html_path:
    type: string
    required: false
    description: "排好版的 HTML 文件路径（仅 article）。与 content 二选一，两个都不给直接报错"
  content:
    type: string
    required: false
    description: "直接给 HTML 全文（仅 article）"
  cover:
    type: string
    required: false
    description: "文章封面图文件路径（仅 article）。上传素材库后调官方桥设封面，建议 700KB 内"
  description:
    type: string
    required: false
    description: "贴图描述，公众号上限 1000 字"
  images:
    type: array
    required: false
    description: "贴图图片文件路径列表（也可给单路径字符串）。更新草稿时传图=替换旧图，不传图=保留旧图。单张建议几百 KB 内"
  author:
    type: string
    required: false
    description: "文章作者，公众号上限 8 字（仅 article）"
  appmsgid:
    type: string
    required: false
    description: "给了就更新这篇已有草稿，不给就新建"
  browser_group:
    type: string
    required: false
    description: "frago browser 的分组名，默认 wechat_draft"
  verify:
    type: boolean
    required: false
    description: "保存后是否回读校验，默认 true"
  dry_run:
    type: boolean
    required: false
    description: "只把内容填进编辑器不点保存，默认 false"
outputs:
  success:
    type: boolean
    description: "是否成功。任何一步没达成预期都为 false 且退出码非零"
  appmsgid:
    type: string
    description: "草稿 ID。干跑时为空"
  draft_url:
    type: string
    description: "可直接打开的草稿编辑地址"
  title:
    type: string
    description: "标题"
  description:
    type: string
    description: "回读到的贴图描述（仅 poster）"
  images:
    type: integer
    description: "回读到的贴图图片数（仅 poster）"
  uploaded_files:
    type: array
    description: "本次上传的素材 file_id 列表（仅 poster 且传了图）"
  sent_chars:
    type: integer
    description: "送进编辑器的文章字符数（仅 article）"
  stored_chars:
    type: integer
    description: "回读到的文章字符数（仅 article）"
  sent_styles:
    type: integer
    description: "送进去的行内样式数（仅 article）"
  stored_styles:
    type: integer
    description: "回读到的行内样式数（仅 article）"
  tables:
    type: integer
    description: "回读到的文章表格数（仅 article）"
  elapsed_sec:
    type: number
    description: "整段耗时"
  warnings:
    type: array
    description: "回读校验对不上的项、以及其他非致命提示"
---

# wechat_draft_create

把内容送进公众号草稿箱，支持**文章（图文）**与**贴图（image post）**两种内容类型。

## 走的哪条路

不走开放接口。公众号的开放接口要 AppSecret、要出口 IP 登记白名单，而且 2025 年 7 月起个人主体账号、企业主体未认证账号被回收了发布相关接口权限。

走的是后台编辑器页面上的官方桥 `window.__MP_Editor_JSAPI__`——微信开给第三方插件用的接口，有正式文档（`developers.weixin.qq.com/doc/subscription/guide/product/mp_editor_jsapi.html`）。文章的正文用它设置，行内样式一个不掉。

贴图（createType=8）没有正文，是「图 + 标题 + 描述」的轻量形态，走编辑器自己的 Vue 组件接口：
- 标题/描述是 ProseMirror 富文本，写入必须走组件暴露的 ProseMirror `view.dispatch()` 事务 API——execCommand 只改 DOM 不同步内部状态、组件的 `setContent` 只改 Vue 数据不碰 view，保存时都会丢（见 `wechat-writing/mp-tietu-image-upload-path`）
- 图片上传：上游 `POST /cgi-bin/filetransfer?action=upload_material` 上素材库（普通 multipart，同源带 cookie），下游把结果按 WebUploader 事件语义喂给 `.image-selector` 的 `uploadSelect → uploadComplete → uploadAllComplete`，组件自己补 seq/宽高/选中

代价是吃网页登录态：浏览器里公众号后台必须是登录状态，登录态失效就跑不动。

## 动作序列（两种类型共用骨架）

1. 导航后台首页，从重定向后的地址里取 token（不写死，随会话变）
2. 打开目标类型的编辑器页（article: type=10；poster: createType=8；更新都是 type=77&appmsgid）
3. 等编辑器就绪（官方接口回报 isReady，poster 另等标题 ProseMirror）
4. 填内容（article: 标题+正文；poster: 标题+描述+图片）
5. 点保存前先读一次确认内容真进去了
6. 点「保存为草稿」（五连事件：pointerdown/mousedown/pointerup/mouseup/click）
7. 从跳转后的地址取草稿 ID，重开草稿回读校验

## 已知的失败路径（别改成这些写法）

- 合成 ClipboardEvent 粘贴富文本 → 被编辑器降级成纯文本，样式全丢
- 直接给编辑器容器赋 innerHTML → 保存时被内部状态重新渲染覆盖
- 去读 `.ProseMirror` 容器的 innerHTML 判断正文 → 那不是正文区，正文只能用 mp_editor_get_content 读
- 朴素 `<li>文字</li>` 直接送，或 `<li>` 之间带换行/缩进 → 公众号编辑器会把 li 之间的空白解析成空列表项、
  把无 section 包裹的 li 拆成「空 li + 文字 li」两段，项目符号落在空行上。
  配方已自动处理：压缩 ul 内标签间空白 + 给朴素 li 包 `<section>`（带 li 的行内样式）。
  排版配方（markdown_to_wechat_html）的标准输出两者都规避，不受影响
- 贴图标题用 execCommand 或组件的 `setContent` 写入 → 只改 DOM/Vue 数据，保存读的是 ProseMirror view 状态，更新草稿时会丢，必须走 `getView().dispatch()` 事务
- 贴图重开校验读太快 → 重开页标题先渲染旧值、服务器提交后翻新，要等标题等于预期值再校验

## 用法

```bash
# 接排版配方的产出建文章草稿（可带封面）
frago recipe run wechat_draft_create --params '{"title":"我的文章","html_path":"/path/to/article.html","cover":"/path/to/cover.png"}'

# 建贴图草稿（图 + 标题 + 描述）
frago recipe run wechat_draft_create --params '{"content_type":"poster","title":"贴图标题","description":"描述文字","images":["/path/a.png","/path/b.png"]}'

# 更新已有贴图草稿（传图替换旧图，不传图保留旧图）
frago recipe run wechat_draft_create --params '{"content_type":"poster","title":"新标题","description":"新描述","images":["/path/c.png"],"appmsgid":"200005074"}'

# 干跑：填进编辑器不保存，人肉确认排版
frago recipe run wechat_draft_create --params '{"content_type":"poster","title":"贴图标题","description":"描述","dry_run":true}'
```
