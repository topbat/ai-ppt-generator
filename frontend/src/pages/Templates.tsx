import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Flex,
  Form,
  Input,
  List,
  Menu,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import {
  AppstoreOutlined,
  CheckCircleOutlined,
  CheckSquareOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  LeftOutlined,
  LoadingOutlined,
  RightOutlined,
  RobotOutlined,
  UploadOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { UploadRequestOption } from 'rc-upload/lib/interface';
import { templateApi } from '../api/endpoints';
import type {
  AiTemplateOptions,
  AiTemplateParams,
  TemplateItem,
} from '../api/types';
import ImgWithFallback from '../components/ImgWithFallback';
import { formatTime } from '../utils/format';

const POLL_MS = 2000;

const isAiTemplate = (t: TemplateItem) => t.name.startsWith('AI');

/** 模板库：左侧分类（个人/AI）+ 右侧封面卡片网格；上传 / 八维 AI 生成 / 批量删除 / 逐页预览 */
export default function Templates() {
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState<'all' | 'personal' | 'ai'>('all');
  // 预览抽屉（含逐页预览）
  const [preview, setPreview] = useState<TemplateItem | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [drawerPage, setDrawerPage] = useState(0);
  // 批量管理
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [batchDeleting, setBatchDeleting] = useState(false);
  // AI 生成模板弹窗（八维参数表单）
  const [aiOpen, setAiOpen] = useState(false);
  const [aiOptions, setAiOptions] = useState<AiTemplateOptions | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiForm] = Form.useForm<AiTemplateParams>();

  const load = useCallback(
    async (silent = false, q?: string) => {
      if (!silent) setLoading(true);
      try {
        const list = await templateApi.list(q ?? keyword);
        setTemplates(list ?? []);
      } catch {
        /* 已统一提示 */
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [keyword],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // 有解析中/缺封面的模板时轮询刷新
  useEffect(() => {
    if (!templates.some((t) => t.status === 'parsing' || !t.thumbnail_url)) return;
    const timer = window.setInterval(() => void load(true), POLL_MS);
    return () => window.clearInterval(timer);
  }, [templates, load]);

  const counts = useMemo(
    () => ({
      all: templates.length,
      ai: templates.filter(isAiTemplate).length,
      personal: templates.filter((t) => !isAiTemplate(t)).length,
    }),
    [templates],
  );
  const shown = useMemo(
    () =>
      templates.filter((t) =>
        category === 'all' ? true : category === 'ai' ? isAiTemplate(t) : !isAiTemplate(t),
      ),
    [templates, category],
  );

  /** 打开 AI 生成弹窗（懒加载八维选项） */
  const openAi = async () => {
    setAiOpen(true);
    if (!aiOptions) {
      try {
        const opts = await templateApi.aiOptions();
        setAiOptions(opts);
        aiForm.setFieldsValue({
          industry: opts.industries[0],
          audience: opts.audiences[1] ?? opts.audiences[0],
          style: opts.styles[0],
          data_content: opts.data_contents[0],
          country: opts.countries[1] ?? opts.countries[0],
          season: opts.seasons[0],
        });
      } catch {
        /* 已统一提示 */
      }
    }
  };

  const handleAiGenerate = async () => {
    setAiLoading(true);
    try {
      const tpl = await templateApi.aiGenerate(aiForm.getFieldsValue());
      message.success(`AI 模板已生成：${tpl?.name ?? ''}（封面图生成中）`);
      setAiOpen(false);
      void load();
    } catch {
      /* 已统一提示 */
    } finally {
      setAiLoading(false);
    }
  };

  /** 上传模板 */
  const uploadTemplate = async (options: UploadRequestOption) => {
    const file = options.file as File;
    try {
      const tpl = await templateApi.upload(file);
      message.success('模板上传成功，正在解析…');
      options.onSuccess?.(tpl);
      void load(true);
    } catch (e) {
      options.onError?.(e as Error);
    }
  };

  /** 单个删除 */
  const handleDelete = async (id: string) => {
    try {
      await templateApi.remove(id);
      message.success('模板已删除');
      setSelectedIds((prev) => prev.filter((x) => x !== id));
      void load();
    } catch {
      /* 已统一提示 */
    }
  };

  /** 批量删除 */
  const handleBatchDelete = async () => {
    if (selectedIds.length === 0) return;
    setBatchDeleting(true);
    try {
      const res = await templateApi.batchRemove(selectedIds);
      message.success(`已批量删除 ${res?.deleted ?? selectedIds.length} 个模板`);
      setSelectedIds([]);
      setBatchMode(false);
      void load();
    } catch {
      /* 已统一提示 */
    } finally {
      setBatchDeleting(false);
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  /** 打开预览抽屉：拉取详情（版式清单 + 逐页预览图） */
  const openPreview = async (tpl: TemplateItem) => {
    setPreview(tpl);
    setDrawerPage(0);
    setPreviewLoading(true);
    try {
      const d = await templateApi.detail(tpl.id);
      setPreview(d);
    } catch {
      /* 已统一提示 */
    } finally {
      setPreviewLoading(false);
    }
  };

  const drawerLayouts = preview?.layouts ?? [];
  const drawerTotal = drawerLayouts.length || preview?.slide_count || 0;
  const drawerImg =
    drawerLayouts[drawerPage]?.thumbnail_url ??
    (drawerPage === 0 ? preview?.thumbnail_url : null);

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {/* 顶部工具栏 */}
      <Flex justify="space-between" align="center" gap={12} wrap>
        <Typography.Title level={4} style={{ margin: 0 }}>
          模板库
        </Typography.Title>
        <Space wrap>
          <Input.Search
            placeholder="搜索模板名称"
            allowClear
            style={{ width: 200 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={(v) => void load(false, v)}
          />
          <Button
            icon={<CheckSquareOutlined />}
            type={batchMode ? 'primary' : 'default'}
            onClick={() => {
              setBatchMode((v) => !v);
              setSelectedIds([]);
            }}
          >
            {batchMode ? '退出批量' : '批量管理'}
          </Button>
          <Button icon={<RobotOutlined />} onClick={() => void openAi()}>
            AI 生成模板
          </Button>
          <Upload
            accept=".pptx"
            showUploadList={false}
            customRequest={uploadTemplate}
            beforeUpload={(file) => {
              if (file.size > 120 * 1024 * 1024) {
                message.error('模板文件不能超过 120MB');
                return Upload.LIST_IGNORE;
              }
              return true;
            }}
          >
            <Button type="primary" icon={<UploadOutlined />}>
              上传模板
            </Button>
          </Upload>
        </Space>
      </Flex>

      {/* 左右栏：分类导航 | 模板网格 */}
      <Row gutter={16} wrap={false}>
        <Col flex="190px">
          <Card size="small" styles={{ body: { padding: 4 } }}>
            <Menu
              mode="inline"
              selectedKeys={[category]}
              onClick={({ key }) => setCategory(key as typeof category)}
              style={{ borderInlineEnd: 'none' }}
              items={[
                { key: 'all', icon: <AppstoreOutlined />, label: `全部模板（${counts.all}）` },
                { key: 'personal', icon: <UserOutlined />, label: `个人模板（${counts.personal}）` },
                { key: 'ai', icon: <RobotOutlined />, label: `AI 模板（${counts.ai}）` },
              ]}
            />
          </Card>
        </Col>

        <Col flex="auto" style={{ minWidth: 0 }}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {/* 批量操作栏 */}
            {batchMode && (
              <Alert
                type="info"
                showIcon={false}
                message={
                  <Flex justify="space-between" align="center">
                    <Space>
                      <Checkbox
                        checked={selectedIds.length === shown.length && shown.length > 0}
                        indeterminate={
                          selectedIds.length > 0 && selectedIds.length < shown.length
                        }
                        onChange={(e) =>
                          setSelectedIds(e.target.checked ? shown.map((t) => t.id) : [])
                        }
                      >
                        全选当前 {shown.length} 个
                      </Checkbox>
                      <Typography.Text type="secondary">
                        已选 {selectedIds.length} 个模板
                      </Typography.Text>
                    </Space>
                    <Popconfirm
                      title={`确认批量删除选中的 ${selectedIds.length} 个模板？`}
                      onConfirm={() => void handleBatchDelete()}
                      disabled={selectedIds.length === 0}
                    >
                      <Button
                        danger
                        icon={<DeleteOutlined />}
                        disabled={selectedIds.length === 0}
                        loading={batchDeleting}
                      >
                        批量删除
                      </Button>
                    </Popconfirm>
                  </Flex>
                }
              />
            )}

            <Spin spinning={loading}>
              {shown.length === 0 && !loading ? (
                <Card>
                  <Empty
                    description={
                      category === 'personal'
                        ? '暂无个人模板：点击右上角「上传模板」添加'
                        : '暂无模板：可上传 .pptx 模板，或用「AI 生成模板」一键生成'
                    }
                  />
                </Card>
              ) : (
                <Row gutter={[16, 16]}>
                  {shown.map((tpl) => {
                    const checked = selectedIds.includes(tpl.id);
                    return (
                      <Col span={6} key={tpl.id}>
                        <Badge.Ribbon
                          text="AI"
                          color="purple"
                          style={{ display: isAiTemplate(tpl) ? undefined : 'none' }}
                        >
                          <Card
                            className="hover-card"
                            size="small"
                            onClick={batchMode ? () => toggleSelect(tpl.id) : undefined}
                            style={{
                              cursor: batchMode ? 'pointer' : undefined,
                              borderColor: checked ? '#1677ff' : undefined,
                              borderWidth: checked ? 2 : 1,
                            }}
                            cover={
                              <div className="thumb-16-9" style={{ position: 'relative' }}>
                                <ImgWithFallback src={tpl.thumbnail_url} alt={tpl.name} />
                                {batchMode && (
                                  <Checkbox
                                    checked={checked}
                                    style={{ position: 'absolute', top: 8, left: 8 }}
                                  />
                                )}
                              </div>
                            }
                            actions={
                              batchMode
                                ? undefined
                                : [
                                    <Button
                                      key="preview"
                                      type="text"
                                      size="small"
                                      icon={<EyeOutlined />}
                                      onClick={() => void openPreview(tpl)}
                                    >
                                      预览
                                    </Button>,
                                    <Button
                                      key="download"
                                      type="text"
                                      size="small"
                                      icon={<DownloadOutlined />}
                                      onClick={() =>
                                        window.open(`/api/v1/templates/${tpl.id}/download`, '_blank')
                                      }
                                    >
                                      下载
                                    </Button>,
                                    <Popconfirm
                                      key="delete"
                                      title="确认删除该模板？"
                                      onConfirm={() => void handleDelete(tpl.id)}
                                    >
                                      <Button
                                        type="text"
                                        size="small"
                                        danger
                                        icon={<DeleteOutlined />}
                                      >
                                        删除
                                      </Button>
                                    </Popconfirm>,
                                  ]
                            }
                          >
                            <Card.Meta
                              title={
                                <Typography.Text
                                  ellipsis
                                  style={{ maxWidth: 190 }}
                                  title={tpl.name}
                                >
                                  {tpl.name}
                                </Typography.Text>
                              }
                              description={
                                <Flex justify="space-between" align="center" gap={8}>
                                  {tpl.status === 'parsing' ? (
                                    <Typography.Text type="secondary">
                                      <LoadingOutlined /> 解析中…
                                    </Typography.Text>
                                  ) : tpl.status === 'failed' ? (
                                    <Typography.Text type="danger" ellipsis>
                                      <CloseCircleOutlined /> 解析失败
                                      {tpl.parse_error ? `（${tpl.parse_error}）` : ''}
                                    </Typography.Text>
                                  ) : (
                                    <Typography.Text type="success">
                                      <CheckCircleOutlined /> {tpl.slide_count ?? '-'} 个版式 ·
                                      可用
                                    </Typography.Text>
                                  )}
                                  <Typography.Text
                                    type="secondary"
                                    style={{ fontSize: 12, flexShrink: 0 }}
                                  >
                                    <ClockCircleOutlined /> {formatTime(tpl.created_at)}
                                  </Typography.Text>
                                </Flex>
                              }
                            />
                          </Card>
                        </Badge.Ribbon>
                      </Col>
                    );
                  })}
                </Row>
              )}
            </Spin>
          </Space>
        </Col>
      </Row>

      {/* AI 生成模板弹窗：八维参数表单 */}
      <Modal
        title="AI 生成模板"
        open={aiOpen}
        onCancel={() => setAiOpen(false)}
        onOk={() => void handleAiGenerate()}
        okText="生成模板"
        confirmLoading={aiLoading}
        width={640}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Text type="secondary">
            按 行业 / 用户群 / 风格 / 数据内容 / 主题 / 关键字 / 国家 / 季节 八个维度生成，
            模板包含 封面 + 目录 + 章节页 + 5~8 个内容页（含图表/表格/时间轴/架构等版式）+ 尾页，
            名称以 AI 为前缀。
          </Typography.Text>
          {aiOptions ? (
            <Form form={aiForm} layout="vertical">
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item label="行业" name="industry">
                    <Select options={aiOptions.industries.map((v) => ({ value: v }))} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="用户群" name="audience">
                    <Select options={aiOptions.audiences.map((v) => ({ value: v }))} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="风格" name="style">
                    <Select options={aiOptions.styles.map((v) => ({ value: v }))} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="数据内容" name="data_content">
                    <Select options={aiOptions.data_contents.map((v) => ({ value: v }))} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="国家" name="country">
                    <Select options={aiOptions.countries.map((v) => ({ value: v }))} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="季节" name="season">
                    <Select options={aiOptions.seasons.map((v) => ({ value: v }))} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="主题（用于封面标题与命名）" name="theme">
                    <Input placeholder="如：智慧园区建设方案" maxLength={20} allowClear />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="关键字（用于封面副标题）" name="keywords">
                    <Input placeholder="如：数字化·降本增效" maxLength={40} allowClear />
                  </Form.Item>
                </Col>
              </Row>
            </Form>
          ) : (
            <Spin />
          )}
        </Space>
      </Modal>

      {/* 预览抽屉：逐页预览 + Design Token + 版式清单 */}
      <Drawer
        title={preview ? `模板预览：${preview.name}` : '模板预览'}
        open={!!preview}
        onClose={() => setPreview(null)}
        width={620}
      >
        <Spin spinning={previewLoading}>
          {preview && (
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              {/* 逐页预览 */}
              <div
                className="thumb-16-9"
                style={{ borderRadius: 4, overflow: 'hidden', background: '#f5f5f5' }}
              >
                <ImgWithFallback
                  src={drawerImg}
                  alt={`第${drawerPage + 1}页`}
                  style={{ objectFit: 'contain', background: '#f5f5f5' }}
                />
              </div>
              <Flex justify="center" align="center" gap={16}>
                <Button
                  size="small"
                  icon={<LeftOutlined />}
                  disabled={drawerPage <= 0}
                  onClick={() => setDrawerPage((p) => Math.max(0, p - 1))}
                >
                  上一页
                </Button>
                <Space size={6}>
                  <Typography.Text strong>
                    {drawerTotal ? `${drawerPage + 1} / ${drawerTotal}` : '-'}
                  </Typography.Text>
                  {drawerLayouts[drawerPage] && (
                    <Tag style={{ marginInlineEnd: 0 }}>
                      {drawerLayouts[drawerPage].slide_type}
                    </Tag>
                  )}
                </Space>
                <Button
                  size="small"
                  disabled={drawerTotal === 0 || drawerPage >= drawerTotal - 1}
                  onClick={() => setDrawerPage((p) => Math.min(drawerTotal - 1, p + 1))}
                >
                  下一页 <RightOutlined />
                </Button>
              </Flex>
              <Typography.Text type="secondary">
                <ClockCircleOutlined /> 创建时间：{formatTime(preview.created_at)}
              </Typography.Text>

              {(preview.missing_layouts?.length ?? 0) > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message={`缺失版式：${preview.missing_layouts!.join('、')}，生成时将使用系统近似版式`}
                />
              )}

              {preview.design_tokens && (
                <Descriptions
                  title="Design Token"
                  size="small"
                  column={1}
                  bordered
                  items={Object.entries(preview.design_tokens)
                    .filter(([, v]) => v != null && typeof v !== 'object')
                    .map(([k, v]) => ({
                      key: k,
                      label: k,
                      children:
                        k === 'primary' ? (
                          <Space>
                            <span
                              style={{
                                display: 'inline-block',
                                width: 14,
                                height: 14,
                                borderRadius: 2,
                                background: String(v),
                                border: '1px solid #d9d9d9',
                              }}
                            />
                            {String(v)}
                          </Space>
                        ) : (
                          String(v)
                        ),
                    }))}
                />
              )}

              <List
                header={
                  <Typography.Text strong>
                    版式清单（{preview.layouts?.length ?? preview.slide_count ?? 0}）
                  </Typography.Text>
                }
                size="small"
                dataSource={preview.layouts ?? []}
                locale={{ emptyText: '暂无版式数据' }}
                renderItem={(layout) => (
                  <List.Item
                    style={{ cursor: 'pointer' }}
                    onClick={() => setDrawerPage(layout.slide_index)}
                  >
                    <Flex justify="space-between" style={{ width: '100%' }}>
                      <Space>
                        <Typography.Text type="secondary">
                          #{layout.slide_index + 1}
                        </Typography.Text>
                        <Tag>{layout.slide_type}</Tag>
                      </Space>
                      <Typography.Text type="secondary">
                        置信度 {(layout.confidence * 100).toFixed(0)}%
                      </Typography.Text>
                    </Flex>
                  </List.Item>
                )}
              />
            </Space>
          )}
        </Spin>
      </Drawer>

    </Space>
  );
}
