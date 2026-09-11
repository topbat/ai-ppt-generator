import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Alert, Button, Card, Col, Input, Row, Select, Space, Statistic, Table, Tag, Typography } from 'antd';
import MetricsAccess, { useMetricsToken } from '../components/MetricsAccess';
import { metricText, metricsFetch } from '../api/metrics';
import type { Engine, MetricSummary, Observation, ObservationPage, RemoteData, SummaryData } from '../api/metrics';

const summaryColumns = [
  { title: '记录数', dataIndex: 'count' },
  { title: '输入 Token（已知）', dataIndex: 'input_tokens', render: (v: number | null) => metricText(v) },
  { title: '输出 Token（已知）', dataIndex: 'output_tokens', render: (v: number | null) => metricText(v) },
  { title: '费用 USD（已知）', dataIndex: 'cost_usd', render: (v: number | null) => metricText(v, 6) },
  { title: '平均耗时', dataIndex: 'avg_duration_ms', render: (v: number | null) => v == null ? '未知' : `${metricText(v / 1000, 2)}s` },
];

export default function LlmMetrics() {
  const [search] = useSearchParams();
  const token = useMetricsToken();
  const [engine, setEngine] = useState<Engine>(search.get('engine') === 'pptmaster' ? 'pptmaster' : 'pipeline');
  const [job, setJob] = useState(search.get('job') || '');
  const [model, setModel] = useState('');
  const [days, setDays] = useState(search.get('job') ? 90 : 7);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<SummaryData | null>(null);
  const [observations, setObservations] = useState<ObservationPage | null>(null);
  const [remote, setRemote] = useState<RemoteData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [remoteLoading, setRemoteLoading] = useState(false);
  const [remoteRevision, setRemoteRevision] = useState(0);
  useEffect(() => {
    setData(null); setError(''); setObservations(null);
    if (!token) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    const filters = { engine, days, model, job };
    Promise.all([
      metricsFetch<SummaryData>('summary', token, filters, controller.signal),
      metricsFetch<ObservationPage>('observations', token, { ...filters, page, page_size: 20 }, controller.signal),
    ]).then(([summary, details]) => { if (!controller.signal.aborted) { setData(summary); setObservations(details); } })
      .catch(e => { if (!controller.signal.aborted) setError(String(e.message)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, engine, days, model, job, page, revision]);
  useEffect(() => {
    setRemote(null);
    if (!token || !remoteRevision) { setRemoteLoading(false); return; }
    const controller = new AbortController();
    setRemoteLoading(true);
    metricsFetch<RemoteData>('remote', token, { engine, days, model, job }, controller.signal)
      .then(r => { if (!controller.signal.aborted) setRemote(r); })
      .catch(e => { if (!controller.signal.aborted) setRemote({ status: 'error', message: String(e.message) }); })
      .finally(() => { if (!controller.signal.aborted) setRemoteLoading(false); });
    return () => controller.abort();
  }, [token, engine, days, model, job, remoteRevision]);
  const s: MetricSummary | undefined = data?.summary;
  const maxCount = Math.max(1, ...(data?.daily.map(d => d.count) || []));
  const columns = [
    { title: '时间', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    { title: '任务 / 阶段', key: 'job', render: (_: unknown, r: Observation) => <>{r.biz_id || '未关联'}<br /><Typography.Text type="secondary">{r.stage}</Typography.Text></> },
    { title: '模型', dataIndex: 'model' },
    { title: '状态', key: 'status', render: (_: unknown, r: Observation) => <Space direction="vertical" size={0}><Tag color={r.status === 'success' ? 'green' : 'red'}>{r.status === 'success' ? '成功' : r.status === 'canceled' ? '取消' : r.status === 'timeout' ? '超时' : '失败'}</Tag>{r.error_type && <Typography.Text type="secondary">{r.error_type}</Typography.Text>}</Space> },
    { title: '输入 / 输出 Token', key: 'tokens', render: (_: unknown, r: Observation) => <>{metricText(r.input_tokens)} / {metricText(r.output_tokens)}{r.usage_source === 'partial' && <Tag color="orange">部分用量</Tag>}</> },
    { title: '费用 USD', key: 'cost', render: (_: unknown, r: Observation) => <>{metricText(r.cost_usd, 6)}{r.cost_source === 'estimated' && <Tag>估算</Tag>}</> },
    { title: '耗时 / 排队', key: 'duration', render: (_: unknown, r: Observation) => `${metricText(r.duration_ms / 1000, 2)}s / ${r.queue_ms}ms` },
    { title: '尝试', key: 'attempt', render: (_: unknown, r: Observation) => <>{r.attempt}{r.fallback && <Tag color="orange">备用</Tag>}</> },
    { title: '追踪', key: 'trace', render: (_: unknown, r: Observation) => r.trace_url ? <a href={r.trace_url} target="_blank" rel="noopener noreferrer">Langfuse</a> : '未配置' },
  ];
  return <Space className="llm-metrics" direction="vertical" size={20} style={{ width: '100%', minWidth: 0 }}>
    <div><Typography.Title level={2}>LLM 用量</Typography.Title><Typography.Paragraph type="secondary">按模型、阶段与任务查看生成消耗。标准请求与 Agent 运行分别统计。</Typography.Paragraph></div>
    <Card><MetricsAccess /></Card>
    <Card>
      <Space wrap>
        <Select aria-label="生成引擎" value={engine} style={{ width: 190 }} onChange={v => { setEngine(v); setPage(1); }} options={[{ value: 'pipeline', label: '标准流水线 · 请求' }, { value: 'pptmaster', label: 'PPT-MASTER · 运行' }]} />
        <Select aria-label="时间范围" value={days} style={{ width: 130 }} onChange={v => { setDays(v); setPage(1); }} options={[1, 7, 30, 90].map(v => ({ value: v, label: `最近 ${v} 天` }))} />
        <Input.Search aria-label="筛选模型" placeholder="模型完整名称" allowClear style={{ width: 210 }} onSearch={v => { setModel(v); setPage(1); }} />
        <Input.Search aria-label="筛选任务" placeholder="任务业务 ID" defaultValue={job} allowClear style={{ width: 240 }} onSearch={v => { setJob(v); setPage(1); }} />
        <Button loading={loading} disabled={!token} onClick={() => setRevision(n => n + 1)}>刷新本地记录</Button>
      </Space>
    </Card>
    {error && <Alert type="error" showIcon message={error} />}
    {token && <>
      <Alert type="info" showIcon message={engine === 'pipeline' ? '记录数代表实际请求尝试，包含失败和重试。' : '记录数代表 CLI 运行次数，不等于内部 LLM 请求数。'} description="仅显示接入后的新记录，时间按 UTC 汇总。未知 Token / 费用不按零计；有缺失时合计仅为已知部分。" />
      <Row gutter={[16, 16]}>
        {[
          [engine === 'pipeline' ? '请求尝试' : 'Agent 运行', s?.count],
          ['成功率 %', s?.success_rate], ['已知输入 Token', s?.input_tokens], ['已知输出 Token', s?.output_tokens],
          ['已知费用 USD', s?.cost_usd], ['P95 耗时 ms', s?.p95_ms],
        ].map(([title, value]) => <Col xs={24} sm={12} lg={8} xl={4} key={String(title)}><Card loading={loading}><Statistic title={title} value={metricText(value as number | null, title === '已知费用 USD' ? 6 : 2)} /></Card></Col>)}
      </Row>
      <Typography.Text type="secondary">用量缺失 {s?.unknown_usage_count ?? '—'} 条 · 部分用量 {s?.partial_usage_count ?? '—'} 条 · 费用未知 {s?.unknown_cost_count ?? '—'} 条 · 费用估算 {s?.estimated_cost_count ?? '—'} 条 · 重试/续跑 {s?.retries ?? '—'} 次 · 备用通道 {s?.fallbacks ?? '—'} 次</Typography.Text>
      <Card title="每日用量趋势（UTC）" loading={loading}>
        <Table rowKey="date" size="small" pagination={false} scroll={{ x: 760 }} dataSource={data?.daily || []} columns={[
          { title: '日期', dataIndex: 'date' },
          { title: '请求 / 运行量', dataIndex: 'count', render: (v: number) => <div style={{ minWidth: 100 }}><div style={{ height: 8, background: '#1677ff', width: `${Math.max(1, v / maxCount * 100)}%`, borderRadius: 3 }} /><span>{v}</span></div> },
          ...summaryColumns.slice(1),
        ]} />
      </Card>
      <Card title="模型对比" loading={loading}><Table rowKey="model" size="small" scroll={{ x: 800 }} dataSource={data?.by_model || []} columns={[{ title: '模型', dataIndex: 'model' }, ...summaryColumns]} /></Card>
      <Card title="阶段消耗" loading={loading}><Table rowKey="stage" size="small" scroll={{ x: 800 }} dataSource={data?.by_stage || []} columns={[{ title: '阶段', dataIndex: 'stage' }, ...summaryColumns]} /></Card>
      <Card title="观测明细"><Table<Observation> rowKey="id" size="small" loading={loading} scroll={{ x: 1400 }} dataSource={observations?.items || []} columns={columns} pagination={{ current: page, pageSize: 20, total: observations?.total || 0, showSizeChanger: false, onChange: setPage }} /></Card>
      <Card title="Langfuse 聚合" extra={<Button loading={remoteLoading} onClick={() => setRemoteRevision(n => n + 1)}>查询 Langfuse</Button>}>
        <Typography.Paragraph type="secondary">此区域独立查询 Langfuse，沿用上方筛选；异步上报可能延迟，不与本地合计相加。远端价格与本地估算配置可能不同。</Typography.Paragraph>
        {remote?.status === 'ok' ? <Table rowKey="providedModelName" size="small" scroll={{ x: 650 }} dataSource={remote.data || []} columns={[
          { title: '模型', dataIndex: 'providedModelName' }, { title: '观测数', dataIndex: 'count_count' },
          { title: 'Token', dataIndex: 'sum_totalTokens' }, { title: '费用 USD', dataIndex: 'sum_totalCost' },
          { title: 'P95（毫秒）', dataIndex: 'p95_latency' },
        ]} /> : <Alert type={remote?.status === 'error' ? 'warning' : 'info'} message={remote?.message || '点击查询以读取 Langfuse 指标。'} />}
      </Card>
    </>}
  </Space>;
}
