import { useEffect, useMemo, useState } from 'react';
import { Alert, Modal, Radio, Space, Typography, message } from 'antd';
import { ExclamationCircleOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { jobApi } from '../api/endpoints';
import type { DecisionRequiredEvent } from '../api/types';
import { DECISION_KIND_TITLE } from '../utils/constants';
import { formatDuration } from '../utils/format';

/**
 * 决策中断弹窗（阻塞式）：
 * - Radio 展示选项（label + detail）
 * - 显示倒计时与默认策略说明（超时后端按 default_choice 自动继续）
 * - 提交 POST /jobs/{id}/decisions/{decision_id}
 * - 不可通过遮罩/ESC 关闭（阻塞式），但提供"暂不选择"交由默认策略
 */
export default function DecisionModal({
  jobId,
  decision,
  onResolved,
}: {
  jobId: string;
  decision: DecisionRequiredEvent | null;
  /** 提交成功或放弃选择后回调（父组件清除 decision 状态） */
  onResolved: () => void;
}) {
  const [choice, setChoice] = useState<string | undefined>(undefined);
  const [submitting, setSubmitting] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  // 打开新决策时重置选中项为默认策略
  useEffect(() => {
    setChoice(decision?.default_choice ?? undefined);
  }, [decision?.decision_id, decision?.default_choice]);

  // 倒计时每秒刷新
  useEffect(() => {
    if (!decision) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [decision]);

  /** 剩余毫秒数（deadline_ts 支持 ISO 字符串或时间戳） */
  const remainMs = useMemo(() => {
    if (!decision?.deadline_ts) return null;
    const deadline =
      typeof decision.deadline_ts === 'number'
        ? decision.deadline_ts
        : dayjs(decision.deadline_ts).valueOf();
    return Math.max(0, deadline - now);
  }, [decision?.deadline_ts, now]);

  if (!decision) return null;

  const title = DECISION_KIND_TITLE[decision.kind] ?? '需要您确认';
  const defaultOption = decision.payload.options.find(
    (o) => o.value === decision.default_choice,
  );

  const handleSubmit = async () => {
    if (!choice) {
      message.warning('请先选择一个选项');
      return;
    }
    setSubmitting(true);
    try {
      await jobApi.decide(jobId, decision.decision_id, choice);
      message.success('已提交选择，任务继续执行');
      onResolved();
    } catch {
      // 错误提示已由 client 统一处理
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open
      title={
        <Space>
          <ExclamationCircleOutlined style={{ color: '#faad14' }} />
          {title}
        </Space>
      }
      okText="确认选择"
      cancelText="暂不选择（按默认策略）"
      onOk={handleSubmit}
      onCancel={onResolved}
      confirmLoading={submitting}
      maskClosable={false}
      keyboard={false}
      closable={false}
      width={560}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Typography.Paragraph style={{ marginBottom: 0 }}>
          <Typography.Text strong>{decision.payload.title}</Typography.Text>
          {decision.payload.description && (
            <>
              <br />
              <Typography.Text type="secondary">{decision.payload.description}</Typography.Text>
            </>
          )}
        </Typography.Paragraph>

        <Radio.Group
          value={choice}
          onChange={(e) => setChoice(e.target.value as string)}
          style={{ width: '100%' }}
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            {decision.payload.options.map((opt) => (
              <Radio key={opt.value} value={opt.value}>
                <Space direction="vertical" size={0}>
                  <span>{opt.label}</span>
                  {opt.detail && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {opt.detail}
                    </Typography.Text>
                  )}
                </Space>
              </Radio>
            ))}
          </Space>
        </Radio.Group>

        <Alert
          type="info"
          showIcon
          message={
            <>
              {remainMs != null && (
                <>
                  剩余 <Typography.Text strong>{formatDuration(remainMs)}</Typography.Text>
                  {'，'}
                </>
              )}
              超时后将按默认策略
              {defaultOption ? `（${defaultOption.label}）` : ''}自动继续
            </>
          }
        />
      </Space>
    </Modal>
  );
}
