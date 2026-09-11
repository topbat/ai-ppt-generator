import { afterEach, describe, expect, it, vi } from 'vitest';
import { metricText, metricsFetch } from './metrics';

afterEach(() => vi.unstubAllGlobals());
describe('指标访问', () => {
  it('未知值和零值分别显示', () => {
    expect(metricText(null)).toBe('未知');
    expect(metricText(0)).toBe('0');
  });
  it('令牌仅进入请求头，筛选参数正确编码', async () => {
    const mock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 0, data: { count: 2 } })));
    vi.stubGlobal('fetch', mock);
    expect(await metricsFetch('summary', 'secret', { model: 'a/b' })).toEqual({ count: 2 });
    expect(mock.mock.calls[0][0]).toBe('/api/v1/metrics/summary?model=a%2Fb');
    expect(mock.mock.calls[0][1].headers.Authorization).toBe('Bearer secret');
  });
  it('未授权时返回可操作的中文错误', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })));
    await expect(metricsFetch('summary', 'bad')).rejects.toThrow('访问令牌');
  });
});
