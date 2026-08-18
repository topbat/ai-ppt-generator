import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Flex,
  InputNumber,
  Popconfirm,
  Radio,
  Row,
  Select,
  Slider,
  Space,
  Spin,
  Steps,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import {
  CheckCircleOutlined,
  CheckSquareOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  CloseOutlined,
  DeleteOutlined,
  FileTextOutlined,
  InboxOutlined,
  LeftOutlined,
  LoadingOutlined,
  RightOutlined,
  RocketOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import type { UploadRequestOption } from 'rc-upload/lib/interface';
import { documentApi, jobApi, templateApi } from '../api/endpoints';
import type { Density, DocumentItem, JobMode, TemplateItem } from '../api/types';
import ImgWithFallback from '../components/ImgWithFallback';
import { MODE_CONFIG } from '../utils/constants';
import { estimateRangeText, formatTime, suggestPagesRange } from '../utils/format';
import { resolveInitialModel } from '../utils/modelOptions';

const POLL_MS = 2000; // 解析状态轮询间隔

/** 新建生成：三步向导 */
export default function JobNew() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  // Step1 状态
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [tplLoading, setTplLoading] = useState(true);
  const [selectedTpl, setSelectedTpl] = useState<TemplateItem | null>(null);
  // 模板管理（单删/批量删除）
  const [manageMode, setManageMode] = useState(false);
  const [delIds, setDelIds] = useState<string[]>([]);
  const [batchDeleting, setBatchDeleting] = useState(false);
  // 选中模板的逐页预览
  const [tplDetail, setTplDetail] = useState<TemplateItem | null>(null);
  const [previewPage, setPreviewPage] = useState(0);

  // 选中模板后拉取详情（版式清单 + 逐页预览图）
  useEffect(() => {
    setTplDetail(null);
    setPreviewPage(0);
    if (!selectedTpl || selectedTpl.status !== 'ready') return;
    let disposed = false;
    void (async () => {
      try {
        const d = await templateApi.detail(selectedTpl.id);
        if (!disposed) setTplDetail(d);
      } catch {
        /* 已统一提示 */
      }
    })();
    return () => {
      disposed = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTpl?.id, selectedTpl?.status]);

  // Step2 状态
  const [doc, setDoc] = useState<DocumentItem | null>(null);
  const [docUploading, setDocUploading] = useState(false);

  // Step3 状态
  const [pages, setPages] = useState(16);
  const [mode, setMode] = useState<JobMode>('fast');
  const [density, setDensity] = useState<Density>('medium');
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState('');

  useEffect(() => {
    let disposed = false;
    void (async () => {
      try {
        const options = await jobApi.options();
        if (disposed) return;
        setModels(options.models);
        setModel(resolveInitialModel(options.models, options.default_model));
      } catch {
        if (!disposed) {
          setModels([]);
          setModel('');
        }
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  /** 加载模板列表 */
  const loadTemplates = useCallback(async (silent = false) => {
    if (!silent) setTplLoading(true);
    try {
      const list = await templateApi.list();
      setTemplates(list ?? []);
      // 同步已选模板的最新解析状态
      setSelectedTpl((prev) =>
        prev ? (list.find((t) => t.id === prev.id) ?? prev) : prev,
      );
    } catch {
      /* 已统一提示 */
    } finally {
      if (!silent) setTplLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTemplates();
  }, [loadTemplates]);

  // 有解析中的模板时轮询刷新
  useEffect(() => {
    if (!templates.some((t) => t.status === 'parsing')) return;
    const timer = window.setInterval(() => void loadTemplates(true), POLL_MS);
    return () => window.clearInterval(timer);
  }, [templates, loadTemplates]);

  // 文档解析中轮询详情
  useEffect(() => {
    if (!doc || doc.parse_status !== 'parsing') return;
    const timer = window.setInterval(async () => {
      try {
        const d = await documentApi.detail(doc.id);
        setDoc(d);
      } catch {
        /* 轮询失败静默 */
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [doc]);

  // 文档解析完成后，用建议页数初始化目标页数
  const appliedSuggestRef = useRef<string | null>(null);
  useEffect(() => {
    if (!doc || doc.parse_status !== 'ready') return;
    if (appliedSuggestRef.current === doc.id) return;
    const range = suggestPagesRange(doc);
    if (range) {
      appliedSuggestRef.current = doc.id;
      // 取建议区间中位数
      setPages(Math.round((range[0] + range[1]) / 2));
    }
  }, [doc]);

  /** 上传模板 */
  const uploadTemplate = async (options: UploadRequestOption) => {
    const file = options.file as File;
    try {
      const tpl = await templateApi.upload(file);
      message.success('模板上传成功，正在解析…');
      options.onSuccess?.(tpl);
      await loadTemplates(true);
      if (tpl?.id) setSelectedTpl(tpl);
    } catch (e) {
      options.onError?.(e as Error);
    }
  };

  /** 删除单个模板 */
  const deleteTemplate = async (id: string) => {
    try {
      await templateApi.remove(id);
      message.success('模板已删除');
      if (selectedTpl?.id === id) setSelectedTpl(null);
      setDelIds((prev) => prev.filter((x) => x !== id));
      void loadTemplates(true);
    } catch {
      /* 已统一提示 */
    }
  };

  /** 批量删除模板 */
  const batchDeleteTemplates = async () => {
    if (delIds.length === 0) return;
    setBatchDeleting(true);
    try {
      const res = await templateApi.batchRemove(delIds);
      message.success(`已批量删除 ${res?.deleted ?? delIds.length} 个模板`);
      if (selectedTpl && delIds.includes(selectedTpl.id)) setSelectedTpl(null);
      setDelIds([]);
      setManageMode(false);
      void loadTemplates(true);
    } catch {
      /* 已统一提示 */
    } finally {
      setBatchDeleting(false);
    }
  };

  /** 上传文档 */
  const uploadDocument = async (options: UploadRequestOption) => {
    const file = options.file as File;
    setDocUploading(true);
    try {
      const d = await documentApi.upload(file);
      message.success('文档上传成功，正在解析…');
      setDoc(d);
      options.onSuccess?.(d);
    } catch (e) {
      options.onError?.(e as Error);
    } finally {
      setDocUploading(false);
    }
  };

  /** 提交生成任务 */
  const handleSubmit = async () => {
    if (!selectedTpl || !doc) return;
    setSubmitting(true);
    try {
      const res = await jobApi.create({
        template_id: selectedTpl.id,
        document_id: doc.id,
        pages,
        mode,
        density,
        model,
      });
      message.success('任务已提交');
      navigate(`/jobs/${res.job_id}`);
    } catch {
      /* 已统一提示 */
    } finally {
      setSubmitting(false);
    }
  };

  const suggestRange = suggestPagesRange(doc);

  /** 各步的"下一步"可用性 */
  const step1Ok = !!selectedTpl && selectedTpl.status === 'ready';
  const step2Ok = !!doc && doc.parse_status === 'ready';

  return (
    <Card>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Steps
          current={step}
          items={[{ title: '选择模板' }, { title: '上传文档' }, { title: '生成设置' }]}
          style={{ maxWidth: 720, margin: '0 auto' }}
        />

        {/* ---------- Step 1 选择模板 ---------- */}
        {step === 0 && (
          <Spin spinning={tplLoading}>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Row gutter={16}>
                {/* 左栏：模板网格 */}
                <Col span={15}>
                  <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              {/* 模板管理工具栏：单删见卡片右上角，批量删除走管理模式 */}
              <Flex justify="flex-end" align="center" gap={8}>
                {manageMode && (
                  <>
                    <Checkbox
                      checked={delIds.length === templates.length && templates.length > 0}
                      indeterminate={delIds.length > 0 && delIds.length < templates.length}
                      onChange={(e) =>
                        setDelIds(e.target.checked ? templates.map((t) => t.id) : [])
                      }
                    >
                      全选（已选 {delIds.length}）
                    </Checkbox>
                    <Popconfirm
                      title={`确认批量删除选中的 ${delIds.length} 个模板？`}
                      onConfirm={() => void batchDeleteTemplates()}
                      disabled={delIds.length === 0}
                    >
                      <Button
                        danger
                        size="small"
                        icon={<DeleteOutlined />}
                        disabled={delIds.length === 0}
                        loading={batchDeleting}
                      >
                        批量删除
                      </Button>
                    </Popconfirm>
                  </>
                )}
                <Button
                  size="small"
                  icon={manageMode ? <CloseOutlined /> : <CheckSquareOutlined />}
                  onClick={() => {
                    setManageMode((v) => !v);
                    setDelIds([]);
                  }}
                >
                  {manageMode ? '退出管理' : '管理模板'}
                </Button>
              </Flex>
              <Row gutter={[12, 12]}>
                {/* 上传新模板卡片 */}
                <Col span={8}>
                  <Upload.Dragger
                    accept=".pptx"
                    showUploadList={false}
                    customRequest={uploadTemplate}
                    style={{ height: '100%' }}
                    beforeUpload={(file) => {
                      if (file.size > 120 * 1024 * 1024) {
                        message.error('模板文件不能超过 120MB');
                        return Upload.LIST_IGNORE;
                      }
                      return true;
                    }}
                  >
                    <p className="ant-upload-drag-icon">
                      <UploadOutlined />
                    </p>
                    <p className="ant-upload-text">上传新 .pptx 模板</p>
                    <p className="ant-upload-hint">≤50MB</p>
                  </Upload.Dragger>
                </Col>
                {/* 模板卡片 */}
                {templates.map((tpl) => {
                  const selected = selectedTpl?.id === tpl.id;
                  const failed = tpl.status === 'failed';
                  const marked = delIds.includes(tpl.id);
                  return (
                    <Col span={8} key={tpl.id}>
                      <Card
                        hoverable={!failed}
                        size="small"
                        onClick={() => {
                          if (manageMode) {
                            setDelIds((prev) =>
                              marked ? prev.filter((x) => x !== tpl.id) : [...prev, tpl.id],
                            );
                            return;
                          }
                          if (failed) {
                            message.warning('该模板解析失败，请更换模板或删除后重新上传');
                            return;
                          }
                          setSelectedTpl(tpl);
                        }}
                        style={{
                          borderColor: manageMode
                            ? marked
                              ? '#ff4d4f'
                              : undefined
                            : failed
                              ? '#ff4d4f'
                              : selected
                                ? '#1677ff'
                                : undefined,
                          borderWidth: (manageMode ? marked : selected || failed) ? 2 : 1,
                        }}
                        cover={
                          <div className="thumb-16-9" style={{ position: 'relative' }}>
                            <ImgWithFallback src={tpl.thumbnail_url} alt={tpl.name} />
                            {manageMode && (
                              <Checkbox
                                checked={marked}
                                style={{ position: 'absolute', top: 8, left: 8 }}
                              />
                            )}
                            {!manageMode && (
                              <Popconfirm
                                title="确认删除该模板？"
                                onConfirm={(e) => {
                                  e?.stopPropagation();
                                  void deleteTemplate(tpl.id);
                                }}
                                onCancel={(e) => e?.stopPropagation()}
                              >
                                <Button
                                  danger
                                  size="small"
                                  type="text"
                                  icon={<DeleteOutlined />}
                                  style={{
                                    position: 'absolute',
                                    top: 4,
                                    right: 4,
                                    background: 'rgba(255,255,255,0.85)',
                                  }}
                                  onClick={(e) => e.stopPropagation()}
                                />
                              </Popconfirm>
                            )}
                          </div>
                        }
                      >
                        <Card.Meta
                          title={
                            <Space size={4}>
                              <Typography.Text ellipsis style={{ maxWidth: 140 }} title={tpl.name}>
                                {tpl.name}
                              </Typography.Text>
                              {tpl.name.startsWith('AI') && <Tag color="purple">AI</Tag>}
                              {tpl.is_system && <Tag color="default">系统</Tag>}
                            </Space>
                          }
                          description={
                            <Flex justify="space-between" align="center" gap={8}>
                              {tpl.status === 'parsing' ? (
                                <Typography.Text type="secondary">
                                  <LoadingOutlined /> 解析中…
                                </Typography.Text>
                              ) : failed ? (
                                <Typography.Text type="danger">
                                  <CloseCircleOutlined /> 无法解析
                                </Typography.Text>
                              ) : (
                                <Typography.Text type="success">
                                  <CheckCircleOutlined /> {tpl.slide_count ?? '-'} 个版式
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
                    </Col>
                  );
                })}
              </Row>
                  </Space>
                </Col>

                {/* 右栏：选中模板逐页预览 */}
                <Col span={9}>
                  <TplPreviewPanel
                    tpl={selectedTpl}
                    detail={tplDetail}
                    page={previewPage}
                    setPage={setPreviewPage}
                  />
                </Col>
              </Row>

              {/* 已选模板解析摘要 */}
              {selectedTpl && selectedTpl.status === 'ready' && (
                <Alert
                  type="info"
                  showIcon
                  message={
                    <>
                      模板解析结果：识别出 {selectedTpl.slide_count ?? '-'} 个版式页
                      {selectedTpl.design_tokens?.primary && (
                        <>
                          ，主色{' '}
                          <Tag color={String(selectedTpl.design_tokens.primary)}>
                            {String(selectedTpl.design_tokens.primary)}
                          </Tag>
                        </>
                      )}
                      {selectedTpl.design_tokens?.font_title && (
                        <>标题字体 {String(selectedTpl.design_tokens.font_title)}</>
                      )}
                    </>
                  }
                />
              )}
              {selectedTpl &&
                selectedTpl.status === 'ready' &&
                (selectedTpl.missing_layouts?.length ?? 0) > 0 && (
                  <Alert
                    type="warning"
                    showIcon
                    message={`未识别到 ${selectedTpl.missing_layouts!.join('、')} 版式，生成相应页面时将使用系统近似版式`}
                  />
                )}
              {selectedTpl && selectedTpl.status === 'parsing' && (
                <Alert type="info" showIcon message="所选模板正在解析中，请稍候…" />
              )}

              <Flex justify="flex-end">
                <Button type="primary" disabled={!step1Ok} onClick={() => setStep(1)}>
                  下一步：上传文档
                </Button>
              </Flex>
            </Space>
          </Spin>
        )}

        {/* ---------- Step 2 上传文档 ---------- */}
        {step === 1 && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {!doc && (
              <Upload.Dragger
                accept=".pdf,.docx"
                showUploadList={false}
                customRequest={uploadDocument}
                disabled={docUploading}
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
                <p className="ant-upload-text">拖拽或点击上传 PDF / DOCX</p>
                <p className="ant-upload-hint">≤100MB，≤500页</p>
              </Upload.Dragger>
            )}
            {docUploading && <Spin tip="上传中…" />}

            {/* 解析预检结果 */}
            {doc && (
              <Card size="small">
                <Flex justify="space-between" align="flex-start">
                  <Space direction="vertical" size={4}>
                    <Space>
                      <FileTextOutlined />
                      <Typography.Text strong>{doc.name}</Typography.Text>
                      {doc.parse_status === 'ready' && (
                        <Typography.Text type="secondary">
                          {doc.page_count != null && `${doc.page_count}页`}
                          {doc.char_count != null &&
                            ` · ${doc.char_count.toLocaleString()}字`}
                          {doc.table_count != null && ` · ${doc.table_count}表格`}
                          {doc.image_count != null && ` · ${doc.image_count}图片`}
                        </Typography.Text>
                      )}
                    </Space>
                    {doc.parse_status === 'parsing' && (
                      <Typography.Text type="secondary">
                        <LoadingOutlined /> 解析预检中…
                      </Typography.Text>
                    )}
                    {doc.parse_status === 'ready' && (
                      <>
                        <Typography.Text type="success">
                          <CheckCircleOutlined /> 解析预检通过，文本可提取
                        </Typography.Text>
                        {doc.chapter_count != null && (
                          <Typography.Text type="success">
                            <CheckCircleOutlined /> 结构识别：识别出 {doc.chapter_count} 个章节
                          </Typography.Text>
                        )}
                        {suggestRange && (
                          <Typography.Text>
                            建议页数：{suggestRange[0]}～{suggestRange[1]} 页（标准密度）
                          </Typography.Text>
                        )}
                      </>
                    )}
                    {doc.parse_status === 'failed' && (
                      <Typography.Text type="danger">
                        <CloseCircleOutlined /> 解析失败
                        {doc.parse_error ? `（${doc.parse_error}）` : ''}
                        ，请更换文档
                      </Typography.Text>
                    )}
                  </Space>
                  <Button
                    icon={<DeleteOutlined />}
                    size="small"
                    onClick={() => setDoc(null)}
                  >
                    删除
                  </Button>
                </Flex>
              </Card>
            )}

            {doc?.is_scanned && (
              <Alert
                type="warning"
                showIcon
                message="检测到扫描版 PDF：将自动进行 OCR 识别，关键数字将进入事实核验，生成耗时会增加"
              />
            )}
            {!doc?.is_scanned && (
              <Alert
                type="info"
                showIcon
                message="若上传扫描版 PDF：将自动进行 OCR 识别，关键数字将进入事实核验，耗时增加"
              />
            )}

            <Flex justify="space-between">
              <Button onClick={() => setStep(0)}>上一步</Button>
              <Button type="primary" disabled={!step2Ok} onClick={() => setStep(2)}>
                下一步：生成设置
              </Button>
            </Flex>
          </Space>
        )}

        {/* ---------- Step 3 生成设置 ---------- */}
        {step === 2 && (
          <Step3Settings
            pages={pages}
            setPages={setPages}
            mode={mode}
            setMode={setMode}
            density={density}
            setDensity={setDensity}
            models={models}
            model={model}
            setModel={setModel}
            suggestRange={suggestRange}
            submitting={submitting}
            onPrev={() => setStep(1)}
            onSubmit={handleSubmit}
          />
        )}
      </Space>
    </Card>
  );
}

/** Step1 右栏：选中模板逐页预览面板 */
function TplPreviewPanel({
  tpl,
  detail,
  page,
  setPage,
}: {
  tpl: TemplateItem | null;
  detail: TemplateItem | null;
  page: number;
  setPage: (updater: (p: number) => number) => void;
}) {
  const layouts = detail?.layouts ?? [];
  const total = layouts.length || tpl?.slide_count || 0;
  const cur = layouts[page];
  const imgSrc = cur?.thumbnail_url ?? (page === 0 ? tpl?.thumbnail_url : null);

  return (
    <Card
      size="small"
      title="模板预览"
      style={{ position: 'sticky', top: 12 }}
      extra={
        tpl && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {tpl.name}
          </Typography.Text>
        )
      }
    >
      {tpl && tpl.status === 'ready' ? (
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          <div
            className="thumb-16-9"
            style={{ borderRadius: 4, overflow: 'hidden', background: '#f5f5f5' }}
          >
            <ImgWithFallback
              src={imgSrc}
              alt={`第${page + 1}页`}
              style={{ objectFit: 'contain', background: '#f5f5f5' }}
            />
          </div>
          {/* 逐页翻页 */}
          <Flex justify="center" align="center" gap={16}>
            <Button
              size="small"
              icon={<LeftOutlined />}
              disabled={page <= 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              上一页
            </Button>
            <Space size={6}>
              <Typography.Text strong>
                {total ? `${page + 1} / ${total}` : '-'}
              </Typography.Text>
              {cur && <Tag style={{ marginInlineEnd: 0 }}>{cur.slide_type}</Tag>}
            </Space>
            <Button
              size="small"
              disabled={total === 0 || page >= total - 1}
              onClick={() => setPage((p) => Math.min(total - 1, p + 1))}
            >
              下一页 <RightOutlined />
            </Button>
          </Flex>
          {!layouts.some((l) => l.thumbnail_url) && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              <LoadingOutlined /> 逐页预览图生成中，稍后自动可用…
            </Typography.Text>
          )}
          <Flex gap={6} wrap>
            {tpl.name.startsWith('AI') && <Tag color="purple">AI 生成</Tag>}
            <Tag>{tpl.slide_count ?? '-'} 个版式</Tag>
            {tpl.design_tokens?.primary && (
              <Tag>
                主色{' '}
                <span
                  style={{
                    display: 'inline-block',
                    width: 10,
                    height: 10,
                    borderRadius: 2,
                    background: String(tpl.design_tokens.primary),
                    verticalAlign: 'middle',
                  }}
                />
              </Tag>
            )}
          </Flex>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            <ClockCircleOutlined /> 创建于 {formatTime(tpl.created_at)}
          </Typography.Text>
        </Space>
      ) : tpl && tpl.status === 'parsing' ? (
        <Flex justify="center" style={{ padding: '48px 0' }}>
          <Spin tip="模板解析中…" />
        </Flex>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="选择左侧模板后，可在此逐页预览版式"
          style={{ padding: '48px 0' }}
        />
      )}
    </Card>
  );
}

/** Step3：页数 / 模式 / 密度 + 预计耗时 */
function Step3Settings({
  pages,
  setPages,
  mode,
  setMode,
  density,
  setDensity,
  models,
  model,
  setModel,
  suggestRange,
  submitting,
  onPrev,
  onSubmit,
}: {
  pages: number;
  setPages: (v: number) => void;
  mode: JobMode;
  setMode: (v: JobMode) => void;
  density: Density;
  setDensity: (v: Density) => void;
  models: string[];
  model: string;
  setModel: (v: string) => void;
  suggestRange: [number, number] | null;
  submitting: boolean;
  onPrev: () => void;
  onSubmit: () => void;
}) {
  // 预计耗时文案实时计算
  const estText = useMemo(
    () => estimateRangeText(mode, pages, density),
    [mode, pages, density],
  );

  return (
    <Space direction="vertical" size="large" style={{ width: '100%', maxWidth: 780, margin: '0 auto' }}>
      {/* 目标页数 */}
      <div>
        <Typography.Title level={5}>目标页数</Typography.Title>
        <Flex gap={16} align="center">
          <Slider
            min={5}
            max={100}
            value={pages}
            onChange={(v) => setPages(v)}
            style={{ flex: 1 }}
          />
          <InputNumber
            min={5}
            max={100}
            value={pages}
            onChange={(v) => v != null && setPages(v)}
          />
        </Flex>
        {suggestRange && (
          <Typography.Text type="secondary">
            根据资料量推荐 {suggestRange[0]}～{suggestRange[1]} 页
          </Typography.Text>
        )}
      </div>

      <div>
        <Typography.Title level={5}>生成模型</Typography.Title>
        <Select
          value={model || undefined}
          onChange={setModel}
          loading={models.length === 0}
          placeholder="请选择生成模型"
          options={models.map((item) => ({ value: item, label: item }))}
          style={{ width: '100%', maxWidth: 360 }}
        />
        <br />
        <Typography.Text type="secondary">模型选项由后端环境配置提供，并应用于整条生成任务。</Typography.Text>
      </div>

      {/* 生成模式三选卡片 */}
      <div>
        <Typography.Title level={5}>生成模式</Typography.Title>
        <Row gutter={16}>
          {(Object.keys(MODE_CONFIG) as JobMode[]).map((m) => {
            const cfg = MODE_CONFIG[m];
            const selected = mode === m;
            return (
              <Col span={8} key={m}>
                <Card
                  hoverable
                  size="small"
                  onClick={() => setMode(m)}
                  style={{
                    textAlign: 'center',
                    borderColor: selected ? '#1677ff' : undefined,
                    borderWidth: selected ? 2 : 1,
                  }}
                >
                  <Typography.Title level={5} style={{ marginTop: 0 }}>
                    {cfg.icon} {cfg.label}
                    {m === 'fast' && '（默认）'}
                  </Typography.Title>
                  <Typography.Text type="secondary">{cfg.desc}</Typography.Text>
                  <br />
                  {selected && (
                    <Typography.Text strong style={{ color: '#1677ff' }}>
                      {estimateRangeText(m, pages, density)}
                    </Typography.Text>
                  )}
                  {!selected && (
                    <Typography.Text type="secondary">
                      {estimateRangeText(m, pages, density)}
                    </Typography.Text>
                  )}
                </Card>
              </Col>
            );
          })}
        </Row>
        <Typography.Text type="secondary">预计耗时按当前页数与密度动态估算</Typography.Text>
      </div>

      {/* 内容密度 */}
      <div>
        <Typography.Title level={5}>内容密度</Typography.Title>
        <Radio.Group value={density} onChange={(e) => setDensity(e.target.value as Density)}>
          <Radio value="low">紧凑-要点式</Radio>
          <Radio value="medium">标准</Radio>
          <Radio value="high">充实-详实型</Radio>
        </Radio.Group>
      </div>

      <Alert type="info" showIcon message={`当前设置 ${pages} 页 · ${estText}`} />

      <Flex justify="space-between">
        <Button onClick={onPrev}>上一步</Button>
        <Button
          type="primary"
          size="large"
          icon={<RocketOutlined />}
          loading={submitting}
          disabled={!model}
          onClick={onSubmit}
        >
          开始生成
        </Button>
      </Flex>
    </Space>
  );
}
