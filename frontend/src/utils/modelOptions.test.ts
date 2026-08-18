import { describe, expect, it } from 'vitest';

import {
  isTemplateStyleLocked,
  resolvePptMasterModel,
  resolveInitialModel,
  resolvePptMasterStyle,
  stageTooltipText,
} from './modelOptions';


describe('resolveInitialModel', () => {
  const models = ['deepseek-v4-pro', 'kimi-k3', 'qwen3.7-plus', 'qwen3.8-max'];

  it('uses the configured default when it belongs to the catalog', () => {
    expect(resolveInitialModel(models, 'qwen3.7-plus')).toBe('qwen3.7-plus');
  });

  it('rejects an absent or unknown configured default', () => {
    expect(() => resolveInitialModel(models, 'qwen-max')).toThrow('默认模型');
    expect(() => resolveInitialModel([], 'qwen3.7-plus')).toThrow('可选模型');
  });
});


describe('resolvePptMasterModel', () => {
  const models = ['deepseek-v4-pro', 'kimi-k3', 'qwen3.7-plus', 'qwen3.8-max'];

  it('defaults the beautify route to kimi-k3', () => {
    expect(resolvePptMasterModel('beautify', models, 'qwen3.7-plus', 'kimi-k3')).toBe('kimi-k3');
  });

  it('uses the normal configured default on non-beautify routes', () => {
    expect(resolvePptMasterModel('generate', models, 'qwen3.7-plus', 'kimi-k3')).toBe('qwen3.7-plus');
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


describe('stageTooltipText', () => {
  it('shows the complete stage path with arrows', () => {
    expect(stageTooltipText(['准备工作区', '启动 Agent', '生成 SVG'])).toBe(
      '准备工作区 --> 启动 Agent --> 生成 SVG',
    );
  });

  it('falls back to the current stage when history is empty', () => {
    expect(stageTooltipText([], '排队中')).toBe('排队中');
  });
});
