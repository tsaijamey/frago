/**
 * GuidePage Component
 *
 * Displays tutorial and FAQ content for frago Web UI.
 * Features: chapter navigation, FAQ index, markdown rendering.
 */

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import { getGuideMeta, getGuideContent, searchGuide, type GuideMeta, type GuideContent, type GuideSearchResult } from '@/api';
import { BookOpen, ChevronRight, Search, X } from 'lucide-react';

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

  // Extract FAQ questions from content for index
  const extractQuestions = (markdown: string): string[] => {
    const lines = markdown.split('\n');
    const questions: string[] = [];

    for (const line of lines) {
      // Match lines starting with Q: or **Q:**
      const match = line.match(/^\*\*Q:\s*(.+?)\*\*$/) || line.match(/^Q:\s*(.+)$/);
      if (match) {
        questions.push(match[1]);
      }
    }

    return questions;
  };

  // Get category name translation
  const getCategoryName = (categoryId: string): string => {
    const category = meta?.categories.find((cat) => cat.id === categoryId);
    if (category) {
      return currentLang === 'zh-CN'
        ? category.title['zh-CN']
        : category.title.en;
    }
    return categoryId;
  };

  // Get chapter title translation
  const getChapterTitle = (chapterId: string): string => {
    const titleMap: Record<string, { en: string; zh: string }> = {
      'getting-started': { en: 'Getting Started', zh: '开始使用' },
      'interface': { en: 'Interface FAQ', zh: '界面功能FAQ' },
      'config': { en: 'Configuration', zh: '配置相关' },
      'usage': { en: 'Usage Tips', zh: '使用技巧' },
      'troubleshooting': { en: 'Troubleshooting', zh: '故障排查' },
    };

    return currentLang === 'zh-CN'
      ? titleMap[chapterId]?.zh || chapterId
      : titleMap[chapterId]?.en || chapterId;
  };

  if (error && !meta) {
    return (
      <div className="page-scroll flex items-center justify-center">
        <div className="text-center">
          <BookOpen size={48} className="mx-auto mb-4 text-[var(--text-secondary)]" />
          <p className="text-[var(--text-secondary)]">{error}</p>
          <p className="text-sm text-[var(--text-tertiary)] mt-2">
            {t('guide.errorHint', 'Please check guide_source/ directory exists')}
          </p>
        </div>
      </div>
    );
  }

  if (!meta) {
    return (
      <div className="page-scroll flex items-center justify-center">
        <div className="spinner" />
      </div>
    );
  }

  const questions = content ? extractQuestions(content.content) : [];

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left Sidebar - Chapter Navigation */}
      <aside className="w-64 border-r border-[var(--border-color)] overflow-y-auto bg-[var(--bg-secondary)]">
        <div className="p-4">
          <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-4 flex items-center gap-2">
            <BookOpen size={20} />
            {t('guide.title', 'Guide')}
          </h2>

          {/* Search Box */}
          <div className="mb-4 relative">
            <div className="relative">
              <Search size={16} className="absolute left-3 top-1/2 transform -translate-y-1/2 text-[var(--text-tertiary)]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={currentLang === 'zh-CN' ? '搜索问题...' : 'Search questions...'}
                aria-label={currentLang === 'zh-CN' ? '搜索问题' : 'Search questions'}
                className="w-full pl-9 pr-8 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)] text-[var(--text-primary)] placeholder-[var(--text-tertiary)] focus:outline-none focus:border-[var(--accent-primary)] text-sm"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 transform -translate-y-1/2 text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
                >
                  <X size={16} />
                </button>
              )}
            </div>

            {/* Search Results Dropdown */}
            {searchQuery && (
              <div className="absolute top-full left-0 right-0 mt-2 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg shadow-lg max-h-96 overflow-y-auto z-10">
                {isSearching ? (
                  <div className="p-4 text-center text-[var(--text-secondary)]">
                    {currentLang === 'zh-CN' ? '搜索中...' : 'Searching...'}
                  </div>
                ) : searchResults.length > 0 ? (
                  <div className="py-2">
                    {searchResults.map((result, resultIndex) => (
                      <div key={resultIndex}>
                        <div className="px-3 py-1 text-xs font-semibold text-[var(--text-tertiary)] uppercase">
                          {getChapterTitle(result.chapter_id)}
                        </div>
                        {result.matches.map((match, matchIndex) => (
                          <button
                            type="button"
                            key={`${resultIndex}-${matchIndex}`}
                            onClick={() => {
                              setSelectedChapter(result.chapter_id);
                              setSearchQuery('');
                            }}
                            className="w-full text-left px-3 py-2 hover:bg-[var(--bg-tertiary)] transition-colors"
                          >
                            <div className="text-sm font-medium text-[var(--text-primary)] mb-1">
                              {match.question}
                            </div>
                            <div
                              className="text-xs text-[var(--text-secondary)] line-clamp-2"
                              dangerouslySetInnerHTML={{ __html: match.snippet }}
                            />
                          </button>
                        ))}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="p-4 text-center text-[var(--text-secondary)]">
                    {currentLang === 'zh-CN' ? '未找到相关内容' : 'No results found'}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Chapters by category */}
          {meta.categories.map((category) => {
            const categoryChapters = meta.chapters.filter(
              (ch) => ch.category === category.id
            );

            if (categoryChapters.length === 0) return null;

            return (
              <div key={category.id} className="mb-4">
                <h3 className="text-xs uppercase font-semibold text-[var(--text-tertiary)] mb-2 px-2">
                  {getCategoryName(category.id)}
                </h3>
                <div className="space-y-1">
                  {categoryChapters.map((chapter) => (
                    <button
                      type="button"
                      key={chapter.id}
                      onClick={() => setSelectedChapter(chapter.id)}
                      className={`w-full text-left px-3 py-2 rounded-lg transition-colors ${
                        selectedChapter === chapter.id
                          ? 'bg-[var(--accent-primary)] text-[var(--text-on-accent)]'
                          : 'text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm">
                          {getChapterTitle(chapter.id)}
                        </span>
                        {chapter.question_count > 0 && (
                          <span className="text-xs opacity-70">
                            {chapter.question_count}
                          </span>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <div className="spinner" />
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <p className="text-[var(--text-secondary)]">{error}</p>
            </div>
          </div>
        ) : !content ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <BookOpen size={48} className="mx-auto mb-4 text-[var(--text-secondary)]" />
              <p className="text-[var(--text-secondary)]">
                {t('guide.noContent', 'No guide content available')}
              </p>
            </div>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto p-6">
            {/* Header */}
            <div className="mb-6">
              <h1 className="text-3xl font-bold text-[var(--text-primary)] mb-2">
                {content.title}
              </h1>
              <p className="text-sm text-[var(--text-secondary)]">
                {currentLang === 'zh-CN' ? '版本' : 'Version'}: {content.metadata.version} | {currentLang === 'zh-CN' ? '更新时间' : 'Last updated'}: {content.metadata.last_updated}
              </p>
            </div>

            {/* FAQ Index */}
            {questions.length > 0 && (
              <div className="mb-8 p-4 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-color)]">
                <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-3">
                  {currentLang === 'zh-CN' ? '本章问题' : 'Questions in this chapter'}
                </h2>
                <ul className="space-y-2">
                  {questions.map((question, index) => (
                    <li key={index}>
                      <a
                        href={`#q-${index}`}
                        className="flex items-start gap-2 text-[var(--text-secondary)] hover:text-[var(--accent-primary)] transition-colors"
                      >
                        <ChevronRight size={16} className="mt-1 flex-shrink-0" />
                        <span className="text-sm">{question}</span>
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Content */}
            <div className="guide-content prose prose-invert max-w-none">
              <ReactMarkdown
                components={{
                  // Custom heading renderer with anchors for FAQ questions
                  h2({ children }) {
                    const text = String(children);
                    const isQuestion = text.startsWith('Q:');
                    const questionIndex = isQuestion ? questions.findIndex((q) => text.includes(q)) : -1;

                    return (
                      <h2
                        id={questionIndex >= 0 ? `q-${questionIndex}` : undefined}
                        className="text-2xl font-semibold mt-8 mb-4 text-[var(--text-primary)] border-b border-[var(--border-color)] pb-2"
                      >
                        {children}
                      </h2>
                    );
                  },
                  h3({ children }) {
                    return (
                      <h3 className="text-xl font-semibold mt-6 mb-3 text-[var(--text-primary)]">
                        {children}
                      </h3>
                    );
                  },
                  // Style paragraphs
                  p({ children }) {
                    return (
                      <p className="text-[var(--text-primary)] leading-relaxed mb-4">
                        {children}
                      </p>
                    );
                  },
                  // Style lists
                  ul({ children }) {
                    return (
                      <ul className="list-disc pl-6 mb-4 text-[var(--text-primary)] space-y-2">
                        {children}
                      </ul>
                    );
                  },
                  ol({ children }) {
                    return (
                      <ol className="list-decimal pl-6 mb-4 text-[var(--text-primary)] space-y-2">
                        {children}
                      </ol>
                    );
                  },
                  // Style links
                  a({ href, children }) {
                    return (
                      <a
                        href={href}
                        className="text-[var(--accent-primary)] hover:underline"
                        target={href?.startsWith('http') ? '_blank' : undefined}
                        rel={href?.startsWith('http') ? 'noopener noreferrer' : undefined}
                      >
                        {children}
                      </a>
                    );
                  },
                  // Style code blocks (pre > code)
                  pre({ children }) {
                    return (
                      <pre className="bg-[var(--bg-tertiary)] p-4 rounded-lg overflow-x-auto mb-4">
                        {children}
                      </pre>
                    );
                  },
                  // Style inline code
                  code({ className, children, ...props }) {
                    // If className contains 'language-', it's a code block (handled by pre)
                    const isCodeBlock = className?.includes('language-');
                    if (isCodeBlock) {
                      return (
                        <code className={className} {...props}>
                          {children}
                        </code>
                      );
                    }
                    // Inline code
                    return (
                      <code
                        className="px-1.5 py-0.5 rounded bg-[var(--bg-tertiary)] text-[var(--accent-primary)] font-mono text-sm"
                        {...props}
                      >
                        {children}
                      </code>
                    );
                  },
                  // Style blockquotes
                  blockquote({ children }) {
                    return (
                      <blockquote className="border-l-4 border-[var(--accent-primary)] pl-4 italic text-[var(--text-secondary)] my-4">
                        {children}
                      </blockquote>
                    );
                  },
                  // Style tables
                  table({ children }) {
                    return (
                      <div className="overflow-x-auto mb-4">
                        <table className="min-w-full border border-[var(--border-color)]">
                          {children}
                        </table>
                      </div>
                    );
                  },
                  th({ children }) {
                    return (
                      <th className="border border-[var(--border-color)] bg-[var(--bg-secondary)] px-4 py-2 text-left font-semibold text-[var(--text-primary)]">
                        {children}
                      </th>
                    );
                  },
                  td({ children }) {
                    return (
                      <td className="border border-[var(--border-color)] px-4 py-2 text-[var(--text-primary)]">
                        {children}
                      </td>
                    );
                  },
                }}
              >
                {content.content}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
