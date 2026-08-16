import { useEffect, useRef, useState } from 'react';
import { jobApi } from '../api/endpoints';
import type {
  DecisionRequiredEvent,
  JobDetail,
  JobDoneEvent,
  JobFailedEvent,
  PageDoneEvent,
  StageUpdateEvent,
  ThumbnailReadyEvent,
} from '../api/types';

/** SSE 事件回调集合 */
export interface JobEventHandlers {
  onStageUpdate?: (e: StageUpdateEvent) => void;
  onPageDone?: (e: PageDoneEvent) => void;
  onThumbnailReady?: (e: ThumbnailReadyEvent) => void;
  onDecisionRequired?: (e: DecisionRequiredEvent) => void;
  onJobDone?: (e: JobDoneEvent) => void;
  onJobFailed?: (e: JobFailedEvent) => void;
  /** 降级轮询模式下，每 3s 拉取一次任务详情后回调 */
  onPollDetail?: (detail: JobDetail) => void;
}

export type ConnectionMode = 'sse' | 'polling' | 'idle';

const MAX_SSE_FAILURES = 3; // SSE 连续断线阈值
const POLL_INTERVAL_MS = 3000; // 降级轮询间隔

/**
 * 任务进度事件 Hook：
 * 1. 优先使用 SSE（EventSource）订阅 /jobs/{id}/events；
 * 2. 按事件内 seq 去重（后端可能在重连后重发历史事件）；
 * 3. SSE 连续断线 3 次后，降级为 3s 轮询 GET /jobs/{id}（简化：不再切回 SSE）。
 */
export function useJobEvents(
  jobId: string | undefined,
  enabled: boolean,
  handlers: JobEventHandlers,
): ConnectionMode {
  const [mode, setMode] = useState<ConnectionMode>('idle');
  // handlers 放入 ref，避免因回调引用变化而反复重建连接
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    if (!jobId || !enabled) {
      setMode('idle');
      return;
    }

    let disposed = false;
    let es: EventSource | null = null;
    let pollTimer: number | null = null;
    let failureCount = 0;
    const seenSeq = new Set<number>(); // seq 去重集合

    /** 解析事件 JSON 并按 seq 去重后分发 */
    function dispatch<T extends { seq: number }>(
      raw: MessageEvent,
      handler: ((e: T) => void) | undefined,
    ) {
      try {
        const data = JSON.parse(raw.data as string) as T;
        if (typeof data.seq === 'number') {
          if (seenSeq.has(data.seq)) return; // 重复事件丢弃
          seenSeq.add(data.seq);
        }
        handler?.(data);
      } catch {
        // 忽略无法解析的事件
      }
    }

    /** 降级：3s 轮询任务详情 */
    function startPolling() {
      if (disposed || pollTimer !== null) return;
      setMode('polling');
      const poll = async () => {
        if (disposed) return;
        try {
          const detail = await jobApi.detail(jobId!);
          if (!disposed) handlersRef.current.onPollDetail?.(detail);
        } catch {
          // 轮询失败静默，下一轮继续
        }
      };
      void poll(); // 立即拉一次
      pollTimer = window.setInterval(poll, POLL_INTERVAL_MS);
    }

    /** 建立 SSE 连接 */
    function connect() {
      if (disposed) return;
      es = new EventSource(`/api/v1/jobs/${jobId}/events`);
      setMode('sse');

      es.onopen = () => {
        failureCount = 0; // 连接成功重置失败计数
      };

      es.addEventListener('stage_update', (e) =>
        dispatch<StageUpdateEvent>(e, handlersRef.current.onStageUpdate),
      );
      es.addEventListener('page_done', (e) =>
        dispatch<PageDoneEvent>(e, handlersRef.current.onPageDone),
      );
      es.addEventListener('thumbnail_ready', (e) =>
        dispatch<ThumbnailReadyEvent>(e, handlersRef.current.onThumbnailReady),
      );
      es.addEventListener('decision_required', (e) =>
        dispatch<DecisionRequiredEvent>(e, handlersRef.current.onDecisionRequired),
      );
      es.addEventListener('job_done', (e) =>
        dispatch<JobDoneEvent>(e, handlersRef.current.onJobDone),
      );
      es.addEventListener('job_failed', (e) =>
        dispatch<JobFailedEvent>(e, handlersRef.current.onJobFailed),
      );

      es.onerror = () => {
        // EventSource 会自动重连；这里统计连续失败次数
        failureCount += 1;
        if (failureCount >= MAX_SSE_FAILURES) {
          es?.close();
          es = null;
          startPolling();
        }
      };
    }

    connect();

    return () => {
      disposed = true;
      es?.close();
      if (pollTimer !== null) window.clearInterval(pollTimer);
    };
  }, [jobId, enabled]);

  return mode;
}
