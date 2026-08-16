import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Flex,
  List,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Space,
  Typography,
  message,
} from 'antd';
import {
  CheckCircleFilled,
  CloseCircleFilled,
  LoadingOutlined,
  MinusCircleOutlined,
  WarningFilled,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { jobApi } from '../../api/endpoints';
import type { ContentCard, JobDetail, JobStage, StageStatus } from '../../api/types';
import ImgWithFallback from '../../components/ImgWithFallback';
import { stageName } from '../../utils/constants';
import { estimateSeconds, formatDuration } from '../../utils/format';
import type { StageOverride } from './JobDetail';

/** 进行中视图：左栏阶段清单 + 总进度；右栏页面缩略图流式网格 */
export default function RunningView({
  jobId,
  detail,
  stageOverrides,
  pageCards,
  thumbs,
  onCanceled,
}: {
  jobId: string;
  detail: JobDetail;
  stageOverrides: Record<string, StageOverride>;
  pageCards: Record<number, ContentCard>;
  thumbs: Record<number, string>;
  onCanceled: () => void;
}) {
  const [canceling, setCanceling] = useState(false);
  const [cardPreview, setCardPreview] = useState<{ page: number; card: ContentCard } | null>(
    null,
  );

  // 已耗时：本地每秒滴答（以 started_at 为基准；未开始执行则显示排队中）
  const [nowTick, setNowTick] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const elapsedMs = detail.started_at
    ? Math.max(0, nowTick - dayjs(detail.started_at).valueOf())
    : null;

  // 预计剩余 = 估算总时长 - 已耗时（粗略，仅展示参考）
  const remainText = useMemo(() => {
    if (elapsedMs == null) return null;
    const estMs = estimateSeconds(detail.mode, detail.target_pages, detail.density) * 1000;
    const remain = estMs - elapsedMs;
    if (remain <= 0) return '即将完成';
    return `预计剩余 ~${formatDuration(remain)}`;
  }, [elapsedMs, detail.mode, detail.target_pages, detail.density]);

  /** 合并后端 stages 与 SSE 实时覆盖 */
  const stages: (JobStage & { live?: StageOverride })[] = useMemo(() => {
    const base = detail.stages ?? [];
    return base.map((s) => ({ ...s, live: stageOverrides[s.stage_code] }));
  }, [detail.stages, stageOverrides]);

  /** 已完成页数（有内容卡片或缩略图即视为完成） */
  const donePages = useMemo(() => {
    const set = new Set<number>();
    Object.keys(pageCards).forEach((p) => set.add(Number(p)));
    Object.keys(thumbs).forEach((p) => set.add(Number(p)));
    return set.size;
  }, [pageCards, thumbs]);

  const handleCancel = async () => {
    setCanceling(true);
    try {
      await jobApi.cancel(jobId);
      message.success('已取消任务');
      onCanceled();
    } catch {
      /* 已统一提示 */
    } finally {
      setCanceling(false);
    }
  };

  return (
    <>
    {/* 左右栏强约束布局：左栏固定 320px，右栏占满剩余且不换行 */}
    <Flex gap={16} align="flex-start" wrap={false}>
      <div style={{ width: 320, flexShrink: 0 }}>
        <Card size="small" title="生成进度">
          <Space direction="vertical" style={{ width: '100%' }} size="small">
            <Progress
              percent={detail.progress ?? 0}
              status={detail.status === 'waiting_user' ? 'exception' : 'active'}
              strokeColor={detail.status === 'waiting_user' ? '#faad14' : undefined}
            />
            <Typography.Text type="secondary">
              {detail.status === 'pending'
                ? '排队中，等待执行…'
                : elapsedMs != null
                  ? `已耗时 ${formatDuration(elapsedMs)}${remainText ? ` · ${remainText}` : ''}`
                  : ''}
              {detail.status === 'waiting_user' && '（等待您确认决策）'}
            </Typography.Text>

            {/* 阶段清单 */}
            <List
              size="small"
              dataSource={stages}
              locale={{ emptyText: '等待执行…' }}
              renderItem={(s) => <StageRow stage={s} />}
            />

            <Popconfirm title="确认取消该任务？" onConfirm={handleCancel}>
              <Button danger block loading={canceling}>
                取消任务
              </Button>
            </Popconfirm>
          </Space>
        </Card>
      </div>

      {/* 右栏：页面预览全部集中于此 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <Card
          size="small"
          title={`页面预览（已完成 ${donePages}/${detail.target_pages}）`}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              点击缩略图可查看该页结构化内容
            </Typography.Text>
          }
        >
          <Row gutter={[12, 12]}>
            {Array.from({ length: detail.target_pages }, (_, i) => i + 1).map((page) => {
              const thumb = thumbs[page];
              const card = pageCards[page];
              return (
                <Col key={page} xs={12} md={8} lg={6}>
                  <PageCell
                    page={page}
                    thumbUrl={thumb}
                    card={card}
                    onClick={() => {
                      if (card) setCardPreview({ page, card });
                    }}
                  />
                </Col>
              );
            })}
          </Row>
        </Card>
      </div>
    </Flex>

      {/* 内容卡片弹窗 */}
      <Modal
        open={!!cardPreview}
        title={cardPreview ? `第 ${cardPreview.page} 页 · ${cardPreview.card.title}` : ''}
        footer={null}
        onCancel={() => setCardPreview(null)}
      >
        <ul style={{ paddingLeft: 20 }}>
          {cardPreview?.card.bullets.map((b, i) => (
            <li key={i}>
              <Typography.Text>{b}</Typography.Text>
            </li>
          ))}
        </ul>
      </Modal>
    </>
  );
}

/** 阶段行：状态图标 + 名称 + 分子/分母 + 耗时 */
function StageRow({ stage }: { stage: JobStage & { live?: StageOverride } }) {
  const status: StageStatus = stage.live?.status ?? stage.status;
  const progress = stage.live?.progress;
  const durationMs = stage.duration_ms ?? stage.live?.elapsed_ms;

  const icon = (() => {
    switch (status) {
      case 'success':
        return <CheckCircleFilled style={{ color: '#52c41a' }} />;
      case 'warning':
        return <WarningFilled style={{ color: '#faad14' }} />;
      case 'failed':
        return <CloseCircleFilled style={{ color: '#ff4d4f' }} />;
      case 'running':
        return <LoadingOutlined style={{ color: '#1677ff' }} />;
      case 'skipped':
        return <MinusCircleOutlined style={{ color: '#bfbfbf' }} />;
      default:
        return <MinusCircleOutlined style={{ color: '#d9d9d9' }} />;
    }
  })();

  return (
    <List.Item style={{ paddingInline: 0 }}>
      <Flex justify="space-between" style={{ width: '100%' }} gap={8}>
        <Space size={8}>
          {icon}
          <Typography.Text
            type={status === 'pending' ? 'secondary' : undefined}
            strong={status === 'running'}
          >
            {stageName(stage.stage_code, stage.name)}
          </Typography.Text>
          {status === 'running' && progress && (
            <Typography.Text type="secondary">
              {progress.done}/{progress.total}
            </Typography.Text>
          )}
        </Space>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {status === 'running'
            ? durationMs != null
              ? `${formatDuration(durationMs)}…`
              : ''
            : status === 'success' || status === 'warning' || status === 'failed'
              ? formatDuration(durationMs)
              : ''}
        </Typography.Text>
      </Flex>
    </List.Item>
  );
}

/** 页面格子：缩略图就绪显示图片；否则显示内容卡片占位；再否则显示生成中虚线框 */
function PageCell({
  page,
  thumbUrl,
  card,
  onClick,
}: {
  page: number;
  thumbUrl?: string;
  card?: ContentCard;
  onClick: () => void;
}) {
  if (thumbUrl) {
    return (
      <div style={{ cursor: card ? 'pointer' : 'default' }} onClick={onClick}>
        <div className="thumb-16-9" style={{ borderRadius: 4 }}>
          <ImgWithFallback src={thumbUrl} alt={`第${page}页`} />
        </div>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          p{page}
        </Typography.Text>
      </div>
    );
  }
  if (card) {
    // 内容卡片占位：标题 + 要点
    return (
      <div
        onClick={onClick}
        style={{
          cursor: 'pointer',
          border: '1px solid #e8e8e8',
          borderRadius: 4,
          padding: 8,
          aspectRatio: '16/9',
          overflow: 'hidden',
          background: '#fff',
        }}
      >
        <Typography.Text strong style={{ fontSize: 12 }} ellipsis>
          p{page} {card.title}
        </Typography.Text>
        <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
          {card.bullets.slice(0, 3).map((b, i) => (
            <li key={i} style={{ fontSize: 11, color: '#8c8c8c' }}>
              <Typography.Text type="secondary" style={{ fontSize: 11 }} ellipsis>
                {b}
              </Typography.Text>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  // 未生成占位
  return (
    <div
      style={{
        border: '1px dashed #d9d9d9',
        borderRadius: 4,
        aspectRatio: '16/9',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#bfbfbf',
        fontSize: 12,
      }}
    >
      p{page} 生成中…
    </div>
  );
}
