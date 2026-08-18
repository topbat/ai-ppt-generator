export function resolveInitialModel(models: string[], defaultModel: string): string {
  if (models.length === 0) {
    throw new Error('可选模型列表为空');
  }
  if (!models.includes(defaultModel)) {
    throw new Error(`默认模型 ${defaultModel || '<empty>'} 不在可选模型列表中`);
  }
  return defaultModel;
}
