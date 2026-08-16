/**
 * API 数据类型定义（与后端契约一一对应，不得随意更改）
 */

/** 统一响应包裹 */
export interface ApiEnvelope<T> {
  code: number;
  message: string;
  data: T;
}

/** 生成模式 */
export type JobMode = 'fast' | 'standard' | 'premium';
/** 内容密度 */
export type Density = 'low' | 'medium' | 'high';
/** 任务状态 */
export type JobStatus =
  | 'pending'
  | 'running'
  | 'waiting_user'
  | 'succeeded'
  | 'failed'
  | 'canceled';
/** 阶段状态 */
export type StageStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'warning'
  | 'failed'
  | 'skipped';
/** 重试能力 */
export type Retryable = 'resume' | 'restart_with_input' | 'no';
/** 重试策略 */
export type RetryStrategy = 'resume' | 'restart' | 'restart_with_input';

/** ---------- 模板 ---------- */
export type TemplateStatus = 'parsing' | 'ready' | 'failed';

export interface TemplateLayout {
  slide_index: number;
  slide_type: string;
  confidence: number;
  thumbnail_url?: string | null;
}

export interface DesignTokens {
  primary?: string;
  font_title?: string;
  font_body?: string;
  [key: string]: unknown;
}

export interface TemplateItem {
  id: string; // biz_id
  name: string;
  status: TemplateStatus;
  is_system?: boolean;
  slide_count?: number | null;
  thumbnail_url?: string | null;
  design_tokens?: DesignTokens | null;
  parse_error?: string | null;
  missing_layouts?: string[]; // 缺失版式警告
  layouts?: TemplateLayout[]; // 版式清单（详情）
  created_at?: string;
}

/** AI 生成模板：八维参数（主题/关键字为自由文本，其余从 ai-options 取值） */
export interface AiTemplateParams {
  industry?: string; // 行业
  audience?: string; // 用户群
  style?: string; // 风格
  data_content?: string; // 数据内容
  theme?: string; // 主题
  keywords?: string; // 关键字
  country?: string; // 国家
  season?: string; // 季节
}

/** AI 生成模板可选项（八维中的六个枚举维度） */
export interface AiTemplateOptions {
  industries: string[];
  audiences: string[];
  styles: string[];
  data_contents: string[];
  countries: string[];
  seasons: string[];
}

/** 美化记录（GET /beautify 列表项） */
export interface BeautifyRecordItem {
  beautify_id: string;
  filename: string;
  source_name: string;
  file_size: number;
  total_pages?: number | null;
  score_before?: number | null;
  score_after?: number | null;
  fixes?: { black_text_fixed?: number; aligned?: number; spacing_snapped?: number };
  fix_count?: number;
  download_url: string;
  created_at?: string | null;
}

export interface BeautifyListResult {
  items: BeautifyRecordItem[];
  total: number;
}

/** 上传 PPT 专业级美化结果（POST /beautify） */
export interface BeautifyResult {
  beautify_id: string;
  filename: string;
  download_url: string;
  score_before: number;
  score_after: number;
  dimensions: Record<string, { score: number; max: number; name: string }>;
  dimensions_before?: Record<string, { score: number; max: number; name: string }>;
  fixes: { black_text_fixed: number; aligned: number; spacing_snapped: number };
  pages: { page: number; score: number; deductions?: { dim: string; points: number; detail: string }[] }[];
  total_pages: number;
}

/** ---------- 文档 ---------- */
export type ParseStatus = 'parsing' | 'ready' | 'failed';

export interface DocumentItem {
  id: string; // biz_id
  name: string;
  file_type?: 'pdf' | 'docx';
  parse_status: ParseStatus;
  parse_error?: string | null;
  page_count?: number | null;
  char_count?: number | null;
  table_count?: number | null;
  image_count?: number | null;
  chapter_count?: number | null;
  is_scanned?: boolean;
  /** 建议页数区间，如 [14, 20] */
  suggest_pages?: [number, number] | { min: number; max: number } | null;
  created_at?: string;
}

/** ---------- 任务 ---------- */
export interface JobStage {
  stage_code: string;
  name: string;
  status: StageStatus;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  attempt?: number;
}

export interface JobDetail {
  biz_id: string;
  status: JobStatus;
  mode: JobMode;
  density: Density;
  target_pages: number;
  progress: number; // 0~100
  current_stage?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  failed_stage?: string | null;
  quality_score?: number | null;
  /** 视觉分（九维规则引擎，与质量分并列展示） */
  visual_score?: number | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  queue_ms?: number | null;
  duration_ms?: number | null;
  stages?: JobStage[];
  template_name?: string | null;
  document_name?: string | null;
  template_id?: string | null;
  document_id?: string | null;
  thumbnail_url?: string | null;
  title?: string | null;
  /** 产物文件名（与下载文件名一致，列表/详情统一展示） */
  output_filename?: string | null;
  retryable?: Retryable;
  suggestion?: string | null; // 失败建议文案（可选）
}

export interface JobListResult {
  items: JobDetail[];
  total: number;
}

export interface CreateJobParams {
  template_id: string;
  document_id: string;
  pages: number;
  mode: JobMode;
  density: Density;
  options?: Record<string, unknown>;
}

/** ---------- 页面 ---------- */
export interface ContentCard {
  title: string;
  bullets: string[];
}

export interface SlideSource {
  document_id?: string;
  document_name?: string;
  pages: number[];
}

export interface SlideItem {
  page_no: number;
  slide_type: string;
  title?: string | null;
  status?: string;
  thumb_url?: string | null;
  image_url?: string | null;
  sources?: SlideSource[] | null;
  degrade_reason?: string | null;
  content_card?: ContentCard | null;
  /** 页级视觉分 */
  visual_score?: number | null;
}

/** ---------- 产物与报告 ---------- */
export interface JobOutput {
  pptx_url: string;
  pdf_url?: string | null;
  report_url?: string | null;
  /** 下载文件名（与列表展示名一致） */
  filename?: string;
}

export interface ReportIssue {
  page?: number;
  issue_type?: string;
  severity?: string;
  message?: string;
  suggestion?: string;
  [key: string]: unknown;
}

/** 视觉评分单维度 */
export interface VisualDimension {
  score: number;
  max: number;
  name: string; // 中文维度名（布局/对齐/字体/…）
}

/** 视觉评分逐页明细 */
export interface VisualPageScore {
  page: number;
  score: number;
  deductions?: { dim: string; points: number; detail: string }[];
}

/** 视觉九维报告（visual_score，与质量分并列） */
export interface VisualReport {
  score: number;
  dimensions: Record<string, VisualDimension>;
  score_before?: number | null;
  rounds?: number | null;
  ops_applied?: { op: string; page: number; detail?: string }[];
  pages?: VisualPageScore[];
}

export interface QualityReport {
  status: string;
  score?: number;
  errors?: number;
  warnings?: number;
  checks?: Record<string, unknown>;
  issues?: ReportIssue[];
  visual?: VisualReport;
}

/** ---------- 管理统计 ---------- */
export interface AdminStats {
  total: number;
  succeeded: number;
  failed: number;
  running: number;
  by_mode: Record<string, number>;
  avg_duration_ms: Record<string, number>;
}

/** ---------- SSE 事件 ---------- */
export interface StageUpdateEvent {
  seq: number;
  stage: string;
  status: StageStatus;
  progress: { done: number; total: number } | null;
  elapsed_ms?: number;
}

export interface PageDoneEvent {
  seq: number;
  page: number;
  content_card: ContentCard;
}

export interface ThumbnailReadyEvent {
  seq: number;
  page: number;
  url: string;
}

export type DecisionKind = 'fact_conflict' | 'page_budget' | 'content_shortage';

export interface DecisionOption {
  value: string;
  label: string;
  detail?: string;
}

export interface DecisionRequiredEvent {
  seq: number;
  decision_id: string;
  kind: DecisionKind;
  payload: {
    title: string;
    description?: string;
    options: DecisionOption[];
  };
  deadline_ts?: string | number | null;
  default_choice?: string | null;
}

export interface JobDoneEvent {
  seq: number;
  quality_score?: number;
}

export interface JobFailedEvent {
  seq: number;
  error_code?: string;
  error_message?: string;
  failed_stage?: string;
}
