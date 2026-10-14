/**
 * CryoAgent Pro — 全局前端状态
 */

import { create } from 'zustand';

export type ViewId =
  | 'dashboard'
  | 'qa'
  | 'literature'
  | 'literature-detail'
  | 'structures'
  | 'structure-detail'
  | 'kg'
  | 'alignment'
  | 'sequence-analyzer'
  | 'skills'
  | 'evaluation'
  | 'settings'
  | 'api-docs';

interface AppState {
  view: ViewId;
  viewParams: Record<string, string>;
  sidebarOpen: boolean;
  theme: 'light' | 'dark' | 'system';
  commandOpen: boolean;
  // 视图数据缓存键 (用于详情视图传参)
  navigate: (view: ViewId, params?: Record<string, string>) => void;
  setSidebarOpen: (open: boolean) => void;
  setCommandOpen: (open: boolean) => void;
  setTheme: (theme: 'light' | 'dark' | 'system') => void;
}

export const useAppStore = create<AppState>((set) => ({
  view: 'dashboard',
  viewParams: {},
  sidebarOpen: true,
  theme: 'system',
  commandOpen: false,
  navigate: (view, params = {}) => set({ view, viewParams: params }),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  setCommandOpen: (open) => set({ commandOpen: open }),
  setTheme: (theme) => set({ theme }),
}));

/** 轻量 fetch 封装 */
export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    ...init,
    headers: init?.body instanceof FormData ? init?.headers : { 'Content-Type': 'application/json', ...init?.headers },
  });
  const data = (await resp.json()) as T & { error?: string };
  if (!resp.ok) throw new Error(data?.error || `请求失败 (${resp.status})`);
  return data;
}

/** SSE 流式请求封装 (用于 QA) */
export async function streamSse(
  url: string,
  body: unknown,
  handlers: {
    onMeta?: (data: unknown) => void;
    onDelta?: (text: string) => void;
    onNotice?: (data: unknown) => void;
    onDone?: (data: unknown) => void;
    onError?: (message: string) => void;
  },
  signal?: AbortSignal
): Promise<void> {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) {
    let message = `请求失败 (${resp.status})`;
    try {
      const j = await resp.json();
      if (j.error) message = j.error;
    } catch {
      /* ignore */
    }
    handlers.onError?.(message);
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';
      for (const evt of events) {
        const lines = evt.split('\n');
        let eventName = '';
        let eventData = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) eventName = line.slice(7).trim();
          else if (line.startsWith('data: ')) eventData = line.slice(6);
        }
        if (!eventName || !eventData) continue;
        try {
          const parsed = JSON.parse(eventData);
          if (eventName === 'meta') handlers.onMeta?.(parsed);
          else if (eventName === 'delta') handlers.onDelta?.(parsed.text || '');
          else if (eventName === 'notice') handlers.onNotice?.(parsed);
          else if (eventName === 'done') handlers.onDone?.(parsed);
          else if (eventName === 'error') handlers.onError?.(parsed.message || 'AI 调用失败');
        } catch {
          /* ignore malformed */
        }
      }
    }
  } catch (err) {
    if ((err as Error).name !== 'AbortError') {
      handlers.onError?.(err instanceof Error ? err.message : '连接中断');
    }
  }
}
