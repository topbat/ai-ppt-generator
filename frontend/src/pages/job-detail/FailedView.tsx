import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Card,
  Descriptions,
  Flex,
  Modal,
  Space,
  Spin,
  Steps,
  Typography,
  Upload,
  message,
} from 'antd';
import {
  CloseCircleOutlined,
  FileAddOutlined,
  InboxOutlined,
  RedoOutlined,
} from '@ant-design/icons';
import type { UploadRequestOption } from 'rc-upload/lib/interface';
import { documentApi, jobApi } from '../../api/endpoints';
import type { DocumentItem, JobDetail, StageStatus } from '../../api/types';
import { stageName } from '../../utils/constants';
import { formatDuration } from '../../utils/format';

const POLL_MS = 2000;

/** 失败视图：失败三要素大字展示 + 按 retryable 切换主按钮 + 阶段横向流程 */
export default function FailedView({
  jobId,
  detail,
  onRefresh,
}: {
  jobId: string;
  detail: JobDetail;
  onRefresh: () => void;
}) {
  const navigate = useNavigate();
  const [retrying, setRetrying] = useState(false);
  const [docModalOpen, setDocModalOpen] = useState(false);

  const retryable = detail.retryable ?? 'no';

  /** 断点重试 */
  const handleResume = async () => {
    setRetrying(true);
    try {
      const res = await jobApi.retry(jobId, { strategy: 'resume' });
      message.success('已发起断点重试');
      const newId = res?.job_id ?? jobId;
      if (newId !== jobId) navigate(`/jobs/${newId}`);
      else onRefresh();
    } catch {
      /* 已统一提示 */
    } finally {
      setRetrying(false);
    }
  };

  /** 找到失败阶段位置，用于横向流程展示 */
  const stages = detail.stages ?? [];
  const failedIdx = stages.findIndex(
    (s) => s.status === 'failed' || s.stage_code === detail.failed_stage,
  );

  const stepStatus = (s: StageStatus): 'finish' | 'error' | 'wait' | 'process' => {
    switch (s) {
      case 'success':
      case 'warning':
      case 'skipped':
        return 'finish';
      case 'failed':
        return 'error';
      case 'running':
        return 'process';
      default:
        return 'wait';
    }
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Flex align="center" gap={12}>
            <CloseCircleOutlined style={{ fontSize: 40, color: '#ff4d4f' }} />
            <Typography.Title level={3} style={{ margin: 0 }}>
              生成失败
            </Typography.Title>
          </Flex>

          {/* 失败三要素：哪一步 + 什么原因 + 怎么办 */}
          <Descriptions
            column={1}
            size="middle"
            labelStyle={{ width: 100, fontSize: 15 }}
            contentStyle={{ fontSize: 15 }}
          >
            <Descriptions.Item label="失败阶段">
              {stageName(detail.failed_stage)}
              {failedIdx >= 0 && stages.length > 0 && (
                <Typography.Text type="secondary">
                  （第{failedIdx + 1}/{stages.length}阶段）
                </Typography.Text>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="错误码">
              <Typography.Text code copyable>
                {detail.error_code ?? '-'}
              </Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="原因">
              <Typography.Text type="danger">
                {detail.error_message || '未知错误'}
              </Typography.Text>
            </Descriptions.Item>
            {detail.suggestion && (
              <Descriptions.Item label="建议">{detail.suggestion}</Descriptions.Item>
            )}
          </Descriptions>

          {/* 操作按钮：主按钮按 retryable 切换 */}
          <Space wrap>
            {retryable === 'resume' && (
              <Button
                type="primary"
                icon={<RedoOutlined />}
                loading={retrying}
                onClick={handleResume}
              >
                断点重试
              </Button>
            )}
            {retryable === 'restart_with_input' && (
              <Button
                type="primary"
                icon={<FileAddOutlined />}
                onClick={() => setDocModalOpen(true)}
              >
                更换文档后重试
              </Button>
            )}
            {/* 次要操作 */}
            {retryable === 'resume' && (
              <Button icon={<FileAddOutlined />} onClick={() => setDocModalOpen(true)}>
                更换文档后重试
              </Button>
            )}
            {retryable === 'no' && (
              <Typography.Text type="secondary">
                该错误不可自动重试，请新建任务
              </Typography.Text>
            )}
          </Space>
        </Space>
      </Card>

      {/* 阶段执行情况：横向流程 */}
      {stages.length > 0 && (
        <Card size="small" title="阶段执行情况">
          <div style={{ overflowX: 'auto', paddingBottom: 8 }}>
            <Steps
              size="small"
              labelPlacement="vertical"
              items={stages.map((s) => ({
                title: stageName(s.stage_code, s.name),
                status: stepStatus(s.status),
                description:
                  s.status === 'failed'
                    ? `失败 ${formatDuration(s.duration_ms)}${(s.attempt ?? 1) > 1 ? `（重试${(s.attempt ?? 1) - 1}次）` : ''}`
                    : s.status === 'success' || s.status === 'warning'
                      ? formatDuration(s.duration_ms)
                      : s.status === 'skipped'
                        ? '跳过'
                        : '未执行',
              }))}
            />
          </div>
        </Card>
      )}

      {/* 更换文档弹窗 */}
      <ReplaceDocModal
        open={docModalOpen}
        onClose={() => setDocModalOpen(false)}
        onConfirm={async (documentId) => {
          try {
            const res = await jobApi.retry(jobId, {
              strategy: 'restart_with_input',
              document_id: documentId,
            });
            message.success('已使用新文档发起重试');
            setDocModalOpen(false);
            const newId = res?.job_id ?? jobId;
            if (newId !== jobId) navigate(`/jobs/${newId}`);
            else onRefresh();
          } catch {
            /* 已统一提示 */
          }
        }}
      />
    </Space>
  );
}

/** 更换文档弹窗：上传新文档 → 轮询解析就绪 → 确认后以新文档重试 */
function ReplaceDocModal({
  open,
  onClose,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: (documentId: string) => Promise<void>;
}) {
  const [doc, setDoc] = useState<DocumentItem | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // 弹窗关闭时重置
  useEffect(() => {
    if (!open) setDoc(null);
  }, [open]);

  // 解析中轮询
  useEffect(() => {
    if (!open || !doc || doc.parse_status !== 'parsing') return;
    const timer = window.setInterval(async () => {
      try {
        const d = await documentApi.detail(doc.id);
        setDoc(d);
      } catch {
        /* 静默 */
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [open, doc]);

  const uploadDoc = async (options: UploadRequestOption) => {
    const file = options.file as File;
    try {
      const d = await documentApi.upload(file);
      setDoc(d);
      options.onSuccess?.(d);
    } catch (e) {
      options.onError?.(e as Error);
    }
  };

  return (
    <Modal
      open={open}
      title="更换文档后重试"
      okText="确认并重试"
      cancelText="取消"
      okButtonProps={{ disabled: !doc || doc.parse_status !== 'ready' }}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={async () => {
        if (!doc) return;
        setSubmitting(true);
        try {
          await onConfirm(doc.id);
        } finally {
          setSubmitting(false);
        }
      }}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Upload.Dragger
          accept=".pdf,.docx"
          showUploadList={false}
          customRequest={uploadDoc}
          beforeUpload={(file) => {
            if (file.size > 100 * 1024 * 1024) {
              message.error('文档不能超过 100MB');
              return Upload.LIST_IGNORE;
            }
            return true;
          }}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">拖拽或点击上传新的 PDF / DOCX</p>
          <p className="ant-upload-hint">≤100MB，≤500页</p>
        </Upload.Dragger>

        {doc && (
          <Card size="small">
            <Space>
              <Typography.Text strong>{doc.name}</Typography.Text>
              {doc.parse_status === 'parsing' && (
                <Typography.Text type="secondary">
                  <Spin size="small" /> 解析中…
                </Typography.Text>
              )}
              {doc.parse_status === 'ready' && (
                <Typography.Text type="success">解析通过，可以重试</Typography.Text>
              )}
              {doc.parse_status === 'failed' && (
                <Typography.Text type="danger">
                  解析失败{doc.parse_error ? `（${doc.parse_error}）` : ''}，请更换文件
                </Typography.Text>
              )}
            </Space>
          </Card>
        )}
      </Space>
    </Modal>
  );
}
