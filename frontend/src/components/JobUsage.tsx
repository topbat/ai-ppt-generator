import { useEffect, useState } from 'react';
import { Alert, Button, Card, Descriptions, Empty, Space, Spin, Typography } from 'antd';
import { Link } from 'react-router-dom';
import MetricsAccess, { useMetricsToken } from './MetricsAccess';
import { metricText, metricsFetch } from '../api/metrics';
import type { Engine, ObservationPage, SummaryData } from '../api/metrics';

export default function JobUsage({ jobId, engine }: { jobId: string; engine: Engine }) {
  const token = useMetricsToken();
  const [result, setResult] = useState<{ summary: SummaryData; observations: ObservationPage } | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    setResult(null); setError('');
    if (!token) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    const filter = { engine, job: jobId, days: 90 };
    Promise.all([
      metricsFetch<SummaryData>('summary', token, filter, controller.signal),
      metricsFetch<ObservationPage>('observations', token, { ...filter, page_size: 1 }, controller.signal),
    ]).then(([summary, observations]) => { if (!controller.signal.aborted) setResult({ summary, observations }); })
      .catch(e => { if (!controller.signal.aborted) setError(String(e.message)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, jobId, engine, revision]);
  const summary = result?.summary.summary;
  const traceUrl = result?.observations.items[0]?.trace_url;
  return <Card title="模型消耗" style={{ marginTop: 16, marginBottom: 16 }}
    extra={<Button size="small" disabled={!token} onClick={() => setRevision(n => n + 1)}>刷新</Button>}>
    <Space direction="vertical" style={{ width: '100%' }}>
      <MetricsAccess />
      {error && <Alert type="error" showIcon message={error} />}
      {loading && <Spin />}
      {summary && (summary.count ? <>
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} items={[
          { key: 'count', label: engine === 'pipeline' ? '请求尝试' : 'Agent 运行', children: summary.count },
          { key: 'input', label: '已知输入 Token', children: metricText(summary.input_tokens) },
          { key: 'output', label: '已知输出 Token', children: metricText(summary.output_tokens) },
          { key: 'cost', label: '已知费用（USD）', children: metricText(summary.cost_usd, 6) },
          { key: 'unknown', label: '费用未知记录', children: summary.unknown_cost_count },
          { key: 'partial', label: '部分用量记录', children: summary.partial_usage_count },
          { key: 'retry', label: '重试 / 续跑', children: summary.retries },
        ]} />
        <Space wrap>
          <Link to={`/metrics?engine=${engine}&job=${encodeURIComponent(jobId)}`}>查看阶段与调用明细</Link>
          {traceUrl && <Typography.Link href={traceUrl} target="_blank" rel="noopener noreferrer">打开 Langfuse 追踪</Typography.Link>}
        </Space>
        <Typography.Text type="secondary">最近 90 天的新采集记录；缺失用量不按零计，估算费用以明细标注为准。</Typography.Text>
      </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该任务暂无新采集记录（最近 90 天）" />)}
    </Space>
  </Card>;
}
