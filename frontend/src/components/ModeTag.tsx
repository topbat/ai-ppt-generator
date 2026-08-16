import { Tag } from 'antd';
import type { JobMode } from '../api/types';
import { MODE_CONFIG } from '../utils/constants';

/** 模式徽标：⚡极速(琥珀) / 🚀标准(蓝) / 💎专业(紫) */
export default function ModeTag({ mode }: { mode: JobMode }) {
  const cfg = MODE_CONFIG[mode];
  if (!cfg) return <Tag>{mode}</Tag>;
  return (
    <Tag color={cfg.color}>
      {cfg.icon}
      {cfg.label}
    </Tag>
  );
}
