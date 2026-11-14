/**
 * 员工页两个弹窗共用的壳。
 *
 * **点遮罩不关窗**，与站内通用浮窗（`components/ui/Modal`）同一条规矩：这两个窗里都有
 * 人刚填进去的东西——打了一半的第一句话、挑好的目录、改到一半的岗位说明。鼠标在窗外多
 * 点一下全都不见，而且没有任何东西提示刚才发生了什么，更没有撤回的办法。关窗只有两个
 * 明确的动作：右上角的叉，或 Esc。
 *
 * **外观收敛到全站唯一那套模态壳**（`base.css` 的 `.ui-modal-*`，即 C7）：遮罩、外框、
 * 头、体、底五处的内距与高度与 `components/ui/Modal` 逐项对齐。此前这里是自己写的一套
 * ——遮罩是纯黑 50% 不带令牌、外框是单层 1px 描边加一层大阴影、头高和关闭键位置也都
 * 自定。同一个站里两扇窗长得不一样，人换一页就得重新认一遍。
 *
 * 仍然不复用 `Modal` 组件本身，因为**宽度**：那个壳固定 `max-w-md`（448px），而这里要
 * 装业务语境原文与纳管目录清单，装不下。高度也不一样——内容长了要能滚，页头与页脚钉住
 * 不动。这两件事由 `.ui-modal-frame` 的可覆写宽度 + 本组件自己排的体实现。
 */

import { useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

interface DialogShellProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** 窗口宽度上限（px）。语境预览要宽一些，编辑弹窗窄一些。 */
  width?: number;
  /** 关窗这件事此刻能不能做。起会话正起着一半时不让关，否则人看不到结果。 */
  closable?: boolean;
}

export default function DialogShell({
  title,
  onClose,
  children,
  footer,
  width = 520,
  closable = true,
}: DialogShellProps) {
  useEffect(() => {
    if (!closable) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [closable, onClose]);

  return createPortal(
    <div className="ui-modal-backdrop">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="ui-modal-frame"
        style={{ maxWidth: `min(${width}px, 100%)` }}
      >
        <div className="ui-modal-head">
          <h3 className="ui-modal-title">{title}</h3>
          {closable ? (
            <button
              type="button"
              onClick={onClose}
              className="ui-icon-btn ui-modal-close"
              aria-label="Close"
            >
              <X size={16} strokeWidth={1.5} />
            </button>
          ) : null}
        </div>

        <div className="ui-modal-body flex flex-col gap-3">{children}</div>

        {footer ? <div className="ui-modal-foot">{footer}</div> : null}
      </div>
    </div>,
    document.body
  );
}
