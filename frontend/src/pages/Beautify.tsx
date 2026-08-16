import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Flex,
  List,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import {
  DownloadOutlined,
  InboxOutlined,
  LoadingOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { UploadRequestOption } from 'rc-upload/lib/interface';
import { beautifyApi } from '../api/endpoints';
import type { BeautifyRecordItem, BeautifyResult } from '../api/types';
import { formatTime } from '../utils/format';

const PAGE_SIZE = 10;

/** 视觉分配色 */
function visualColor(score: number): string {
  if (score >= 90) return '#52c41a';
  if (score >= 75) return '#1677ff';
  if (score >= 60) return '#faad14';
  return '#ff4d4f';
}

/** 文件大小格式化 */
function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return '-';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** PPT 美化页：上方上传美化（产物存 MinIO），下方美化记录列表（倒序） */
export default function Beautify() {
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState<BeautifyResult | null>(null);
  // 记录列表
  const [records, setRecords] = useState<BeautifyRecordItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [listLoading, setListLoading] = useState(true);

  const loadList = useCallback(async (p: number) => {
    setListLoading(true);
    try {
      const data = await beautifyApi.list({ page: p, page_size: PAGE_SIZE });
      setRecords(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch {
      /* 错误提示由 client 统一处理 */
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadList(page);
  }, [page, loadList]);

  const handleUpload = async (options: UploadRequestOption) => {
    const file = options.file as File;
    setProcessing(true);
    setResult(null);
    try {
      const r = await beautifyApi.upload(file);
      setResult(r);
      options.onSuccess?.(r);
      message.success(`美化完成：视觉分 ${r.score_before} → ${r.score_after}`);
      // 新记录排在第一页最前面，回到第一页刷新
      setPage(1);
      void loadList(1);
    } catch (e) {
      options.onError?.(e as Error);
    } finally {
      setProcessing(false);
    }
  };

  const worstPages = (result?.pages ?? [])
    .filter((p) => (p.deductions?.length ?? 0) > 0)
    .sort((a, b) => a.score - b.score)
    .slice(0, 5);

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {/* 上：上传美化 */}
      <Card title="PPT 专业级视觉美化">
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Text type="secondary">
            上传任意 .pptx 文件，系统将进行九维视觉评分（布局/对齐/字体/间距/色彩/层级/密度/图片/一致性），
            并执行确定性美化：对齐锚线吸附、8pt 网格吸附、纯黑正文替换为专业深灰。
            只做吸附级微调，绝不改动内容与版式。美化后的文件自动保存，可随时在下方列表中下载。
          </Typography.Text>

          <Upload.Dragger
            accept=".pptx"
            showUploadList={false}
            customRequest={handleUpload}
            disabled={processing}
            beforeUpload={(file) => {
              if (file.size > 60 * 1024 * 1024) {
                message.error('文件不能超过 60MB');
                return Upload.LIST_IGNORE;
              }
              return true;
            }}
          >
            <p className="ant-upload-drag-icon">
              {processing ? <LoadingOutlined /> : <InboxOutlined />}
            </p>
            <p className="ant-upload-text">
              {processing ? '正在评分与美化…' : '拖拽或点击上传 .pptx 文件'}
            </p>
            <p className="ant-upload-hint">≤60MB，处理约 2~5 秒</p>
          </Upload.Dragger>

          {result && (
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Row gutter={16}>
                <Col span={6}>
                  <Statistic
                    title="美化前视觉分"
                    value={result.score_before}
                    valueStyle={{ color: visualColor(result.score_before) }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="美化后视觉分"
                    value={result.score_after}
                    valueStyle={{ color: visualColor(result.score_after) }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic title="页数" value={result.total_pages} />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="修复处数"
                    value={
                      result.fixes.aligned +
                      result.fixes.spacing_snapped +
                      result.fixes.black_text_fixed
                    }
                  />
                </Col>
              </Row>

              <Flex gap={6} wrap>
                <Tag>对齐吸附 {result.fixes.aligned} 处</Tag>
                <Tag>8pt 网格吸附 {result.fixes.spacing_snapped} 处</Tag>
                <Tag>纯黑正文修复 {result.fixes.black_text_fixed} 处</Tag>
              </Flex>

              {/* 九维条形图 */}
              <Card size="small" title="九维视觉评分">
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  {Object.entries(result.dimensions ?? {}).map(([k, d]) => (
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
              </Card>

              {worstPages.length > 0 && (
                <Card size="small" title="待改进页面（评分最低 5 页）">
                  <List
                    size="small"
                    dataSource={worstPages}
                    renderItem={(p) => (
                      <List.Item>
                        <Space direction="vertical" size={0} style={{ width: '100%' }}>
                          <Tag color={visualColor(p.score)}>
                            第{p.page}页 · {p.score}分
                          </Tag>
                          {(p.deductions ?? []).slice(0, 3).map((d, i) => (
                            <Typography.Text key={i} type="secondary" style={{ fontSize: 12 }}>
                              [-{d.points}] {d.detail}
                            </Typography.Text>
                          ))}
                        </Space>
                      </List.Item>
                    )}
                  />
                </Card>
              )}

              <Flex justify="flex-end">
                <Button
                  type="primary"
                  icon={<DownloadOutlined />}
                  onClick={() => window.open(result.download_url, '_blank')}
                >
                  下载美化后文件（{result.filename}）
                </Button>
              </Flex>
            </Space>
          )}
        </Space>
      </Card>

      {/* 下：美化记录列表（倒序） */}
      <Card
        title="美化记录"
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => void loadList(page)}>
            刷新
          </Button>
        }
      >
        <Table<BeautifyRecordItem>
          rowKey="beautify_id"
          loading={listLoading}
          dataSource={records}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total,
            showSizeChanger: false,
            onChange: (p) => setPage(p),
          }}
          locale={{ emptyText: '暂无美化记录，上传 .pptx 文件开始美化' }}
          columns={[
            {
              title: '文件名',
              dataIndex: 'filename',
              ellipsis: true,
              render: (name: string, r) => (
                <Typography.Text ellipsis title={`原文件：${r.source_name}`}>
                  {name}
                </Typography.Text>
              ),
            },
            {
              title: '视觉分',
              width: 140,
              render: (_, r) =>
                r.score_before != null && r.score_after != null ? (
                  <Space size={4}>
                    <Typography.Text type="secondary">{r.score_before}</Typography.Text>
                    <Typography.Text type="secondary">→</Typography.Text>
                    <Typography.Text strong style={{ color: visualColor(r.score_after) }}>
                      {r.score_after}
                    </Typography.Text>
                  </Space>
                ) : (
                  '-'
                ),
            },
            {
              title: '页数',
              dataIndex: 'total_pages',
              width: 80,
              render: (v: number | null) => (v != null ? `${v}页` : '-'),
            },
            {
              title: '修复处数',
              dataIndex: 'fix_count',
              width: 90,
              render: (v: number | undefined) => v ?? '-',
            },
            {
              title: '大小',
              dataIndex: 'file_size',
              width: 90,
              render: (v: number) => formatSize(v),
            },
            {
              title: '美化时间',
              dataIndex: 'created_at',
              width: 150,
              render: (v: string | null) => formatTime(v),
            },
            {
              title: '操作',
              width: 110,
              render: (_, r) => (
                <Button
                  size="small"
                  type="primary"
                  icon={<DownloadOutlined />}
                  onClick={() => window.open(r.download_url, '_blank')}
                >
                  下载
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  );
}
