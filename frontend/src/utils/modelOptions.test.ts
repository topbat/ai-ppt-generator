import { describe, expect, it } from 'vitest';

import { isTemplateStyleLocked, resolveInitialModel, resolvePptMasterStyle } from './modelOptions';


describe('resolveInitialModel', () => {
  const models = ['deepseek-v4', 'qwen3.7-plus', 'qwen3.8-max'];

  it('uses the configured default when it belongs to the catalog', () => {
    expect(resolveInitialModel(models, 'qwen3.7-plus')).toBe('qwen3.7-plus');
  });

  it('rejects an absent or unknown configured default', () => {
    expect(() => resolveInitialModel(models, 'qwen-max')).toThrow('默认模型');
    expect(() => resolveInitialModel([], 'qwen3.7-plus')).toThrow('可选模型');
  });
});


describe('PPT-MASTER template style lock', () => {
  it('locks template_fill to the template visual style', () => {
    expect(isTemplateStyleLocked('template_fill')).toBe(true);
    expect(resolvePptMasterStyle('template_fill', 'swiss-minimal')).toBe('template');
  });

  it('preserves user style on other routes', () => {
    expect(isTemplateStyleLocked('generate')).toBe(false);
    expect(resolvePptMasterStyle('generate', 'swiss-minimal')).toBe('swiss-minimal');
  });
});
