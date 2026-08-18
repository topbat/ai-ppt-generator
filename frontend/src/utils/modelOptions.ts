export function resolveInitialModel(models: string[], defaultModel: string): string {
  if (models.length === 0) {
    throw new Error('可选模型列表为空');
  }
  if (!models.includes(defaultModel)) {
    throw new Error(`默认模型 ${defaultModel || '<empty>'} 不在可选模型列表中`);
  }
  return defaultModel;
}

export function isTemplateStyleLocked(route: string): boolean {
  return route === 'template_fill';
}

export function resolvePptMasterStyle(route: string, currentStyle: string): string {
  if (isTemplateStyleLocked(route)) return 'template';
  return currentStyle === 'template' ? 'auto' : currentStyle;
}

export function stageTooltipText(history: string[] | undefined, currentStage?: string): string {
  const stages = (history ?? []).filter((item) => item.trim().length > 0);
  if (stages.length > 0) return stages.join(' --> ');
  return currentStage ?? '';
}
