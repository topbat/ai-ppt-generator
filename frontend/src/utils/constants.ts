import type { Density, JobMode, JobStatus, StageStatus } from '../api/types';

/** 模式展示配置：图标/名称/配色（琥珀/蓝/紫） */
export const MODE_CONFIG: Record<
  JobMode,
  { icon: string; label: string; color: string; desc: string }
> = {
  fast: { icon: '⚡', label: '极速', color: 'gold', desc: '内部草稿' },
  standard: { icon: '🚀', label: '标准', color: 'blue', desc: '日常正式汇报' },
  premium: { icon: '💎', label: '专业', color: 'purple', desc: '对外方案/汇报' },
};

/** 任务状态展示配置 */
export const STATUS_CONFIG: Record<
  JobStatus,
  { label: string; color: string; badge: 'default' | 'processing' | 'warning' | 'success' | 'error' }
> = {
  pending: { label: '排队中', color: 'default', badge: 'default' },
  running: { label: '生成中', color: 'processing', badge: 'processing' },
  waiting_user: { label: '待确认', color: 'orange', badge: 'warning' },
  succeeded: { label: '成功', color: 'success', badge: 'success' },
  failed: { label: '失败', color: 'error', badge: 'error' },
  canceled: { label: '已取消', color: 'default', badge: 'default' },
};

/** 密度展示配置 */
export const DENSITY_CONFIG: Record<Density, string> = {
  low: '紧凑-要点式',
  medium: '标准',
  high: '充实-详实型',
};

/** 阶段编码 → 中文名（后端 stages 里已带 name，此表用于 SSE 事件兜底） */
export const STAGE_NAMES: Record<string, string> = {
  VALIDATE: '输入校验',
  PARSE_DOC: '文档解析',
  PARSE_TPL: '模板解析',
  KNOWLEDGE: '内容理解',
  FACT_CHECK: '事实核验',
  OUTLINE: '大纲生成',
  PLAN: '目录与页面规划',
  CONTENT: '页面内容生成',
  MATCH: '模板匹配',
  LAYOUT: '布局计算',
  RENDER: '模板匹配与渲染',
  CONVERT: 'PDF/PNG 转换',
  QA: '质量检查',
  REPAIR: '自动修复',
  PUBLISH: '上传与归档',
};

export function stageName(code: string | null | undefined, fallbackName?: string): string {
  if (fallbackName) return fallbackName;
  if (!code) return '-';
  return STAGE_NAMES[code] ?? code;
}

/** 阶段状态图标（文本符号，配合颜色使用） */
export const STAGE_STATUS_META: Record<StageStatus, { label: string }> = {
  pending: { label: '未开始' },
  running: { label: '进行中' },
  success: { label: '完成' },
  warning: { label: '完成(有警告)' },
  failed: { label: '失败' },
  skipped: { label: '已跳过' },
};

/** 决策类型标题 */
export const DECISION_KIND_TITLE: Record<string, string> = {
  fact_conflict: '发现事实冲突，需要您确认',
  page_budget: '页数预算冲突，需要您确认',
  content_shortage: '资料内容不足，需要您确认',
};
