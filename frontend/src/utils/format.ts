import dayjs from 'dayjs';
import type { Density, DocumentItem, JobMode } from '../api/types';

/** 毫秒 → 人类可读耗时，如 41s / 2m 10s / 1h 3m */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || ms < 0) return '-';
  const totalSec = Math.round(ms / 1000);
  if (totalSec < 60) {
    // 小于 10 秒保留一位小数，更精确
    return ms < 10_000 ? `${(ms / 1000).toFixed(1)}s` : `${totalSec}s`;
  }
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  if (min < 60) return sec > 0 ? `${min}m ${sec}s` : `${min}m`;
  const hour = Math.floor(min / 60);
  const remMin = min % 60;
  return remMin > 0 ? `${hour}h ${remMin}m` : `${hour}h`;
}

/** 时间戳格式化 */
export function formatTime(ts: string | null | undefined, fmt = 'YYYY-MM-DD HH:mm'): string {
  if (!ts) return '-';
  return dayjs(ts).format(fmt);
}

/** 时间戳格式化（含毫秒，阶段耗时抽屉用） */
export function formatTimeMs(ts: string | null | undefined): string {
  if (!ts) return '-';
  return dayjs(ts).format('HH:mm:ss.SSS').slice(0, -2); // 保留 1 位毫秒
}

/**
 * 预计耗时估算（§14 公式）：
 * est = base(mode) + pages × per_page(mode) × (density==high ? 1.2 : 1)
 * 展示区间 [est×0.7, est×1.5]
 */
export function estimateSeconds(mode: JobMode, pages: number, density: Density): number {
  const base: Record<JobMode, number> = { fast: 15, standard: 30, premium: 60 };
  const perPage: Record<JobMode, number> = { fast: 1.5, standard: 4, premium: 8 };
  const densityFactor = density === 'high' ? 1.2 : 1;
  return base[mode] + pages * perPage[mode] * densityFactor;
}

/** 估算区间的展示文案，如「预计 40s ～ 1m 26s」 */
export function estimateRangeText(mode: JobMode, pages: number, density: Density): string {
  const est = estimateSeconds(mode, pages, density);
  const low = Math.round(est * 0.7);
  const high = Math.round(est * 1.5);
  return `预计 ${formatDuration(low * 1000)} ～ ${formatDuration(high * 1000)}`;
}

/** 解析文档建议页数区间（兼容数组与对象两种后端形态） */
export function suggestPagesRange(doc: DocumentItem | null | undefined): [number, number] | null {
  const sp = doc?.suggest_pages;
  if (!sp) return null;
  if (Array.isArray(sp) && sp.length === 2) return [sp[0], sp[1]];
  if (typeof sp === 'object' && 'min' in sp && 'max' in sp) return [sp.min, sp.max];
  return null;
}
