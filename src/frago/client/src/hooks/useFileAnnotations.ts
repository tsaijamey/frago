/**
 * useFileAnnotations — 会话文件预览（FileViewer）的文档批注状态与落盘同步。
 *
 * 与 `useSessionMarks` 同构：
 * 1. 新增、删除批注当场更新界面，随后整份排队写入 `~/.frago/sessions/<family>/<sid>/file-annotations.json`。
 * 2. 写入失败退回最后一份确认落盘的数据，并弹一次报错。
 * 3. 提供 `formatPackedAnnotationsPrompt` 将当前会话全部批注按溯源路径打包成一条完整的新 prompt，
 *    直接填入底部对话框（Composer）供用户检查后按 Send 发送。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import i18n from '@/i18n';
import { getSessionFileAnnotations, putSessionFileAnnotations } from '@/api';
import type { FileAnnotation } from '@/types/api';
import { useUIStore } from '@/stores/uiStore';
import { withTilde } from '@/components/sessionWorkbench/filePaths';

export type { FileAnnotation } from '@/types/api';

export interface NewFileAnnotation {
  file: string;
  line_start: number;
  line_end: number;
  quote: string;
  note: string;
}

export interface FileAnnotationsState {
  annotations: FileAnnotation[];
  tracePath: string;
  loaded: boolean;
  addAnnotation: (input: NewFileAnnotation) => FileAnnotation | null;
  removeAnnotation: (id: string) => void;
  clearAnnotations: () => void;
}

export function newAnnotationId(): string {
  const rand =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID().replace(/-/g, '').slice(0, 12)
      : Math.random().toString(36).slice(2, 14);
  return `ann_${rand}`;
}

/**
 * 把全部文档批注打包成一段完整的新 prompt（带会话关联存档路径与逐项文件行号引用）。
 */
export function formatPackedAnnotationsPrompt(
  annotations: FileAnnotation[],
  tracePath: string
): string {
  if (!annotations.length) return '';
  const header = i18n.t('workbench.files.packedHeader', {
    path: tracePath,
    defaultValue: `【文档批注汇总】（已关联存档：${tracePath}）`,
  });
  const items = annotations.map((ann, idx) => {
    const loc =
      ann.line_start === ann.line_end
        ? `L${ann.line_start}`
        : `L${ann.line_start}-L${ann.line_end}`;
    return `${idx + 1}. \`${withTilde(ann.file)}:${loc}\`\n"""\n${ann.quote}\n"""\n>>> ${ann.note}`;
  });
  const footer = i18n.t('workbench.files.packedFooter', {
    defaultValue: '请按以上批注逐项处理。',
  });
  return `${header}\n\n${items.join('\n\n')}\n\n${footer}`;
}

export function useFileAnnotations(sessionId: string | null): FileAnnotationsState {
  const [annotations, setAnnotations] = useState<FileAnnotation[]>([]);
  const [tracePath, setTracePath] = useState<string>('');
  const [loaded, setLoaded] = useState(false);

  const current = useRef<FileAnnotation[]>([]);
  const confirmed = useRef<FileAnnotation[]>([]);
  const sidRef = useRef<string | null>(sessionId);
  const inFlight = useRef(false);
  const dirty = useRef(false);
  const warned = useRef(false);
  const readState = useRef<'pending' | 'ok' | 'failed'>('pending');
  const flushRef = useRef<() => Promise<void>>(async () => {});

  const apply = useCallback((next: FileAnnotation[]) => {
    current.current = next;
    setAnnotations(next);
  }, []);

  useEffect(() => {
    sidRef.current = sessionId;
    inFlight.current = false;
    dirty.current = false;
    warned.current = false;
    readState.current = 'pending';
    confirmed.current = [];
    apply([]);
    setTracePath(sessionId ? `~/.frago/sessions/.../${sessionId}/file-annotations.json` : '');
    setLoaded(false);
    if (!sessionId || typeof getSessionFileAnnotations !== 'function') {
      readState.current = 'ok';
      setLoaded(true);
      return;
    }
    let alive = true;
    Promise.resolve(getSessionFileAnnotations(sessionId))
      .then((body) => {
        if (!alive || sidRef.current !== sessionId) return;
        const list = Array.isArray(body?.annotations) ? body.annotations : [];
        confirmed.current = list;
        readState.current = 'ok';
        if (body?.trace_path) setTracePath(body.trace_path);
        const known = new Set(list.map((a) => a.id));
        apply([...list, ...current.current.filter((a) => !known.has(a.id))]);
        setLoaded(true);
        if (dirty.current) void flushRef.current();
      })
      .catch(() => {
        if (!alive || sidRef.current !== sessionId) return;
        readState.current = 'failed';
        setLoaded(true);
        if (dirty.current) void flushRef.current();
      });
    return () => {
      alive = false;
    };
  }, [sessionId, apply]);

  const flush = useCallback(async () => {
    const sid = sidRef.current;
    if (!sid || inFlight.current || readState.current === 'pending') return;
    inFlight.current = true;
    dirty.current = false;
    const snapshot = current.current;
    try {
      if (readState.current === 'failed') {
        throw new Error(i18n.t('workbench.errors.marksNotLoaded'));
      }
      const saved =
        typeof putSessionFileAnnotations === 'function'
          ? await putSessionFileAnnotations(sid, {
              version: 1,
              annotations: snapshot,
            })
          : null;
      if (sidRef.current !== sid) return;
      confirmed.current = snapshot;
      if (saved?.trace_path) setTracePath(saved.trace_path);
      warned.current = false;
    } catch (e) {
      if (sidRef.current !== sid) return;
      dirty.current = false;
      apply(confirmed.current);
      if (!warned.current) {
        warned.current = true;
        useUIStore.getState().showToast(
          i18n.t('workbench.errors.marksSaveFailed', {
            reason: e instanceof Error ? e.message : String(e),
          }),
          'error'
        );
      }
    } finally {
      if (sidRef.current === sid) {
        inFlight.current = false;
        if (dirty.current) void flush();
      }
    }
  }, [apply]);
  flushRef.current = flush;

  const commit = useCallback(
    (next: FileAnnotation[]) => {
      if (!sidRef.current) return;
      apply(next);
      dirty.current = true;
      void flush();
    },
    [apply, flush]
  );

  const addAnnotation = useCallback(
    (input: NewFileAnnotation): FileAnnotation | null => {
      if (!sidRef.current) return null;
      const note = input.note.trim();
      if (!note) return null;
      const entry: FileAnnotation = {
        id: newAnnotationId(),
        file: input.file,
        line_start: input.line_start,
        line_end: input.line_end,
        quote: input.quote,
        note,
        created_at: Date.now(),
      };
      commit([...current.current, entry]);
      return entry;
    },
    [commit]
  );

  const removeAnnotation = useCallback(
    (id: string) => {
      const next = current.current.filter((a) => a.id !== id);
      if (next.length !== current.current.length) commit(next);
    },
    [commit]
  );

  const clearAnnotations = useCallback(() => {
    if (current.current.length > 0) commit([]);
  }, [commit]);

  return {
    annotations,
    tracePath,
    loaded,
    addAnnotation,
    removeAnnotation,
    clearAnnotations,
  };
}
