import { Badge } from 'antd';
import type { JobStatus } from '../api/types';
import { STATUS_CONFIG } from '../utils/constants';

/** 任务状态徽标：色点 + 文案双编码 */
export default function StatusTag({
  status,
  extra,
}: {
  status: JobStatus;
  /** 附加文案，如百分比 / 质量分 / 错误码 */
  extra?: string;
}) {
  const cfg = STATUS_CONFIG[status];
  if (!cfg) return <Badge status="default" text={status} />;
  const text = extra ? `${cfg.label} ${extra}` : cfg.label;
  return <Badge status={cfg.badge} text={text} />;
}
