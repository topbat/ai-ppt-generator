import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button, Card, Flex, Result, Space, Spin, Tag, Typography, message } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { jobApi } from '../../api/endpoints';
import type {
  ContentCard,
  DecisionRequiredEvent,
  JobDetail as JobDetailType,
  StageUpdateEvent,
} from '../../api/types';
import { useJobEvents } from '../../hooks/useJobEvents';
import DecisionModal from '../../components/DecisionModal';
import ModeTag from '../../components/ModeTag';
import StatusTag from '../../components/StatusTag';
import { DENSITY_CONFIG } from '../../utils/constants';
import RunningView from './RunningView';
import SuccessView from './SuccessView';
import FailedView from './FailedView';

/** SSE 阶段覆盖信息（叠加在 detail.stages 上展示） */
export interface StageOverride {
  status: StageUpdateEvent['status'];
  progress: { done: number; total: number } | null;
  elapsed_ms?: number;
}

/** 任务详情页：按状态渲染 进行中 / 成功 / 失败 三种视图 */
export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [detail, setDetail] = useState<JobDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  // SSE 实时状态
  const [stageOverrides, setStageOverrides] = useState<Record<string, StageOverride>>({});
  const [pageCards, setPageCards] = useState<Record<number, ContentCard>>({});
  const [thumbs, setThumbs] = useState<Record<number, string>>({});
  const [decision, setDecision] = useState<DecisionRequiredEvent | null>(null);

  /** 拉取任务详情 */
  const loadDetail = useCallback(async () => {
    if (!id) return;
    try {
      const d = await jobApi.detail(id);
      setDetail(d);
      setNotFound(false);
    } catch {
      setNotFound(true);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    setLoading(true);
    // 切换任务时清空实时状态
    setStageOverrides({});
    setPageCards({});
    setThumbs({});
    setDecision(null);
    void loadDetail();
  }, [loadDetail]);

  // 进行中任务：初始拉一次 slides，恢复刷新前已生成的页面
  const isActive =
    !!detail && ['pending', 'running', 'waiting_user'].includes(detail.status);

  useEffect(() => {
    if (!id || !isActive) return;
    void (async () => {
      try {
        const slides = await jobApi.slides(id);
        const cards: Record<number, ContentCard> = {};
        const th: Record<number, string> = {};
        for (const s of slides ?? []) {
          if (s.content_card) cards[s.page_no] = s.content_card;
          if (s.thumb_url) th[s.page_no] = s.thumb_url;
        }
        setPageCards((prev) => ({ ...cards, ...prev }));
        setThumbs((prev) => ({ ...th, ...prev }));
      } catch {
        // 任务刚创建时 slides 可能 404/为空，忽略
      }
    })();
  }, [id, isActive]);

  // SSE 订阅（仅活跃状态启用）
  const connMode = useJobEvents(id, isActive, {
    onStageUpdate: (e) => {
      setStageOverrides((prev) => ({
        ...prev,
        [e.stage]: { status: e.status, progress: e.progress, elapsed_ms: e.elapsed_ms },
      }));
      // 阶段结束时静默刷新详情（更新总进度/阶段耗时，低频）
      if (e.status !== 'running') void loadDetail();
    },
    onPageDone: (e) => {
      setPageCards((prev) => ({ ...prev, [e.page]: e.content_card }));
    },
    onThumbnailReady: (e) => {
      setThumbs((prev) => ({ ...prev, [e.page]: e.url }));
    },
    onDecisionRequired: (e) => {
      setDecision(e);
      void loadDetail(); // 状态应变为 waiting_user
    },
    onJobDone: () => {
      message.success('生成成功');
      void loadDetail();
    },
    onJobFailed: () => {
      void loadDetail();
    },
    onPollDetail: (d) => {
      // 降级轮询：直接以详情为准
      setDetail(d);
      if (d.status === 'waiting_user') {
        // 轮询模式拿不到决策事件详情，提示用户（决策弹窗依赖 SSE payload）
        // 详情接口若带 decision 信息可在此扩展
      }
    },
  });

  /** 重新生成（restart 新任务） */
  const handleRestart = async () => {
    if (!id) return;
    try {
      const res = await jobApi.retry(id, { strategy: 'restart' });
      message.success('已发起重新生成');
      const newId = res?.job_id ?? id;
      if (newId !== id) navigate(`/jobs/${newId}`);
      else void loadDetail();
    } catch {
      /* 已统一提示 */
    }
  };

  /** 一键美化（以本任务为父创建新版本，只跑渲染+视觉优化） */
  const handleBeautify = async () => {
    if (!id) return;
    try {
      const res = await jobApi.beautify(id);
      message.success('已发起一键美化，正在跳转新版本任务');
      if (res?.job_id) navigate(`/jobs/${res.job_id}`);
    } catch {
      /* 已统一提示 */
    }
  };

  const headerTitle = useMemo(
    // 展示名与下载文件名一致；未生成完成时回退文档名
    () =>
      detail?.output_filename ||
      detail?.title ||
      detail?.document_name ||
      detail?.biz_id ||
      id ||
      '',
    [detail, id],
  );

  if (loading) {
    return (
      <Flex justify="center" style={{ paddingTop: 120 }}>
        <Spin size="large" tip="加载中…" />
      </Flex>
    );
  }

  if (notFound || !detail || !id) {
    return (
      <Result
        status="404"
        title="任务不存在"
        subTitle="该任务可能已被删除"
        extra={
          <Link to="/jobs">
            <Button type="primary">返回任务列表</Button>
          </Link>
        }
      />
    );
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {/* 页头 */}
      <Card size="small">
        <Flex justify="space-between" align="center" wrap gap={8}>
          <Space size="middle">
            <Link to="/jobs">
              <Button type="text" icon={<ArrowLeftOutlined />}>
                返回列表
              </Button>
            </Link>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {headerTitle}
            </Typography.Title>
            <StatusTag
              status={detail.status}
              extra={
                detail.status === 'succeeded' && detail.quality_score != null
                  ? `· 质量分 ${detail.quality_score}` +
                    (detail.visual_score != null ? ` · 视觉分 ${detail.visual_score}` : '')
                  : undefined
              }
            />
          </Space>
          <Space size={4} wrap>
            <ModeTag mode={detail.mode} />
            <Tag>{detail.target_pages}页</Tag>
            <Tag>密度·{DENSITY_CONFIG[detail.density] ?? detail.density}</Tag>
            {detail.template_name && <Tag>模板：{detail.template_name}</Tag>}
            <Typography.Text type="secondary" copyable={{ text: detail.biz_id }}>
              job: {detail.biz_id}
            </Typography.Text>
            {connMode === 'polling' && isActive && (
              <Tag color="orange">已降级为轮询模式</Tag>
            )}
          </Space>
        </Flex>
      </Card>

      {/* 按状态分发视图 */}
      {isActive && (
        <RunningView
          jobId={id}
          detail={detail}
          stageOverrides={stageOverrides}
          pageCards={pageCards}
          thumbs={thumbs}
          onCanceled={() => void loadDetail()}
        />
      )}
      {detail.status === 'succeeded' && (
        <SuccessView
          jobId={id}
          detail={detail}
          onRestart={handleRestart}
          onBeautify={handleBeautify}
        />
      )}
      {detail.status === 'failed' && (
        <FailedView jobId={id} detail={detail} onRefresh={() => void loadDetail()} />
      )}
      {detail.status === 'canceled' && (
        <Card>
          <Result
            status="info"
            title="任务已取消"
            subTitle={`任务 ${detail.biz_id} 已被取消，可重新生成`}
            extra={
              <Button type="primary" onClick={handleRestart}>
                重新生成
              </Button>
            }
          />
        </Card>
      )}

      {/* 决策阻塞弹窗 */}
      <DecisionModal
        jobId={id}
        decision={decision}
        onResolved={() => {
          setDecision(null);
          void loadDetail();
        }}
      />
    </Space>
  );
}
