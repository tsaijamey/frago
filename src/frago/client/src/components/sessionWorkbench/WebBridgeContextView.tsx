import { useState } from 'react';
import { ChevronDown, ChevronRight, ExternalLink, Paperclip } from 'lucide-react';
import MarkdownContent from '@/components/ui/MarkdownContent';
import {
  splitFocusAnchorSegments,
  type ParsedWebBridgeContext,
  type WebBridgeFocusItem,
  type WebBridgePageContext,
} from '@/utils/webBridgeContext';

function FocusQuoteCard({ item }: { item: WebBridgeFocusItem }) {
  return (
    <div
      data-testid="web-bridge-focus-card"
      data-focus-index={item.index}
      className="wb-ctx-focus-card"
    >
      <div className="wb-ctx-focus-head">
        <span className="wb-ctx-focus-badge">🎯 Focus #{item.index}</span>
        {item.kindLabel ? (
          <span className="wb-ctx-focus-kind">{item.kindLabel}</span>
        ) : null}
        <span className="wb-ctx-focus-title" title={item.title}>
          {item.title}
        </span>
        {item.domain ? (
          item.safeUrl ? (
            <a
              href={item.safeUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="wb-ctx-domain-link"
              title={item.url}
            >
              <span>{item.domain}</span>
              <ExternalLink size={11} />
            </a>
          ) : (
            <span className="wb-ctx-domain-text" title={item.url}>
              {item.domain}
            </span>
          )
        ) : null}
      </div>
      {item.body ? (
        <div className="wb-ctx-focus-quote">
          <MarkdownContent content={item.body} className="wb-ctx-prose" />
        </div>
      ) : null}
    </div>
  );
}

function PageContextCard({ page }: { page: WebBridgePageContext }) {
  const [open, setOpen] = useState(false);
  const segments = open ? splitFocusAnchorSegments(page.markdown) : [];
  const summaryLabel = page.domain ? `${page.title} (${page.domain})` : page.title;

  return (
    <div
      data-testid="web-bridge-page-card"
      data-page-index={page.pageIndex}
      className="wb-ctx-page-card"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid="web-bridge-page-toggle"
        className="wb-ctx-page-capsule"
      >
        <span className="wb-ctx-page-lead">
          <span aria-hidden="true" className="shrink-0">
            📄
          </span>
          <span className="wb-ctx-page-kicker">网页完整可见上下文</span>
          <span className="wb-ctx-sep" aria-hidden="true">
            ·
          </span>
          <span className="wb-ctx-page-title" title={summaryLabel}>
            {summaryLabel}
          </span>
          <span className="wb-ctx-sep" aria-hidden="true">
            ·
          </span>
          <span className="wb-ctx-page-count">
            约 {page.charCount.toLocaleString()} 字
          </span>
          {page.focusNumbers.length > 0 ? (
            <span className="wb-ctx-anchor-chip" data-testid="web-bridge-page-anchor-chip">
              含 {page.focusNumbers.length} 处 Focus 锚点
            </span>
          ) : null}
        </span>
        <span className="wb-ctx-page-action">
          <span>{open ? '收起全文' : '点击展开全文'}</span>
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </span>
      </button>

      {open ? (
        <div data-testid="web-bridge-page-body" className="wb-ctx-page-body">
          {page.url || page.offloadedAttachmentName ? (
            <div className="wb-ctx-page-meta-bar">
              {page.safeUrl ? (
                <a
                  href={page.safeUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="wb-ctx-meta-url"
                  title={page.url}
                >
                  <span className="truncate">{page.url}</span>
                  <ExternalLink size={11} className="shrink-0" />
                </a>
              ) : page.url ? (
                <span className="truncate text-text-muted">{page.url}</span>
              ) : null}
              {page.offloadedAttachmentName ? (
                <span className="wb-ctx-offload-chip">
                  <Paperclip size={11} />
                  <span className="font-mono">{page.offloadedAttachmentName}</span>
                </span>
              ) : null}
            </div>
          ) : null}
          <div className="wb-ctx-page-scroll">
            {segments.map((seg, idx) =>
              seg.type === 'focus' ? (
                <div
                  key={`anchor-${seg.focusNumber}-${idx}`}
                  data-testid="web-bridge-anchor-highlight"
                  data-focus-anchor={seg.focusNumber}
                  className="wb-ctx-anchor-hit"
                >
                  <div className="wb-ctx-anchor-hit-badge">
                    🎯 Focus #{seg.focusNumber}
                  </div>
                  <MarkdownContent content={seg.content} className="wb-ctx-prose" />
                </div>
              ) : (
                <MarkdownContent
                  key={`md-${idx}`}
                  content={seg.content}
                  className="wb-ctx-prose"
                />
              )
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function WebBridgeContextView({
  parsed,
}: {
  parsed: ParsedWebBridgeContext;
}) {
  if (!parsed.hasBridgeContext) return null;

  return (
    <div data-testid="web-bridge-context" className="wb-ctx-stack">
      {parsed.focusItems.length > 0 ? (
        <div data-testid="web-bridge-focus-list" className="wb-ctx-focus-list">
          {parsed.focusItems.map((item) => (
            <FocusQuoteCard key={`focus-${item.index}`} item={item} />
          ))}
        </div>
      ) : null}

      {parsed.pages.length > 0 ? (
        <div data-testid="web-bridge-page-list" className="wb-ctx-page-list">
          {parsed.pages.map((page) => (
            <PageContextCard key={`page-${page.pageIndex}`} page={page} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
