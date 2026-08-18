import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Flex,
  List,
  Progress,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  ClockCircleOutlined,
  DownloadOutlined,
  FileTextOutlined,
  HighlightOutlined,
  LeftOutlined,
  RedoOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { jobApi } from '../../api/endpoints';
import type {
  JobDetail,
  JobOutput,
  QualityReport,
  SlideItem,
} from '../../api/types';
import ImgWithFallback from '../../components/ImgWithFallback';
import { stageName } from '../../utils/constants';
import { formatDuration, formatTimeMs } from '../../utils/format';

/** 视觉分配色：≥90 绿 / ≥75 蓝 / ≥60 橙 / 其余红 */
function visualColor(score: number): string {
  if (score >= 90) return '#52c41a';
  if (score >= 75) return '#1677ff';
  if (score >= 60) return '#faad14';
  return '#ff4d4f';
}

/** 成功视图：操作栏 + 页码导航 + 大图翻页预览 + 报告/耗时抽屉 */
export default function SuccessView({
  jobId,
  detail,
  onRestart,
  onBeautify,
}: {
  jobId: string;
  detail: JobDetail;
  onRestart: () => void;
  onBeautify?: () => void;
}) {
  const [slides, setSlides] = useState<SlideItem[]>([]);
  const [slidesLoading, setSlidesLoading] = useState(true);
  const [output, setOutput] = useState<JobOutput | null>(null);
  const [current, setCurrent] = useState(1); // 当前页码（1 基）
  const [reportOpen, setReportOpen] = useState(false);
  const [stagesOpen, setStagesOpen] = useState(false);
  const [report, setReport] = useState<QualityReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  // 加载页面清单与产物链接
  useEffect(() => {
    let disposed = false;
    void (async () => {
      setSlidesLoading(true);
      try {
        const [s, o] = await Promise.all([
          jobApi.slides(jobId),
          jobApi.output(jobId).catch(() => null),
        ]);
        if (disposed) return;
        setSlides((s ?? []).slice().sort((a, b) => a.page_no - b.page_no));
        setOutput(o);
      } catch {
        /* 已统一提示 */
      } finally {
        if (!disposed) setSlidesLoading(false);
      }
    })();
    return () => {
      disposed = true;
    };
  }, [jobId]);

  const currentSlide = useMemo(
    () => slides.find((s) => s.page_no === current) ?? null,
    [slides, current],
  );
  const totalPages = slides.length || detail.target_pages;

  /** 打开质检报告抽屉（懒加载） */
  const openReport = useCallback(async () => {
    setReportOpen(true);
    if (report) return;
    setReportLoading(true);
    try {
      const r = await jobApi.report(jobId);
      setReport(r);
    } catch {
      /* 已统一提示 */
    } finally {
      setReportLoading(false);
    }
  }, [jobId, report]);

  const totalText = useMemo(() => {
    const parts: string[] = [];
    if (detail.queue_ms != null) parts.push(`排队${formatDuration(detail.queue_ms)}`);
    if (detail.duration_ms != null) parts.push(`执行${formatDuration(detail.duration_ms)}`);
    const total = (detail.queue_ms ?? 0) + (detail.duration_ms ?? 0);
    if (total > 0) return `总耗时 ${formatDuration(total)}（${parts.join('+')}）`;
    return null;
  }, [detail.queue_ms, detail.duration_ms]);

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {/* 顶部操作栏 */}
      <Card size="small">
        <Flex justify="space-between" align="center" wrap gap={8}>
          <Space wrap>
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              disabled={!output?.pptx_url}
              onClick={() => output?.pptx_url && window.open(output.pptx_url, '_blank')}
            >
              下载PPTX
            </Button>
            <Button
              icon={<DownloadOutlined />}
              disabled={!output?.pdf_url}
              onClick={() => output?.pdf_url && window.open(output.pdf_url!, '_blank')}
            >
              下载PDF
            </Button>
            <Button icon={<RedoOutlined />} onClick={onRestart}>
              重新生成
            </Button>
            {onBeautify && (
              <Button icon={<HighlightOutlined />} onClick={onBeautify}>
                一键美化
              </Button>
            )}
            <Button icon={<FileTextOutlined />} onClick={() => void openReport()}>
              质检报告
            </Button>
            <Button icon={<ClockCircleOutlined />} onClick={() => setStagesOpen(true)}>
              阶段耗时
            </Button>
          </Space>
          {totalText && <Typography.Text type="secondary">{totalText}</Typography.Text>}
        </Flex>
      </Card>

      <Row gutter={16}>
        {/* 左侧页码导航 */}
        <Col flex="240px">
          <Card size="small" title={`页面导航（${totalPages}页）`} styles={{ body: { padding: 0, maxHeight: 560, overflowY: 'auto' } }}>
            <Spin spinning={slidesLoading}>
              <List
                size="small"
                dataSource={slides}
                locale={{ emptyText: <Empty description="页面数据未就绪" /> }}
                renderItem={(s) => (
                  <List.Item
                    onClick={() => setCurrent(s.page_no)}
                    style={{
                      cursor: 'pointer',
                      paddingInline: 12,
                      background: s.page_no === current ? '#e6f4ff' : undefined,
                    }}
                  >
                    <Space size={8}>
                      <Typography.Text type="secondary">p{s.page_no}</Typography.Text>
                      <Typography.Text ellipsis style={{ maxWidth: 140 }}>
                        {s.title || s.slide_type}
                      </Typography.Text>
                    </Space>
                  </List.Item>
                )}
              />
            </Spin>
          </Card>
        </Col>

        {/* 右侧大图预览 */}
        <Col flex="auto">
          <Card size="small">
            <Space direction="vertical" style={{ width: '100%' }} size="small">
              <div className="thumb-16-9" style={{ borderRadius: 4, background: '#fafafa' }}>
                <ImgWithFallback
                  src={currentSlide?.image_url ?? currentSlide?.thumb_url}
                  alt={`第${current}页`}
                  style={{ objectFit: 'contain', background: '#fafafa' }}
                />
              </div>

              {/* 翻页控制 */}
              <Flex justify="center" align="center" gap={24}>
                <Button
                  icon={<LeftOutlined />}
                  disabled={current <= 1}
                  onClick={() => setCurrent((c) => Math.max(1, c - 1))}
                >
                  上一页
                </Button>
                <Typography.Text strong>
                  {current} / {totalPages}
                </Typography.Text>
                <Button
                  disabled={current >= totalPages}
                  onClick={() => setCurrent((c) => Math.min(totalPages, c + 1))}
                >
                  下一页 <RightOutlined />
                </Button>
              </Flex>

              {/* 本页信息栏：版式 / 来源页码 / 降级原因 */}
              {currentSlide && (
                <>
                  <Flex gap={8} wrap align="center">
                    <Typography.Text type="secondary">本页信息：</Typography.Text>
                    <Tag>版式 {currentSlide.slide_type}</Tag>
                    {currentSlide.visual_score != null && (
                      <Tag color={visualColor(currentSlide.visual_score)}>
                        视觉分 {currentSlide.visual_score}
                      </Tag>
                    )}
                    {(currentSlide.sources ?? []).map((src, i) => (
                      <Tag key={i}>
                        来源：{src.document_name ?? '文档'} p{src.pages.join(', p')}
                      </Tag>
                    ))}
                  </Flex>
                  {currentSlide.degrade_reason && (
                    <Alert
                      type="warning"
                      showIcon
                      message={`本页曾自动降级处理：${currentSlide.degrade_reason}`}
                    />
                  )}
                </>
              )}
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 阶段耗时抽屉 */}
      <Drawer
        title="阶段耗时"
        open={stagesOpen}
        onClose={() => setStagesOpen(false)}
        width={520}
      >
        <Table
          size="small"
          rowKey={(r) => `${r.stage_code}-${r.attempt ?? 1}`}
          pagination={false}
          dataSource={detail.stages ?? []}
          columns={[
            {
              title: '阶段',
              dataIndex: 'stage_code',
              render: (_: string, r) => stageName(r.stage_code, r.name),
            },
            {
              title: '开始',
              dataIndex: 'started_at',
              render: (v: string | null) => formatTimeMs(v),
            },
            {
              title: '结束',
              dataIndex: 'finished_at',
              render: (v: string | null) => formatTimeMs(v),
            },
            {
              title: '耗时',
              dataIndex: 'duration_ms',
              align: 'right' as const,
              render: (v: number | null) => formatDuration(v),
            },
          ]}
        />
        <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>
          排队 {formatDuration(detail.queue_ms)} + 执行 {formatDuration(detail.duration_ms)} = 总计{' '}
          {formatDuration((detail.queue_ms ?? 0) + (detail.duration_ms ?? 0))}
        </Typography.Paragraph>
      </Drawer>

      {/* 质检报告抽屉 */}
      <Drawer
        title="质检报告"
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        width={560}
      >
        <Spin spinning={reportLoading}>
          {report ? (
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Row gutter={16}>
                <Col span={6}>
                  <Statistic title="质量分" value={report.score ?? detail.quality_score ?? '-'} />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="视觉分"
                    value={report.visual?.score ?? detail.visual_score ?? '-'}
                    valueStyle={
                      report.visual?.score != null
                        ? { color: visualColor(report.visual.score) }
                        : undefined
                    }
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="错误"
                    value={report.errors ?? 0}
                    valueStyle={{ color: (report.errors ?? 0) > 0 ? '#ff4d4f' : undefined }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="警告"
                    value={report.warnings ?? 0}
                    valueStyle={{ color: (report.warnings ?? 0) > 0 ? '#faad14' : undefined }}
                  />
                </Col>
              </Row>

              {/* 视觉九维条形图（visual_score 明细） */}
              {report.visual && (
                <Card
                  size="small"
                  title={
                    <Space size={8}>
                      <Typography.Text strong>视觉九维评分</Typography.Text>
                      {report.visual.score_before != null &&
                        report.visual.score_before !== report.visual.score && (
                          <Tag color="green">
                            美化 {report.visual.score_before} → {report.visual.score}
                          </Tag>
                        )}
                      {(report.visual.rounds ?? 0) > 0 && (
                        <Tag>闭环 {report.visual.rounds} 轮</Tag>
                      )}
                    </Space>
                  }
                >
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    {Object.entries(report.visual.dimensions ?? {}).map(([k, d]) => (
                      <Flex key={k} align="center" gap={8}>
                        <Typography.Text
                          type="secondary"
                          style={{ width: 56, flexShrink: 0, fontSize: 12 }}
                        >
                          {d.name}
                        </Typography.Text>
                        <Progress
                          percent={Math.round((d.score / d.max) * 100)}
                          size="small"
                          strokeColor={visualColor((d.score / d.max) * 100)}
                          format={() => `${d.score}/${d.max}`}
                          style={{ flex: 1, margin: 0 }}
                        />
                      </Flex>
                    ))}
                  </Space>
                  {(report.visual.pages?.length ?? 0) > 0 && (
                    <>
                      <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>
                        逐页评分
                      </Typography.Text>
                      <Flex wrap gap={4} style={{ marginTop: 8 }}>
                        {report.visual.pages!.map((p) => (
                          <Tag
                            key={p.page}
                            color={visualColor(p.score)}
                            title={(p.deductions ?? [])
                              .map((d) => `[-${d.points}] ${d.detail}`)
                              .join('\n')}
                          >
                            P{p.page}·{p.score}
                          </Tag>
                        ))}
                      </Flex>
                    </>
                  )}
                </Card>
              )}

              {report.composition && (
                <Card size="small" title="构图与整册节奏">
                  <Row gutter={[12, 12]}>
                    <Col span={8}>
                      <Statistic title="节奏分" value={report.composition.deck_rhythm_score} />
                    </Col>
                    <Col span={8}>
                      <Statistic
                        title="主导布局占比"
                        value={Math.round(report.composition.dominant_family_ratio * 100)}
                        suffix="%"
                      />
                    </Col>
                    <Col span={8}>
                      <Statistic
                        title="关键页应用"
                        value={report.composition.key_slides_applied.length}
                        suffix={`/ ${report.composition.key_slides_selected.length}`}
                      />
                    </Col>
                  </Row>
                  <Descriptions
                    size="small"
                    column={1}
                    style={{ marginTop: 12 }}
                    items={[
                      {
                        key: 'guard',
                        label: '硬约束',
                        children: `边距 ${report.composition.margin_violations} · 字体 ${report.composition.typography_violations}`,
                      },
                      {
                        key: 'repeat',
                        label: '相邻重复',
                        children: report.composition.adjacent_fingerprint_duplicates,
                      },
                      {
                        key: 'fallback',
                        label: '关键页回退',
                        children:
                          report.composition.key_slides_fallback.length > 0
                            ? report.composition.key_slides_fallback.map((page) => `P${page}`).join('、')
                            : '无',
                      },
                    ]}
                  />
                </Card>
              )}

              {report.checks && Object.keys(report.checks).length > 0 && (
                <Descriptions
                  title="分项检查"
                  size="small"
                  column={1}
                  bordered
                  items={Object.entries(report.checks).map(([k, v]) => ({
                    key: k,
                    label: k,
                    children:
                      typeof v === 'object' ? JSON.stringify(v) : String(v),
                  }))}
                />
              )}

              {(report.issues?.length ?? 0) > 0 ? (
                <List
                  header={<Typography.Text strong>问题清单</Typography.Text>}
                  size="small"
                  dataSource={report.issues}
                  renderItem={(issue) => (
                    <List.Item>
                      <Space direction="vertical" size={0}>
                        <Space size={4}>
                          {issue.page != null && <Tag>第{issue.page}页</Tag>}
                          {issue.severity && (
                            <Tag
                              color={
                                issue.severity === 'blocker' || issue.severity === 'error'
                                  ? 'red'
                                  : issue.severity === 'warning'
                                    ? 'orange'
                                    : 'default'
                              }
                            >
                              {issue.severity}
                            </Tag>
                          )}
                          {issue.issue_type && <Tag>{issue.issue_type}</Tag>}
                        </Space>
                        <Typography.Text>{issue.message ?? ''}</Typography.Text>
                        {issue.suggestion && (
                          <Typography.Text type="secondary">
                            建议：{issue.suggestion}
                          </Typography.Text>
                        )}
                      </Space>
                    </List.Item>
                  )}
                />
              ) : (
                <Alert type="success" showIcon message="未发现问题" />
              )}
            </Space>
          ) : (
            !reportLoading && <Empty description="暂无报告数据" />
          )}
        </Spin>
      </Drawer>
    </Space>
  );
}
