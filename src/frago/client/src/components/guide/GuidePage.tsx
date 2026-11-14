/**
 * GuidePage Component
 *
 * Displays tutorial and FAQ content for frago Web UI.
 *
 * 这一页从前是全站最离群的一页：内容区顶着一个 30px 粗黑体大标题、正文里
 * 蓝色下划线链接、`Q:` / `A:` 前缀加全宽分隔线，看起来像嵌进来的第三方文档站。
 * 左栏还直接露出 `interface-faq` 这种小写连字符 key。现在它按全站同一套语言重做：
 * 页头走 C1 契约、左栏章节名取 meta.json 里的本地化名、每组问答是一张可折叠的
 * Double-Bezel 阅读卡、提示语用 Lucide 灯泡图标而不是原生 emoji。
 */

import { useMemo, useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import { getGuideMeta, getGuideContent, searchGuide, type GuideMeta, type GuideContent, type GuideSearchResult } from '@/api';
import { BookOpen, ChevronDown, ChevronRight, Lightbulb, Search, X } from 'lucide-react';
import EmptyState from '@/components/ui/EmptyState';

/** 一段内容：要么是普通 Markdown，要么是一条提示语。 */
type Segment =
  | { kind: 'md'; text: string }
  | { kind: 'tip'; text: string };

/** 一组问答。 */
interface FaqSection {
  question: string;
  body: string;
}

/**
 * 把小写连字符 id 变成可读标题（`interface-faq` → `Interface FAQ`）。
 *
 * 只在章节拿不到本地化名时兜底。此前左栏直接把 id 印出来，`interface-faq`
 * 就这么裸露在导航里——那是数据库字段，不是给人读的标题。
 */
function prettifyId(id: string): string {
  return id
    .split('-')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * 把一章的 Markdown 拆成若干组问答。
 *
 * 章首（第一个 `## Q:` 之前）的内容单独返回，它讲的是这一章在说什么，
 * 不属于任何一组问答。
 */
function splitFaq(markdown: string): { intro: string; sections: FaqSection[] } {
  const lines = markdown.split('\n');
  const introLines: string[] = [];
  const sections: FaqSection[] = [];
  let current: FaqSection | null = null;

  for (const line of lines) {
    // 一级标题（`# 开始使用`）与页头重复，不进正文。
    if (/^#\s+/.test(line)) continue;

    const questionMatch = line.match(/^##\s+Q:\s*(.+?)\s*$/);
    if (questionMatch) {
      if (current) sections.push(current);
      current = { question: questionMatch[1], body: '' };
      continue;
    }

    if (current) {
      current.body += `${line}\n`;
    } else {
      introLines.push(line);
    }
  }
  if (current) sections.push(current);

  return { intro: introLines.join('\n').trim(), sections };
}

/**
 * 把一段正文切成「普通 Markdown」与「提示语」交替的片段。
 *
 * 提示语在原文里写成 `**💡 提示**: …`，那个 emoji 是原生字符，字形随系统字体变，
 * 在浅色主题下还发黄。这里把它摘出来单独用灯泡图标画，正文里不再出现 emoji。
 */
function splitTips(markdown: string): Segment[] {
  const segments: Segment[] = [];
  let buffer: string[] = [];

  const flush = () => {
    const text = buffer.join('\n').trim();
    if (text) segments.push({ kind: 'md', text });
    buffer = [];
  };

  for (const line of markdown.split('\n')) {
    const tipMatch = line.match(/^\*\*\s*(?:💡\s*)?(?:提示|Tip)\s*\*\*\s*[:：]\s*(.*)$/i);
    if (tipMatch) {
      flush();
      segments.push({ kind: 'tip', text: tipMatch[1].trim() });
    } else {
      buffer.push(line);
    }
  }
  flush();

  return segments;
}

/** 正文 Markdown 的统一渲染口径。 */
function MarkdownBlock({ children }: { children: string }) {
  return (
    <div className="gd-prose">
      <ReactMarkdown
        components={{
          p({ children: kids }) {
            return <p className="gd-p">{kids}</p>;
          },
          ul({ children: kids }) {
            return <ul className="gd-ul">{kids}</ul>;
          },
          ol({ children: kids }) {
            return <ol className="gd-ol">{kids}</ol>;
          },
          li({ children: kids }) {
            return <li className="gd-li">{kids}</li>;
          },
          strong({ children: kids }) {
            return <strong className="gd-strong">{kids}</strong>;
          },
          a({ href, children: kids }) {
            return (
              <a
                href={href}
                className="gd-link"
                target={href?.startsWith('http') ? '_blank' : undefined}
                rel={href?.startsWith('http') ? 'noopener noreferrer' : undefined}
              >
                {kids}
              </a>
            );
          },
          pre({ children: kids }) {
            return <pre className="gd-pre">{kids}</pre>;
          },
          code({ className, children: kids, ...props }) {
            const isCodeBlock = className?.includes('language-');
            if (isCodeBlock) {
              return (
                <code className={className} {...props}>
                  {kids}
                </code>
              );
            }
            return (
              <code className="gd-code" {...props}>
                {kids}
              </code>
            );
          },
          // 引用块：中性微底色块 + 全周发丝边框。品牌绿只留给动作与活跃状态，
          // 不用左单边竖线做强调。
          blockquote({ children: kids }) {
            return <blockquote className="gd-quote">{kids}</blockquote>;
          },
          table({ children: kids }) {
            return (
              <div className="gd-table-wrap">
                <table className="gd-table">{kids}</table>
              </div>
            );
          },
          th({ children: kids }) {
            return <th className="gd-th">{kids}</th>;
          },
          td({ children: kids }) {
            return <td className="gd-td">{kids}</td>;
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

/** 一组正文片段：普通段落照常渲染，提示语画成柔和提示框。 */
function Segments({ segments }: { segments: Segment[] }) {
  return (
    <>
      {segments.map((segment, index) =>
        segment.kind === 'tip' ? (
          <div className="gd-tip" key={index}>
            <span className="gd-tip-icon">
              <Lightbulb size={15} strokeWidth={1.75} />
            </span>
            <span className="gd-tip-text">{segment.text}</span>
          </div>
        ) : (
          <MarkdownBlock key={index}>{segment.text}</MarkdownBlock>
        )
      )}
    </>
  );
}

/** 一组可折叠问答。 */
function FaqCard({ section, defaultOpen }: { section: FaqSection; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const segments = useMemo(() => splitTips(section.body), [section.body]);

  return (
    <section className="gd-faq ui-bezel-card">
      <button
        type="button"
        className="gd-faq-head"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span className="gd-faq-chevron">
          {open ? <ChevronDown size={15} strokeWidth={1.75} /> : <ChevronRight size={15} strokeWidth={1.75} />}
        </span>
        <span className="gd-faq-question">{section.question}</span>
      </button>
      {open && (
        <div className="gd-faq-body">
          <Segments segments={segments} />
        </div>
      )}
    </section>
  );
}

export default function GuidePage() {
  const { t, i18n } = useTranslation();
  const [meta, setMeta] = useState<GuideMeta | null>(null);
  const [content, setContent] = useState<GuideContent | null>(null);
  const [selectedChapter, setSelectedChapter] = useState<string>('getting-started');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Search state
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchResults, setSearchResults] = useState<GuideSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  // Get current language from i18n
  const currentLang = i18n.language === 'zh' ? 'zh-CN' : 'en';

  // Load meta on mount and language change
  useEffect(() => {
    const loadMeta = async () => {
      try {
        const guideMeta = await getGuideMeta(currentLang);
        setMeta(guideMeta);
      } catch (err) {
        console.error('Failed to load guide meta:', err);
        setError(err instanceof Error ? err.message : 'Failed to load guide');
      }
    };

    loadMeta();
  }, [currentLang]);

  // Load chapter content when chapter changes
  useEffect(() => {
    const loadChapter = async () => {
      if (!meta) return;

      try {
        setLoading(true);
        setError(null);

        const chapterContent = await getGuideContent(currentLang, selectedChapter);
        if (chapterContent) {
          setContent(chapterContent);
        }
      } catch (err) {
        console.error('Failed to load chapter content:', err);
        setError(err instanceof Error ? err.message : 'Failed to load chapter');
      } finally {
        setLoading(false);
      }
    };

    loadChapter();
  }, [currentLang, selectedChapter, meta]);

  // Handle search with debounce
  useEffect(() => {
    const performSearch = async () => {
      if (!searchQuery.trim()) {
        setSearchResults([]);
        setIsSearching(false);
        return;
      }

      setIsSearching(true);
      try {
        const response = await searchGuide(searchQuery, currentLang);
        setSearchResults(response.results);
      } catch (err) {
        console.error('Search failed:', err);
        setSearchResults([]);
      } finally {
        setIsSearching(false);
      }
    };

    const timeoutId = setTimeout(performSearch, 300);
    return () => clearTimeout(timeoutId);
  }, [searchQuery, currentLang]);

  /**
   * 章节的显示名。
   *
   * 取 meta.json 里分类的本地化标题——那本来就是人写的名字（「界面功能FAQ」）。
   * 此前代码里写了一张硬编码映射表，键写成 `interface`，而 meta.json 里章节 id 是
   * `interface-faq`，查不到就退回 id 本身，于是左栏直接印出 `interface-faq`。
   * 一个分类下有多章时（当前没有）才退回把 id 变可读标题。
   */
  const getChapterLabel = (chapterId: string): string => {
    const chapter = meta?.chapters.find((ch) => ch.id === chapterId);
    const category = chapter && meta?.categories.find((cat) => cat.id === chapter.category);
    if (category) {
      const siblings = meta!.chapters.filter((ch) => ch.category === category.id);
      if (siblings.length === 1) {
        return currentLang === 'zh-CN' ? category.title['zh-CN'] : category.title.en;
      }
    }
    return prettifyId(chapterId);
  };

  const getCategoryName = (categoryId: string): string => {
    const category = meta?.categories.find((cat) => cat.id === categoryId);
    if (category) {
      return currentLang === 'zh-CN'
        ? category.title['zh-CN']
        : category.title.en;
    }
    return prettifyId(categoryId);
  };

  const currentChapterLabel = meta ? getChapterLabel(selectedChapter) : '';

  const { intro, sections } = useMemo(
    () => (content ? splitFaq(content.content) : { intro: '', sections: [] }),
    [content]
  );

  // 整页只有这一条页头：标题、章节名、搜索。正文里不再出现第二个大标题。
  const header = (
    <header className="ui-page-header">
      <div className="ui-page-header-titles">
        <h1 className="ui-page-header-title">{t('guide.title', 'Guide')}</h1>
        {currentChapterLabel && <span className="ui-page-header-meta">{currentChapterLabel}</span>}
      </div>
      <div className="ui-page-header-actions">
        <div className="ui-search-box gd-search">
          <Search size={16} strokeWidth={1.75} className="ui-search-box-icon" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={currentLang === 'zh-CN' ? '搜索问题…' : 'Search questions…'}
            aria-label={currentLang === 'zh-CN' ? '搜索问题' : 'Search questions'}
          />
          {searchQuery && (
            <button
              type="button"
              className="ui-search-box-clear"
              onClick={() => setSearchQuery('')}
              aria-label={t('common.clear', 'Clear')}
            >
              <X size={14} strokeWidth={1.75} />
            </button>
          )}
        </div>
      </div>
    </header>
  );

  if (error && !meta) {
    return (
      <div className="gd-page">
        {header}
        <div className="gd-state">
          <EmptyState
            Icon={BookOpen}
            title={error}
            description={t('guide.errorHint', 'Please check guide_source/ directory exists')}
          />
        </div>
      </div>
    );
  }

  if (!meta) {
    return (
      <div className="gd-page">
        {header}
        <div className="gd-state">
          <div className="spinner" />
        </div>
      </div>
    );
  }

  return (
    <div className="gd-page">
      {header}

      <div className="gd-split">
        {/* 左栏：章节导航。条目与选中态走全站同一套微边框语言。 */}
        <aside className="gd-nav">
          <div className="gd-nav-inner">
            {meta.categories.map((category) => {
              const categoryChapters = meta.chapters.filter((ch) => ch.category === category.id);
              if (categoryChapters.length === 0) return null;

              return (
                <div className="gd-nav-group" key={category.id}>
                  <div className="gd-nav-group-title">{getCategoryName(category.id)}</div>
                  {categoryChapters.map((chapter) => {
                    const isActive = selectedChapter === chapter.id;
                    return (
                      <button
                        type="button"
                        key={chapter.id}
                        onClick={() => setSelectedChapter(chapter.id)}
                        className={`gd-nav-item ${isActive ? 'is-active' : ''}`}
                        aria-current={isActive ? 'page' : undefined}
                      >
                        <span className="gd-nav-item-label">{getChapterLabel(chapter.id)}</span>
                        {chapter.question_count > 0 && (
                          <span className="gd-nav-count">{chapter.question_count}</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </aside>

        {/* 右栏：这一章的问答。 */}
        <main className="gd-main">
          <div className="gd-main-inner">
            {/* 搜索结果：盖在正文之上的浮层，选中一条就跳去那一章。 */}
            {searchQuery && (
              <div className="gd-results ui-bezel-card">
                {isSearching ? (
                  <div className="gd-results-note">
                    {currentLang === 'zh-CN' ? '搜索中…' : 'Searching…'}
                  </div>
                ) : searchResults.length > 0 ? (
                  searchResults.map((result, resultIndex) => (
                    <div key={resultIndex} className="gd-results-group">
                      <div className="gd-results-chapter">{getChapterLabel(result.chapter_id)}</div>
                      {result.matches.map((match, matchIndex) => (
                        <button
                          type="button"
                          key={`${resultIndex}-${matchIndex}`}
                          onClick={() => {
                            setSelectedChapter(result.chapter_id);
                            setSearchQuery('');
                          }}
                          className="gd-result-item"
                        >
                          <div className="gd-result-question">{match.question}</div>
                          <div
                            className="gd-result-snippet"
                            dangerouslySetInnerHTML={{ __html: match.snippet }}
                          />
                        </button>
                      ))}
                    </div>
                  ))
                ) : (
                  <div className="gd-results-note">
                    {currentLang === 'zh-CN' ? '未找到相关内容' : 'No results found'}
                  </div>
                )}
              </div>
            )}

            {loading ? (
              <div className="gd-state">
                <div className="spinner" />
              </div>
            ) : error ? (
              <div className="gd-state">
                <EmptyState Icon={BookOpen} title={error} />
              </div>
            ) : !content ? (
              <div className="gd-state">
                <EmptyState Icon={BookOpen} title={t('guide.noContent', 'No guide content available')} />
              </div>
            ) : (
              <>
                {intro && (
                  <div className="gd-intro">
                    <MarkdownBlock>{intro}</MarkdownBlock>
                  </div>
                )}

                {sections.length > 0 && (
                  <div className="gd-faq-list">
                    {sections.map((section, index) => (
                      <FaqCard
                        key={`${selectedChapter}-${index}`}
                        section={section}
                        defaultOpen={index === 0}
                      />
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
