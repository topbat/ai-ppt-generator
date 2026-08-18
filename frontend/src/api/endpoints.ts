import { get, post, del, upload, uploadForm } from './client';
import type {
  AdminStats,
  AiTemplateOptions,
  AiTemplateParams,
  BeautifyListResult,
  BeautifyResult,
  CreateJobParams,
  DocumentItem,
  JobDetail,
  JobListResult,
  JobMode,
  JobOptions,
  JobOutput,
  JobStatus,
  PptMasterJobDetail,
  PptMasterJobListResult,
  PptMasterOptions,
  PptMasterStatus,
  QualityReport,
  RetryStrategy,
  SlideItem,
  TemplateItem,
} from './types';

/** ---------- 模板 ---------- */
export const templateApi = {
  /** 上传模板（.pptx，multipart），后端异步解析 */
  upload: (file: File) => upload<TemplateItem>('/templates', file),
  list: (q?: string) => get<TemplateItem[]>('/templates', q ? { q } : undefined),
  detail: (id: string) => get<TemplateItem>(`/templates/${id}`),
  remove: (id: string) => del<null>(`/templates/${id}`),
  /** 批量删除模板 */
  batchRemove: (ids: string[]) =>
    post<{ deleted: number; skipped: string[] }>('/templates/batch-delete', { ids }),
  /** AI 生成模板：八维参数选项与生成入口 */
  aiOptions: () => get<AiTemplateOptions>('/templates/ai-options'),
  aiGenerate: (params: AiTemplateParams) =>
    post<TemplateItem>('/templates/ai-generate', params),
};

/** ---------- 文档 ---------- */
export const documentApi = {
  /** 上传主文档（PDF/DOCX），上传后需轮询解析状态 */
  upload: (file: File) => upload<DocumentItem>('/documents', file),
  detail: (id: string) => get<DocumentItem>(`/documents/${id}`),
};

/** ---------- 任务 ---------- */
export const jobApi = {
  options: () => get<JobOptions>('/jobs/options'),
  create: (params: CreateJobParams) => post<{ job_id: string }>('/jobs', params),
  list: (params: {
    status?: JobStatus | '';
    mode?: JobMode | '';
    page?: number;
    page_size?: number;
  }) => get<JobListResult>('/jobs', params),
  detail: (id: string) => get<JobDetail>(`/jobs/${id}`),
  cancel: (id: string) => post<null>(`/jobs/${id}/cancel`),
  retry: (
    id: string,
    body: { strategy: RetryStrategy; document_id?: string; template_id?: string },
  ) => post<{ job_id?: string }>(`/jobs/${id}/retry`, body),
  decide: (id: string, decisionId: string, choice: string) =>
    post<null>(`/jobs/${id}/decisions/${decisionId}`, { choice }),
  slides: (id: string) => get<SlideItem[]>(`/jobs/${id}/slides`),
  output: (id: string) => get<JobOutput>(`/jobs/${id}/output`),
  report: (id: string) => get<QualityReport>(`/jobs/${id}/report`),
  /** 一键美化：以原任务为父创建新版本 Job，只跑渲染+视觉优化链路 */
  beautify: (id: string) => post<{ job_id: string }>(`/jobs/${id}/beautify`),
};

/** ---------- PPT 专业级美化（独立能力） ---------- */
export const beautifyApi = {
  /** 上传 PPTX → 九维评分 + 确定性美化 → 产物存 MinIO → 报告与下载链接 */
  upload: (file: File) => upload<BeautifyResult>('/beautify', file),
  /** 美化记录列表（创建时间倒序） */
  list: (params?: { page?: number; page_size?: number }) =>
    get<BeautifyListResult>('/beautify', params),
};

/** ---------- ppt-master 生成（异步提交 → 轮询） ---------- */
export const pptmasterApi = {
  /** 可选项与限制（输入方式/路线/档位/画布/风格/Agent 等） */
  options: () => get<PptMasterOptions>('/pptmaster/options'),
  /** 提交生成任务（multipart：业务字段 + files[] + template），秒回 job_id */
  create: (form: FormData) => uploadForm<{ job_id: string }>('/pptmaster/jobs', form),
  list: (params: { status?: PptMasterStatus | ''; page?: number; page_size?: number }) =>
    get<PptMasterJobListResult>('/pptmaster/jobs', params),
  detail: (id: string) => get<PptMasterJobDetail>(`/pptmaster/jobs/${id}`),
  cancel: (id: string) =>
    post<{ job_id: string; status: PptMasterStatus }>(`/pptmaster/jobs/${id}/cancel`),
  remove: (id: string) => del<{ deleted: boolean }>(`/pptmaster/jobs/${id}`),
  // 下载 / 预览图 / 完整日志为后端代理的文件流，直接使用返回数据里的
  // download_url / preview_urls / log_url 放到 <a href> / <img src> 即可。
};

/** ---------- 管理端 ---------- */
export const adminApi = {
  stats: () => get<AdminStats>('/admin/stats'),
};

/**
 * 健康检查：/healthz 在 /api/v1 之外，直接请求根路径
 * （nginx 配置了独立 location 代理到后端）
 */
export async function checkHealth(): Promise<boolean> {
  try {
    const resp = await fetch('/healthz', { cache: 'no-store' });
    return resp.ok;
  } catch {
    return false;
  }
}
