import axios, { AxiosError } from 'axios';
import { message } from 'antd';
import type { ApiEnvelope } from './types';

/**
 * axios 封装：
 * - 统一 Base URL /api/v1
 * - 响应拦截器拆包 {code, message, data}，code 非 0 视为业务错误
 * - 统一错误提示（antd message）
 */

/** 业务错误：携带后端 code 与 message */
export class BizError extends Error {
  code: number;
  constructor(code: number, msg: string) {
    super(msg);
    this.code = code;
    this.name = 'BizError';
  }
}

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 60_000,
});

http.interceptors.response.use(
  (resp) => {
    const body = resp.data as ApiEnvelope<unknown>;
    // 非标准包裹（如文件流）直接放行
    if (body === null || typeof body !== 'object' || !('code' in body)) {
      return resp;
    }
    if (body.code !== 0) {
      const err = new BizError(body.code, body.message || '请求失败');
      message.error(err.message);
      return Promise.reject(err);
    }
    // 拆包：把 data 提升为响应数据
    resp.data = body.data;
    return resp;
  },
  (error: AxiosError<ApiEnvelope<unknown>>) => {
    // HTTP 层错误：尽量取后端 message，否则给通用文案
    const bizMsg = error.response?.data?.message;
    const text =
      bizMsg ||
      (error.code === 'ECONNABORTED'
        ? '请求超时，请稍后重试'
        : error.response
          ? `请求失败（HTTP ${error.response.status}）`
          : '网络异常，请检查连接');
    message.error(text);
    return Promise.reject(error);
  },
);

/** GET 请求，返回已拆包的 data */
export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const resp = await http.get<T>(url, { params });
  return resp.data;
}

/** POST 请求，返回已拆包的 data */
export async function post<T>(url: string, body?: unknown): Promise<T> {
  const resp = await http.post<T>(url, body);
  return resp.data;
}

/** DELETE 请求 */
export async function del<T>(url: string): Promise<T> {
  const resp = await http.delete<T>(url);
  return resp.data;
}

/** multipart 文件上传 */
export async function upload<T>(url: string, file: File): Promise<T> {
  const form = new FormData();
  form.append('file', file);
  const resp = await http.post<T>(url, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300_000, // 大文件上传放宽超时
  });
  return resp.data;
}

/** multipart 表单上传（调用方自行组装 FormData：多文件 + 业务字段） */
export async function uploadForm<T>(url: string, form: FormData): Promise<T> {
  const resp = await http.post<T>(url, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 600_000, // 多文件上传放宽超时
  });
  return resp.data;
}
