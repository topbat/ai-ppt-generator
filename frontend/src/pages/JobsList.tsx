import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Button,
  Card,
  Empty,
  Flex,
  Pagination,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { jobApi } from '../api/endpoints';
import type { JobDetail, JobMode, JobStatus } from '../api/types';
import ModeTag from '../components/ModeTag';
import StatusTag from '../components/StatusTag';
import ImgWithFallback from '../components/ImgWithFallback';
import { DENSITY_CONFIG, STATUS_CONFIG, stageName } from '../utils/constants';
import { formatDuration, formatTime } from '../utils/format';

const PAGE_SIZE = 10;
const REFRESH_MS = 5000; // 列表存在进行中任务时自动刷新间隔

/** 任务列表页（首页）：卡片流 + 筛选 + 分页 */
export default function JobsList() {
  const navigate = useNavigate();
  const [items, setItems] = useState<JobDetail[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<JobStatus | ''>('');
  const [modeFilter, setModeFilter] = useState<JobMode | ''>('');

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const data = await jobApi.list({
          status: statusFilter,
          mode: modeFilter,
          page,
          page_size: PAGE_SIZE,
        });
        setItems(data.items ?? []);
        setTotal(data.total ?? 0);
      } catch {
        // 错误提示由 client 统一处理
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [statusFilter, modeFilter, page],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // 有进行中/排队/待确认的任务时定时静默刷新
  useEffect(() => {
    const hasActive = items.some((j) =>
      ['pending', 'running', 'waiting_user'].includes(j.status),
    );
    if (!hasActive) return;
    const timer = window.setInterval(() => void load(true), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [items, load]);

  /** 取消任务 */
  const handleCancel = async (id: string) => {
    try {
      await jobApi.cancel(id);
      message.success('已取消任务');
      void load();
    } catch {
      /* 已统一提示 */
    }
  };

  /** 断点重试 */
  const handleRetry = async (job: JobDetail) => {
    try {
      const res = await jobApi.retry(job.biz_id, { strategy: 'resume' });
      message.success('已发起重试');
      navigate(`/jobs/${res?.job_id ?? job.biz_id}`);
    } catch {
      /* 已统一提示 */
    }
  };

  /** 重新生成（restart，产生新任务） */
  const handleRestart = async (job: JobDetail) => {
    try {
      const res = await jobApi.retry(job.biz_id, { strategy: 'restart' });
      message.success('已发起重新生成');
      navigate(`/jobs/${res?.job_id ?? job.biz_id}`);
    } catch {
      /* 已统一提示 */
    }
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {/* 工具栏：新建 + 筛选 */}
      <Flex justify="space-between" align="center" wrap>
        <Link to="/jobs/new">
          <Button type="primary" icon={<PlusOutlined />}>
            新建生成
          </Button>
        </Link>
        <Space>
          <span>筛选：</span>
          <Select<JobStatus | ''>
            value={statusFilter}
            style={{ width: 140 }}
            onChange={(v) => {
              setStatusFilter(v);
              setPage(1);
            }}
            options={[
              { value: '', label: '全部状态' },
              ...Object.entries(STATUS_CONFIG).map(([value, cfg]) => ({
                value: value as JobStatus,
                label: cfg.label,
              })),
            ]}
          />
          <Select<JobMode | ''>
            value={modeFilter}
            style={{ width: 140 }}
            onChange={(v) => {
              setModeFilter(v);
              setPage(1);
            }}
            options={[
              { value: '', label: '全部模式' },
              { value: 'fast', label: '⚡ 极速' },
              { value: 'standard', label: '🚀 标准' },
              { value: 'premium', label: '💎 专业' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
        </Space>
      </Flex>

      {/* 卡片流 */}
      <Spin spinning={loading}>
        {items.length === 0 && !loading ? (
          <Card>
            <Empty description="暂无任务，点击上方「新建生成」开始">
              <Link to="/jobs/new">
                <Button type="primary" icon={<PlusOutlined />}>
                  新建生成
                </Button>
              </Link>
            </Empty>
          </Card>
        ) : (
          <Space direction="vertical" size="small" style={{ width: '100%' }}>
            {items.map((job) => (
              <JobCard
                key={job.biz_id}
                job={job}
                onCancel={handleCancel}
                onRetry={handleRetry}
                onRestart={handleRestart}
              />
            ))}
          </Space>
        )}
      </Spin>

      {/* 分页 */}
      {total > PAGE_SIZE && (
        <Flex justify="center">
          <Pagination
            current={page}
            pageSize={PAGE_SIZE}
            total={total}
            showSizeChanger={false}
            onChange={(p) => setPage(p)}
          />
        </Flex>
      )}
    </Space>
  );
}

/** 单个任务卡片 */
function JobCard({
  job,
  onCancel,
  onRetry,
  onRestart,
}: {
  job: JobDetail;
  onCancel: (id: string) => void;
  onRetry: (job: JobDetail) => void;
  onRestart: (job: JobDetail) => void;
}) {
  const navigate = useNavigate();
  // 展示名与下载文件名一致（后端同一规则生成）；未生成完成时回退文档名
  const title = job.output_filename || job.title || job.document_name || job.biz_id;

  /** 状态附加文案 */
  const statusExtra = (() => {
    switch (job.status) {
      case 'running':
        return `${job.progress ?? 0}%`;
      case 'succeeded':
        return job.quality_score != null ? `质量分 ${job.quality_score}` : undefined;
      case 'failed':
        return job.error_code ?? undefined;
      default:
        return undefined;
    }
  })();

  return (
    <Card className="hover-card" size="small" styles={{ body: { padding: 16 } }}>
      <Flex gap={16} align="flex-start">
        {/* 缩略图 160×90 */}
        <div
          style={{ width: 160, height: 90, flexShrink: 0, borderRadius: 4, overflow: 'hidden', cursor: 'pointer' }}
          onClick={() => navigate(`/jobs/${job.biz_id}`)}
        >
          <ImgWithFallback src={job.thumbnail_url} alt={title} />
        </div>

        {/* 主体信息 */}
        <Flex vertical gap={6} flex={1} style={{ minWidth: 0 }}>
          <Flex justify="space-between" align="center" gap={8}>
            <Link to={`/jobs/${job.biz_id}`} style={{ minWidth: 0 }}>
              <Typography.Text strong ellipsis style={{ fontSize: 15, maxWidth: 480 }}>
                {title}
              </Typography.Text>
            </Link>
            <Space size={4} wrap>
              <ModeTag mode={job.mode} />
              <Tag>{job.target_pages}页</Tag>
              <Tag>密度·{DENSITY_CONFIG[job.density] ?? job.density}</Tag>
            </Space>
          </Flex>

          <Flex justify="space-between" align="center" gap={8} wrap>
            <Space size="middle" wrap>
              <StatusTag status={job.status} extra={statusExtra} />
              {job.status === 'running' && job.current_stage && (
                <Typography.Text type="secondary">
                  正在{stageName(job.current_stage)}
                </Typography.Text>
              )}
              {job.status === 'succeeded' && job.duration_ms != null && (
                <Typography.Text type="secondary">
                  耗时 {formatDuration(job.duration_ms)}
                </Typography.Text>
              )}
            </Space>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {formatTime(job.created_at)}
            </Typography.Text>
          </Flex>

          {/* 失败卡片：直接露出错误码 + 一句话原因 */}
          {job.status === 'failed' && (
            <Typography.Text type="danger" ellipsis>
              {job.error_code} {job.error_message || '生成失败'}
            </Typography.Text>
          )}

          {/* 操作按钮（按状态切换） */}
          <Space size="small" wrap>
            {job.status === 'succeeded' && (
              <>
                <Button size="small" type="primary" onClick={() => navigate(`/jobs/${job.biz_id}`)}>
                  在线预览
                </Button>
                <Button
                  size="small"
                  onClick={async () => {
                    try {
                      const out = await jobApi.output(job.biz_id);
                      window.open(out.pptx_url, '_blank');
                    } catch {
                      /* 已统一提示 */
                    }
                  }}
                >
                  下载PPTX
                </Button>
                <Button size="small" onClick={() => onRestart(job)}>
                  重新生成
                </Button>
              </>
            )}
            {(job.status === 'running' ||
              job.status === 'pending' ||
              job.status === 'waiting_user') && (
              <>
                <Button size="small" type="primary" onClick={() => navigate(`/jobs/${job.biz_id}`)}>
                  查看进度
                </Button>
                <Popconfirm title="确认取消该任务？" onConfirm={() => onCancel(job.biz_id)}>
                  <Button size="small" danger>
                    取消
                  </Button>
                </Popconfirm>
              </>
            )}
            {job.status === 'failed' && (
              <>
                <Button size="small" type="primary" onClick={() => navigate(`/jobs/${job.biz_id}`)}>
                  查看原因
                </Button>
                {job.retryable !== 'no' && (
                  <Button
                    size="small"
                    onClick={() =>
                      job.retryable === 'restart_with_input'
                        ? navigate(`/jobs/${job.biz_id}`)
                        : onRetry(job)
                    }
                  >
                    {job.retryable === 'restart_with_input' ? '更换文档后重试' : '重试'}
                  </Button>
                )}
              </>
            )}
            {job.status === 'canceled' && (
              <Button size="small" onClick={() => onRestart(job)}>
                重新生成
              </Button>
            )}
            <Button size="small" type="text" onClick={() => navigate(`/jobs/${job.biz_id}`)}>
              详情
            </Button>
          </Space>
        </Flex>
      </Flex>
    </Card>
  );
}
