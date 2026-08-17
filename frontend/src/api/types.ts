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

/** ---------- ppt-master 生成 ---------- */
/** 通用枚举项（key 为提交值，label 为展示名） */
export interface OptionItem {
  key: string;
  label: string;
  desc?: string;
}

/** GET /pptmaster/options：可选项与限制 */
export interface PptMasterOptions {
  /** local=当前 API 进程执行；worker=独立 pptmaster-worker 执行 */
  execution_scope?: 'local' | 'worker';
  /** ppt-master 仓库是否就绪 */
  repo: { dir: string; ready: boolean; version: string | null; delegated?: boolean };
  agents: {
    key: 'claude' | 'codex' | 'mock';
    label: string;
    available: boolean;
    bin?: string;
    note?: string;
  }[];
  /** 'claude' | 'codex' | 'mock' */
  default_agent: string;
  /** files 上传源文件 / topic 仅主题 / text 粘贴文本 / url 网页链接 */
  input_modes: OptionItem[];
  /** generate / template_fill / beautify / enhance / image_to_pptx / create_template */
  routes: (OptionItem & { needs_template?: boolean; needs_pptx?: boolean; agents?: string[] })[];
  /** quick 快速生成(推荐) / default 完整流程 */
  profiles: OptionItem[];
  /** ppt169/ppt43/xiaohongshu/moments/story/wechat/banner/a4 */
  canvas_formats: (OptionItem & { size: string; ratio: string })[];
  /** auto + 内置风格 + custom */
  styles: OptionItem[];
  narrative_modes: OptionItem[];
  reading_modes: OptionItem[];
  languages: OptionItem[];
  image_sources: OptionItem[];
  limits: {
    max_files: number;
    max_upload_mb: number;
    pages_min: number;
    pages_max: number;
    timeout_minutes_default: number;
    timeout_minutes_max: number;
  };
  /** 允许上传的扩展名，如 ['.pdf', '.docx', ...] */
  accept_extensions: string[];
}

export type PptMasterStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'canceled';

/** 产物条目（download_url 为后端代理下载地址） */
export interface PptMasterOutput {
  kind: 'pptx' | 'pptx_native' | 'pptx_narrated' | 'pdf' | 'log' | 'report' | string;
  name: string;
  size: number;
  download_url: string;
}

/** 列表项（GET /pptmaster/jobs） */
export interface PptMasterJob {
  job_id: string;
  title: string;
  input_mode: string;
  route: string;
  profile: string;
  agent: string;
  model: string | null;
  status: PptMasterStatus;
  progress: number;
  /** 当前阶段中文描述 */
  stage: string | null;
  /** 提交时的全部参数（原样） */
  params: Record<string, unknown>;
  source_files: { name: string; size: number }[];
  template_name: string | null;
  /** 成功后非空 */
  outputs: PptMasterOutput[];
  /** 主产物下载地址（便捷字段） */
  pptx_url: string | null;
  /** 可预览页数（0=无预览） */
  preview_pages: number;
  /** /api/v1/pptmaster/jobs/{id}/pages/{n}/image（svg 或 png） */
  preview_urls: string[];
  page_count: number | null;
  file_size: number | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  /** Agent 用量（运行结束后回填）：cost_usd / num_turns / returncode / final_text */
  run?: { cost_usd?: number | null; num_turns?: number | null; returncode?: number | null; final_text?: string } | null;
}

/** 详情（GET /pptmaster/jobs/{id}） */
export interface PptMasterJobDetail extends PptMasterJob {
  /** 实际发给 Agent 的提示词 */
  prompt: string;
  /** 最近约 4KB 日志（running 时随轮询更新） */
  log_tail: string;
  /** /api/v1/pptmaster/jobs/{id}/log */
  log_url: string;
}

export interface PptMasterJobListResult {
  items: PptMasterJob[];
  total: number;
}
