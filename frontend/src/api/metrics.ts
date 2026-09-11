export type Engine = 'pipeline' | 'pptmaster';
export interface MetricSummary {
  count: number; success_rate: number | null; retries: number; fallbacks: number;
  input_tokens: number | null; output_tokens: number | null; cost_usd: number | null;
  unknown_usage_count: number; unknown_cost_count: number; estimated_cost_count: number; partial_usage_count: number;
  avg_duration_ms: number | null; p50_ms?: number | null; p95_ms?: number | null;
}
export interface SummaryData {
  source: string; engine: Engine; summary: MetricSummary;
  by_model: (MetricSummary & { model: string })[];
  daily: (MetricSummary & { date: string })[];
  by_stage: (MetricSummary & { stage: string })[];
  langfuse_enabled: boolean;
}
export interface Observation {
  id: string; trace_id: string; trace_url: string | null; biz_id: string | null;
  engine: Engine; kind: string; model: string; provider: string; stage: string;
  status: string; error_type: string | null; input_tokens: number | null;
  output_tokens: number | null; cost_usd: number | null; cost_source: string;
  duration_ms: number; queue_ms: number; attempt: number; fallback: boolean; created_at: string; usage_source: string;
}
export interface ObservationPage { items: Observation[]; total: number; page: number; page_size: number }
export interface RemoteData { status: string; message?: string; data?: Record<string, unknown>[]; cached?: boolean }

export function metricText(value: number | null | undefined, digits = 0): string {
  return value == null ? '未知' : value.toLocaleString('zh-CN', { maximumFractionDigits: digits });
}

export async function metricsFetch<T>(path: string, token: string,
  params: Record<string, string | number> = {}, signal?: AbortSignal): Promise<T> {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '').map(([k, v]) => [k, String(v)]));
  const response = await fetch(`/api/v1/metrics/${path}?${query}`, {
    headers: { Authorization: `Bearer ${token}` }, signal,
  });
  if (response.status === 401) throw new Error('访问令牌无效，请重新输入。');
  if (response.status === 503) throw new Error('指标访问尚未开启，请配置服务端 METRICS_ACCESS_TOKEN。');
  if (!response.ok) throw new Error(`指标读取失败（${response.status}），请稍后重试。`);
  const body = await response.json();
  if (body.code !== 0) throw new Error(body.message || '指标读取失败');
  return body.data as T;
}

// 只在当前浏览器页面内存保存；不写入 URL、localStorage 或构建配置。
let accessToken = '';
const listeners = new Set<() => void>();
export const readMetricsToken = () => accessToken;
export function setMetricsToken(value: string) {
  accessToken = value;
  listeners.forEach(fn => fn());
}
export function subscribeMetricsToken(fn: () => void) {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
