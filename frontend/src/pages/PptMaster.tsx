import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  Descriptions,
  Drawer,
  Dropdown,
  Empty,
  Flex,
  Form,
  Image,
  Input,
  InputNumber,
  Popconfirm,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from 'antd';
import type { UploadFile } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  DeleteOutlined,
  DownOutlined,
  DownloadOutlined,
  ExportOutlined,
  EyeOutlined,
  InboxOutlined,
  ReloadOutlined,
  RocketOutlined,
  StopOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import { pptmasterApi } from '../api/endpoints';
import type {
  OptionItem,
  PptMasterJob,
  PptMasterJobDetail,
  PptMasterOptions,
  PptMasterOutput,
  PptMasterStatus,
} from '../api/types';
import { formatDuration, formatTime } from '../utils/format';
import {
  isTemplateStyleLocked,
  resolveInitialModel,
  resolvePptMasterStyle,
  stageTooltipText,
} from '../utils/modelOptions';

const PAGE_SIZE = 10;
const POLL_MS = 3000; // 列表 / 详情存在进行中任务时的轮询间隔
const TICK_MS = 1000; // 运行中任务「实时耗时」刷新间隔

/** 任务状态展示配置（Tag 颜色 + 文案） */
const PM_STATUS: Record<PptMasterStatus, { label: string; color: string }> = {
  pending: { label: '排队中', color: 'default' },
  running: { label: '生成中', color: 'processing' },
  succeeded: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
  canceled: { label: '已取消', color: 'default' },
};

/** 产物类型 → 中文名 */
/** 列表内使用的 Agent 短标签（完整说明见 options.agents[].label） */
const AGENT_SHORT: Record<string, string> = { claude: 'Claude Code', codex: 'Codex', mock: 'Mock' };

const OUTPUT_KIND_LABEL: Record<string, string> = {
  pptx: 'PPTX',
  pptx_native: 'PPTX（原生图表）',
  pptx_narrated: 'PPTX（含旁白）',
  pdf: 'PDF',
  log: '日志',
  report: '报告',
};

/** 增强选项（Checkbox 组）：value 即后端布尔字段名 */
const ENHANCE_FLAGS: { label: string; value: string }[] = [
  { label: '原生图表/表格', value: 'native_charts' },
  { label: '讲者备注', value: 'speaker_notes' },
  { label: '语音旁白', value: 'narration' },
  { label: '转场', value: 'transitions' },
  { label: '对象动画', value: 'animations' },
];

/** 表单值（文件列表另存于 state，不走 Form） */
interface FormValues {
  input_mode: string;
  topic?: string;
  text?: string;
  url?: string;
  route: string;
  profile: string;
  pages?: number | null;
  canvas: string;
  style: string;
  narrative_mode: string;
  reading_mode: string;
  language: string;
  enhancements: string[];
  image_source: string;
  extra_instructions?: string;
  title?: string;
  agent: string;
  model: string;
  timeout_minutes?: number | null;
}

/** 字节数 → 人类可读大小 */
function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || bytes < 0) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** 是否为进行中状态（需要轮询） */
function isActive(status: PptMasterStatus | undefined | null): boolean {
  return status === 'pending' || status === 'running';
}

/** 枚举 key → 展示名（找不到时回退 key 本身） */
function labelOf(list: OptionItem[] | undefined, key: unknown): string {
  if (key == null || key === '') return '-';
  const k = String(key);
  return list?.find((o) => o.key === k)?.label ?? k;
}

/** 参数原样值 → 展示字符串 */
function strOf(v: unknown): string {
  if (v == null || v === '') return '-';
  return String(v);
}

/** 布尔参数（后端可能回传 'true'/'false' 字符串或布尔值） */
function flagOn(v: unknown): boolean {
  return v === true || v === 'true' || v === '1' || v === 1;
}

/** 从枚举列表里挑默认值：优先 preferred，否则取第一项 */
function pickDefault(list: OptionItem[] | undefined, preferred: string): string {
  if (!list || list.length === 0) return preferred;
  return list.some((o) => o.key === preferred) ? preferred : list[0].key;
}

/** 状态 Tag */
function PmStatusTag({ status }: { status: PptMasterStatus }) {
  const cfg = PM_STATUS[status];
  if (!cfg) return <Tag>{status}</Tag>;
  return <Tag color={cfg.color}>{cfg.label}</Tag>;
}

/** ppt-master 生成页：上方提交表单，下方任务列表（轮询进度）+ 详情抽屉 */
export default function PptMaster() {
  // ---------- 可选项 ----------
  const [options, setOptions] = useState<PptMasterOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [optionsError, setOptionsError] = useState(false);

  const loadOptions = useCallback(async () => {
    setOptionsLoading(true);
    setOptionsError(false);
    try {
      const data = await pptmasterApi.options();
      setOptions(data);
    } catch {
      setOptionsError(true);
    } finally {
      setOptionsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOptions();
  }, [loadOptions]);

  // ---------- 任务列表 ----------
  const [items, setItems] = useState<PptMasterJob[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<PptMasterStatus | ''>('');
  const [reloadTick, setReloadTick] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  const loadList = useCallback(
    async (silent = false) => {
      if (!silent) setListLoading(true);
      try {
        const data = await pptmasterApi.list({
          status: statusFilter,
          page,
          page_size: PAGE_SIZE,
        });
        setItems(data.items ?? []);
        setTotal(data.total ?? 0);
      } catch {
        /* 错误提示由 client 统一处理 */
      } finally {
        if (!silent) setListLoading(false);
      }
    },
    [statusFilter, page],
  );

  useEffect(() => {
    void loadList();
  }, [loadList, reloadTick]);

  // 有排队/进行中的任务时定时静默刷新列表
  const hasActive = items.some((j) => isActive(j.status));
  useEffect(() => {
    if (!hasActive) return;
    const poll = window.setInterval(() => void loadList(true), POLL_MS);
    return () => window.clearInterval(poll);
  }, [hasActive, loadList]);

  /** 强制回到第一页并刷新（提交成功后调用） */
  const refreshFromTop = () => {
    setStatusFilter('');
    setPage(1);
    setReloadTick((t) => t + 1);
  };

  // ---------- 详情抽屉 ----------
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PptMasterJobDetail | null>(null);
  const detailActiveRef = useRef(false);
  detailActiveRef.current = isActive(detail?.status);

  useEffect(() => {
    if (!detailId) return;
    let disposed = false;
    const fetchDetail = async () => {
      try {
        const d = await pptmasterApi.detail(detailId);
        if (!disposed) setDetail(d);
      } catch {
        /* 已统一提示 */
      }
    };
    void fetchDetail();
    // 抽屉打开期间仅在任务进行中时轮询
    const timer = window.setInterval(() => {
      if (detailActiveRef.current) void fetchDetail();
    }, POLL_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [detailId]);

  // 列表或抽屉中存在进行中任务时，每秒刷新「实时耗时」
  const tickActive = hasActive || isActive(detail?.status);
  useEffect(() => {
    if (!tickActive) return;
    setNow(Date.now());
    const tick = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(tick);
  }, [tickActive]);

  const openDetail = (id: string) => {
    setDetail(null);
    setDetailId(id);
  };
  const closeDetail = () => {
    setDetailId(null);
    setDetail(null);
  };
  const reloadDetail = async () => {
    if (!detailId) return;
    try {
      const d = await pptmasterApi.detail(detailId);
      setDetail(d);
    } catch {
      /* 已统一提示 */
    }
  };

  // ---------- 操作 ----------
  const handleCancel = async (id: string) => {
    try {
      await pptmasterApi.cancel(id);
      message.success('已取消任务');
      void loadList(true);
      if (detailId === id) void reloadDetail();
    } catch {
      /* 已统一提示 */
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await pptmasterApi.remove(id);
      message.success('已删除任务');
      if (detailId === id) closeDetail();
      void loadList(true);
    } catch {
      /* 已统一提示 */
    }
  };

  // ---------- 表格列 ----------
  const columns: ColumnsType<PptMasterJob> = [
      {
        title: '任务名',
        dataIndex: 'title',
        ellipsis: true,
        render: (title: string, r) => (
          <Flex vertical style={{ minWidth: 0 }}>
            <Typography.Link ellipsis onClick={() => openDetail(r.job_id)} title={title}>
              {title || r.job_id}
            </Typography.Link>
            <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
              {labelOf(options?.input_modes, r.input_mode)} · {labelOf(options?.routes, r.route)}
              {' · '}
              {labelOf(options?.profiles, r.profile)}
            </Typography.Text>
          </Flex>
        ),
      },
      {
        title: 'Agent',
        dataIndex: 'agent',
        width: 100,
        render: (agent: string) => <span>{AGENT_SHORT[agent] ?? agent}</span>,
      },
      {
        title: '模型',
        dataIndex: 'model',
        width: 140,
        ellipsis: true,
        render: (model: string | null) => model || '-',
      },
      {
        title: '状态',
        dataIndex: 'status',
        width: 200,
        render: (status: PptMasterStatus, r) => (
          <Space direction="vertical" size={2} style={{ width: '100%' }}>
            <PmStatusTag status={status} />
            {isActive(status) && (
              <>
                <Progress
                  percent={Math.max(0, Math.min(100, r.progress ?? 0))}
                  size="small"
                  status="active"
                  style={{ margin: 0 }}
                />
                {r.stage && (
                  <Tooltip
                    title={stageTooltipText(r.stage_history, r.stage)}
                    overlayStyle={{ maxWidth: 720 }}
                  >
                    <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                      {r.stage}
                    </Typography.Text>
                  </Tooltip>
                )}
              </>
            )}
            {status === 'failed' && r.error_message && (
              <Typography.Text type="danger" style={{ fontSize: 12 }} ellipsis title={r.error_message}>
                {r.error_message}
              </Typography.Text>
            )}
          </Space>
        ),
      },
      {
        title: '页数/大小',
        width: 110,
        render: (_, r) => (
          <Space direction="vertical" size={0}>
            <span>{r.page_count != null ? `${r.page_count} 页` : '-'}</span>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {formatBytes(r.file_size)}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: '耗时',
        width: 90,
        render: (_, r) => {
          // 运行中：以 started_at 起算实时耗时；结束后用后端 duration_ms
          if (isActive(r.status) && r.started_at) {
            const elapsed = now - new Date(r.started_at).getTime();
            return formatDuration(Math.max(0, elapsed));
          }
          return formatDuration(r.duration_ms);
        },
      },
      {
        title: '创建时间',
        dataIndex: 'created_at',
        width: 150,
        render: (v: string) => formatTime(v),
      },
      {
        title: '操作',
        width: 230,
        render: (_, r) => (
          <Space size={4} wrap>
            <Button size="small" icon={<EyeOutlined />} onClick={() => openDetail(r.job_id)}>
              详情
            </Button>
            <DownloadButton job={r} />
            {isActive(r.status) && (
              <Popconfirm title="确认取消该任务？" onConfirm={() => handleCancel(r.job_id)}>
                <Button size="small" danger icon={<StopOutlined />}>
                  取消
                </Button>
              </Popconfirm>
            )}
            {!isActive(r.status) && (
              <Popconfirm
                title="确认删除该任务及其产物？"
                onConfirm={() => handleDelete(r.job_id)}
              >
                <Button size="small" danger type="text" icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            )}
          </Space>
        ),
      },
  ];

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {/* 上：新建任务表单 */}
      <Card title="新建 ppt-master 生成任务">
        {optionsLoading ? (
          <Flex justify="center" style={{ padding: 40 }}>
            <Space>
              <Spin />
              <Typography.Text type="secondary">正在加载配置…</Typography.Text>
            </Space>
          </Flex>
        ) : optionsError || !options ? (
          <Alert
            type="error"
            showIcon
            message="无法加载 ppt-master 配置"
            description="请确认后端服务已启动并实现 /api/v1/pptmaster/options 接口。"
            action={
              <Button size="small" onClick={() => void loadOptions()}>
                重试
              </Button>
            }
          />
        ) : (
          <SubmitForm options={options} onSubmitted={refreshFromTop} />
        )}
      </Card>

      {/* 下：任务列表 */}
      <Card
        title="生成任务列表"
        extra={
          <Space>
            <Select<PptMasterStatus | ''>
              value={statusFilter}
              style={{ width: 130 }}
              onChange={(v) => {
                setStatusFilter(v);
                setPage(1);
              }}
              options={[
                { value: '', label: '全部状态' },
                ...(Object.keys(PM_STATUS) as PptMasterStatus[]).map((k) => ({
                  value: k,
                  label: PM_STATUS[k].label,
                })),
              ]}
            />
            <Button icon={<ReloadOutlined />} onClick={() => void loadList()}>
              刷新
            </Button>
          </Space>
        }
      >
        <Table<PptMasterJob>
          rowKey="job_id"
          loading={listLoading}
          dataSource={items}
          columns={columns}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total,
            showSizeChanger: false,
            onChange: (p) => setPage(p),
          }}
          locale={{ emptyText: <Empty description="暂无任务，在上方提交一个生成任务开始" /> }}
        />
      </Card>

      {/* 详情抽屉 */}
      <DetailDrawer
        open={!!detailId}
        detail={detail}
        options={options}
        now={now}
        onClose={closeDetail}
        onRefresh={() => void reloadDetail()}
        onCancel={handleCancel}
        onDelete={handleDelete}
      />
    </Space>
  );
}

/* ====================================================================== */
/*                               提交表单                                  */
/* ====================================================================== */

function SubmitForm({
  options,
  onSubmitted,
}: {
  options: PptMasterOptions;
  onSubmitted: () => void;
}) {
  const [form] = Form.useForm<FormValues>();
  const [submitting, setSubmitting] = useState(false);
  // 文件列表单独管理（不走 Form 值），提交成功后清空
  const [sourceFiles, setSourceFiles] = useState<UploadFile[]>([]);
  const [templateFiles, setTemplateFiles] = useState<UploadFile[]>([]);

  const { limits } = options;
  const acceptExts = useMemo(
    () => (options.accept_extensions ?? []).map((e) => e.toLowerCase()),
    [options.accept_extensions],
  );

  /** 表单默认值（由 /options 推导） */
  const initialValues = useMemo<FormValues>(
    () => ({
      input_mode: pickDefault(options.input_modes, 'files'),
      route: pickDefault(options.routes, 'generate'),
      profile: pickDefault(options.profiles, 'quick'),
      pages: null,
      canvas: pickDefault(options.canvas_formats, 'ppt169'),
      style: pickDefault(options.styles, 'auto'),
      narrative_mode: pickDefault(options.narrative_modes, 'auto'),
      reading_mode: pickDefault(options.reading_modes, 'auto'),
      language: pickDefault(options.languages, 'auto'),
      enhancements: [],
      image_source: pickDefault(options.image_sources, 'auto'),
      extra_instructions: '',
      title: '',
      agent: options.default_agent || options.agents[0]?.key || 'auto',
      model: resolveInitialModel(options.models, options.default_model),
      timeout_minutes: limits.timeout_minutes_default,
    }),
    [options, limits.timeout_minutes_default],
  );

  const inputMode = Form.useWatch('input_mode', form) ?? initialValues.input_mode;
  const routeKey = Form.useWatch('route', form) ?? initialValues.route;
  const profileKey = Form.useWatch('profile', form) ?? initialValues.profile;
  const selectedRoute = options.routes.find((r) => r.key === routeKey);
  const needsTemplate = !!selectedRoute?.needs_template;
  const templateStyleLocked = isTemplateStyleLocked(routeKey);
  const needsPptx = !!selectedRoute?.needs_pptx;
  const routeAgents = selectedRoute?.agents;
  const hasAgentRestriction = !!routeAgents && routeAgents.length > 0;

  // 路线需要 PPTX 输入时强制「上传源文件」
  useEffect(() => {
    if (needsPptx && inputMode !== 'files') {
      form.setFieldValue('input_mode', 'files');
    }
  }, [needsPptx, inputMode, form]);

  // 路线限定 Agent 时自动切换
  useEffect(() => {
    if (!routeAgents || routeAgents.length === 0) return;
    const cur = form.getFieldValue('agent') as string | undefined;
    if (!cur || !routeAgents.includes(cur)) {
      form.setFieldValue('agent', routeAgents[0]);
    }
  }, [routeAgents, form]);

  useEffect(() => {
    const current = form.getFieldValue('style') as string | undefined;
    form.setFieldValue('style', resolvePptMasterStyle(routeKey, current || 'auto'));
  }, [routeKey, form]);

  // 环境告警：仓库未就绪 / 无可用真实 Agent
  const noRealAgent = !options.agents.some((a) => a.available && a.key !== 'mock');
  const warnings: string[] = [];
  if (!options.repo.ready && !options.repo.delegated) {
    warnings.push(
      `ppt-master 仓库未就绪（${options.repo.dir || '未配置目录'}），任务将无法真正执行，请先在服务端安装 ppt-master。`,
    );
  }
  if (noRealAgent && options.execution_scope !== 'worker') {
    warnings.push('未检测到可用的 claude / codex 命令行 Agent，任务将以 mock Agent 模拟执行流程。');
  }

  /** 源文件校验：扩展名 + 单文件大小 */
  const beforeSourceUpload = (file: File): boolean | string => {
    const lower = file.name.toLowerCase();
    if (acceptExts.length > 0 && !acceptExts.some((ext) => lower.endsWith(ext))) {
      message.error(`不支持的文件类型：${file.name}`);
      return Upload.LIST_IGNORE;
    }
    if (file.size > limits.max_upload_mb * 1024 * 1024) {
      message.error(`文件 ${file.name} 超过 ${limits.max_upload_mb}MB 限制`);
      return Upload.LIST_IGNORE;
    }
    return false; // 不自动上传，随表单一起提交
  };

  const beforeTemplateUpload = (file: File): boolean | string => {
    if (!file.name.toLowerCase().endsWith('.pptx')) {
      message.error('模板必须是 .pptx 文件');
      return Upload.LIST_IGNORE;
    }
    if (file.size > limits.max_upload_mb * 1024 * 1024) {
      message.error(`模板超过 ${limits.max_upload_mb}MB 限制`);
      return Upload.LIST_IGNORE;
    }
    return false;
  };

  /** 组装 multipart 并提交 */
  const handleFinish = async (v: FormValues) => {
    // 按输入方式做必填校验（文件类不走 Form 校验）
    if (v.input_mode === 'files' && sourceFiles.length === 0) {
      message.error(needsPptx ? '请上传要处理的 PPTX 文件' : '请上传至少一个源文件');
      return;
    }
    if (needsTemplate && templateFiles.length === 0) {
      message.error('请上传我的 PPTX 模板');
      return;
    }

    const fd = new FormData();
    fd.append('input_mode', v.input_mode);
    if (v.input_mode === 'topic') fd.append('topic', (v.topic ?? '').trim());
    if (v.input_mode === 'text') fd.append('text', (v.text ?? '').trim());
    if (v.input_mode === 'url') fd.append('url', (v.url ?? '').trim());
    fd.append('route', v.route);
    fd.append('profile', v.profile);
    if (v.pages != null) fd.append('pages', String(v.pages));
    fd.append('canvas', v.canvas);
    fd.append('style', resolvePptMasterStyle(v.route, v.style));
    fd.append('narrative_mode', v.narrative_mode);
    fd.append('reading_mode', v.reading_mode);
    fd.append('language', v.language);
    const enh = v.enhancements ?? [];
    ENHANCE_FLAGS.forEach((f) => fd.append(f.value, enh.includes(f.value) ? 'true' : 'false'));
    fd.append('image_source', v.image_source);
    if (v.extra_instructions?.trim()) fd.append('extra_instructions', v.extra_instructions.trim());
    if (v.title?.trim()) fd.append('title', v.title.trim());
    fd.append('agent', v.agent || 'auto');
    fd.append('model', v.model.trim());
    if (v.timeout_minutes != null) fd.append('timeout_minutes', String(v.timeout_minutes));
    // 文件：源文件（可多个）+ 模板（可选单个）
    if (v.input_mode === 'files') {
      sourceFiles.forEach((f) => {
        const raw = f.originFileObj as File | undefined;
        if (raw) fd.append('files', raw, f.name);
      });
    }
    if (needsTemplate && templateFiles[0]?.originFileObj) {
      fd.append('template', templateFiles[0].originFileObj as File, templateFiles[0].name);
    }

    setSubmitting(true);
    try {
      const res = await pptmasterApi.create(fd);
      message.success(`任务已提交（${res.job_id}），请在下方列表查看进度`);
      // 保留其他参数，只清空文件列表
      setSourceFiles([]);
      setTemplateFiles([]);
      onSubmitted();
    } catch {
      /* 已统一提示 */
    } finally {
      setSubmitting(false);
    }
  };

  /** Agent 下拉项：不可用的置灰并附说明；路线限定时禁用不在名单中的 */
  const agentOptions = [
    ...options.agents.map((a) => {
      const restricted = hasAgentRestriction && !routeAgents!.includes(a.key);
      const suffix = !a.available ? `（不可用${a.note ? `：${a.note}` : ''}）` : a.note ? `（${a.note}）` : '';
      return {
        value: a.key,
        label: `${a.label}${suffix}`,
        disabled: !a.available || restricted,
      };
    }),
  ];

  return (
    <Form<FormValues>
      form={form}
      layout="vertical"
      initialValues={initialValues}
      onFinish={(v) => void handleFinish(v)}
      disabled={submitting}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {warnings.length > 0 && (
          <Alert
            type="warning"
            showIcon
            message="环境提示"
            description={
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            }
          />
        )}

        {/* 输入方式 */}
        <Form.Item name="input_mode" label="输入方式" style={{ marginBottom: 8 }}>
          <Radio.Group
            optionType="button"
            buttonStyle="solid"
            options={options.input_modes.map((m) => ({
              label: m.label,
              value: m.key,
              disabled: needsPptx && m.key !== 'files',
            }))}
          />
        </Form.Item>
        {needsPptx && (
          <Typography.Text type="warning">
            当前路线需要现成 PPTX：请在下方「上传源文件」中上传要处理的 PPTX
            {routeKey === 'image_to_pptx' ? '（或页面图片）' : ''}。
          </Typography.Text>
        )}

        {inputMode === 'files' && (
          <Form.Item
            label="上传源文件"
            required
            extra={`支持 ${acceptExts.join(' ')}；最多 ${limits.max_files} 个，单文件 ≤ ${limits.max_upload_mb}MB`}
          >
            <Upload.Dragger
              multiple
              accept={acceptExts.join(',')}
              maxCount={limits.max_files}
              fileList={sourceFiles}
              beforeUpload={beforeSourceUpload}
              onChange={({ fileList }) => setSourceFiles(fileList)}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">拖拽或点击选择源文件（可多选）</p>
              <p className="ant-upload-hint">
                文档 / 表格 / PPTX / 图片等，将作为 ppt-master 的输入素材
              </p>
            </Upload.Dragger>
          </Form.Item>
        )}
        {inputMode === 'topic' && (
          <Form.Item
            name="topic"
            label="主题"
            rules={[{ required: true, whitespace: true, message: '请输入要生成的主题' }]}
          >
            <Input placeholder="例如：2026 年新能源汽车市场趋势分析" maxLength={200} showCount />
          </Form.Item>
        )}
        {inputMode === 'text' && (
          <Form.Item
            name="text"
            label="粘贴文本"
            rules={[{ required: true, whitespace: true, message: '请粘贴要转换的文本内容' }]}
          >
            <Input.TextArea rows={6} placeholder="粘贴文章 / 提纲 / 会议纪要等文本" />
          </Form.Item>
        )}
        {inputMode === 'url' && (
          <Form.Item
            name="url"
            label="网页链接"
            rules={[
              { required: true, whitespace: true, message: '请输入网页链接' },
              {
                validator: (_, value: string | undefined) =>
                  !value || /^https?:\/\//i.test(value.trim())
                    ? Promise.resolve()
                    : Promise.reject(new Error('链接需以 http:// 或 https:// 开头')),
              },
            ]}
          >
            <Input placeholder="https://example.com/article" />
          </Form.Item>
        )}

        {/* 生成路线 + 档位 */}
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="route"
              label={
                <Space size={6}>
                  <span>生成路线</span>
                  {hasAgentRestriction && (
                    <Tag color="orange" style={{ marginInlineEnd: 0 }}>
                      仅 {routeAgents!.map((k) => labelOf(options.agents, k)).join(' / ')}
                    </Tag>
                  )}
                </Space>
              }
              extra={selectedRoute?.desc}
            >
              <Select
                options={options.routes.map((r) => ({ value: r.key, label: r.label, desc: r.desc }))}
                optionRender={(opt) => (
                  <div>
                    <div>{opt.data.label}</div>
                    {opt.data.desc && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {opt.data.desc}
                      </Typography.Text>
                    )}
                  </div>
                )}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="profile"
              label="生成档位"
              extra={options.profiles.find((p) => p.key === profileKey)?.desc}
            >
              <Radio.Group
                options={options.profiles.map((p) => ({ label: p.label, value: p.key }))}
              />
            </Form.Item>
          </Col>
        </Row>

        {needsTemplate && (
          <Form.Item label="我的 PPTX 模板" required extra="套用该模板的版式与配色生成内容（仅 .pptx）">
            <Upload
              accept=".pptx"
              maxCount={1}
              fileList={templateFiles}
              beforeUpload={beforeTemplateUpload}
              onChange={({ fileList }) => setTemplateFiles(fileList)}
            >
              <Button icon={<UploadOutlined />}>选择模板文件</Button>
            </Upload>
          </Form.Item>
        )}

        {/* 参数区 */}
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item
              name="model"
              label="生成模型"
              rules={[{ required: true, message: '请选择生成模型' }]}
            >
              <Select options={options.models.map((item) => ({ value: item, label: item }))} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="pages" label="页数">
              <InputNumber
                min={limits.pages_min}
                max={limits.pages_max}
                precision={0}
                placeholder="由 Agent 决定"
                style={{ width: '100%' }}
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="canvas" label="画布格式">
              <Select
                options={options.canvas_formats.map((c) => ({
                  value: c.key,
                  label: `${c.label}（${c.size}）`,
                }))}
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item
              name="style"
              label="视觉风格"
              extra={templateStyleLocked ? '视觉风格由上传的 PPTX 模板决定，不可修改' : undefined}
            >
              <Select
                disabled={templateStyleLocked}
                showSearch
                optionFilterProp="label"
                options={options.styles
                  .filter((s) => templateStyleLocked ? s.key === 'template' : s.key !== 'template')
                  .map((s) => ({ value: s.key, label: s.label, desc: s.desc }))}
                optionRender={(opt) => (
                  <div>
                    <div>{opt.data.label}</div>
                    {opt.data.desc && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {opt.data.desc}
                      </Typography.Text>
                    )}
                  </div>
                )}
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="narrative_mode" label="叙事模式">
              <Select
                options={options.narrative_modes.map((s) => ({ value: s.key, label: s.label }))}
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="reading_mode" label="阅读模式">
              <Select
                options={options.reading_modes.map((s) => ({ value: s.key, label: s.label }))}
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="language" label="语言">
              <Select options={options.languages.map((s) => ({ value: s.key, label: s.label }))} />
            </Form.Item>
          </Col>
        </Row>

        {/* 增强选项 */}
        <Row gutter={16}>
          <Col span={16}>
            <Form.Item name="enhancements" label="增强选项">
              <Checkbox.Group options={ENHANCE_FLAGS} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="image_source" label="图片素材">
              <Select
                options={options.image_sources.map((s) => ({ value: s.key, label: s.label }))}
              />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={16}>
            <Form.Item name="extra_instructions" label="附加要求">
              <Input.TextArea
                rows={3}
                placeholder="可选：对结构、重点、语气、配色等的额外要求，会原样附加到 Agent 提示词"
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="title" label="任务名称" extra="可选，留空由后端按文件名 / 主题推导">
              <Input placeholder="例如：Q3 经营分析汇报" maxLength={100} />
            </Form.Item>
          </Col>
        </Row>

        {/* 执行设置（默认折叠；forceRender 保证字段注册） */}
        <Collapse
          size="small"
          items={[
            {
              key: 'exec',
              label: '高级：执行 Agent 与超时',
              forceRender: true,
              children: (
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="agent" label="执行 Agent" style={{ marginBottom: 0 }}>
                      <Select options={agentOptions} />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="timeout_minutes" label="超时（分钟）" style={{ marginBottom: 0 }}>
                      <InputNumber
                        min={1}
                        max={limits.timeout_minutes_max}
                        precision={0}
                        style={{ width: '100%' }}
                      />
                    </Form.Item>
                  </Col>
                </Row>
              ),
            },
          ]}
        />

        <Flex justify="flex-end">
          <Button
            type="primary"
            size="large"
            icon={<RocketOutlined />}
            htmlType="submit"
            loading={submitting}
          >
            提交生成
          </Button>
        </Flex>
      </Space>
    </Form>
  );
}

/* ====================================================================== */
/*                               下载按钮                                  */
/* ====================================================================== */

/** 列表操作列的下载：单产物直接下载，多产物下拉选择 */
function DownloadButton({ job }: { job: PptMasterJob }) {
  const outputs = job.outputs ?? [];
  if (outputs.length === 0) {
    if (job.pptx_url) {
      return (
        <Button
          size="small"
          type="primary"
          icon={<DownloadOutlined />}
          href={job.pptx_url}
          target="_blank"
        >
          下载
        </Button>
      );
    }
    return null;
  }
  if (outputs.length === 1) {
    return (
      <Button
        size="small"
        type="primary"
        icon={<DownloadOutlined />}
        href={outputs[0].download_url}
        target="_blank"
        title={outputs[0].name}
      >
        下载
      </Button>
    );
  }
  return (
    <Dropdown
      menu={{
        items: outputs.map((o, i) => ({
          key: `${o.kind}-${i}`,
          label: (
            <a href={o.download_url} target="_blank" rel="noreferrer">
              {outputLabel(o)}
            </a>
          ),
        })),
      }}
    >
      <Button size="small" type="primary" icon={<DownloadOutlined />}>
        下载 <DownOutlined />
      </Button>
    </Dropdown>
  );
}

function outputLabel(o: PptMasterOutput): string {
  const kind = OUTPUT_KIND_LABEL[o.kind] ?? o.kind;
  return `${kind} · ${o.name}（${formatBytes(o.size)}）`;
}

/* ====================================================================== */
/*                               详情抽屉                                  */
/* ====================================================================== */

function DetailDrawer({
  open,
  detail,
  options,
  now,
  onClose,
  onRefresh,
  onCancel,
  onDelete,
}: {
  open: boolean;
  detail: PptMasterJobDetail | null;
  options: PptMasterOptions | null;
  now: number;
  onClose: () => void;
  onRefresh: () => void;
  onCancel: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const logRef = useRef<HTMLPreElement>(null);

  // 日志更新时自动滚到底部
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [detail?.log_tail, open]);

  const params = detail?.params ?? {};
  const active = isActive(detail?.status);

  /** 耗时：运行中按 started_at 实时计算 */
  const durationText = (() => {
    if (!detail) return '-';
    if (active && detail.started_at) {
      return formatDuration(Math.max(0, now - new Date(detail.started_at).getTime()));
    }
    return formatDuration(detail.duration_ms);
  })();

  const flagText = ENHANCE_FLAGS.filter((f) => flagOn(params[f.value]))
    .map((f) => f.label)
    .join('、');

  return (
    <Drawer
      width={720}
      open={open}
      onClose={onClose}
      destroyOnHidden
      title={
        detail ? (
          <Space size={8} wrap>
            <Typography.Text strong ellipsis style={{ maxWidth: 420 }} title={detail.title}>
              {detail.title || detail.job_id}
            </Typography.Text>
            <PmStatusTag status={detail.status} />
          </Space>
        ) : (
          '任务详情'
        )
      }
      extra={
        <Space>
          <Button size="small" icon={<ReloadOutlined />} onClick={onRefresh}>
            刷新
          </Button>
          {detail && active && (
            <Popconfirm title="确认取消该任务？" onConfirm={() => onCancel(detail.job_id)}>
              <Button size="small" danger icon={<StopOutlined />}>
                取消
              </Button>
            </Popconfirm>
          )}
          {detail && !active && (
            <Popconfirm title="确认删除该任务及其产物？" onConfirm={() => onDelete(detail.job_id)}>
              <Button size="small" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      }
    >
      {!detail ? (
        <Flex justify="center" style={{ padding: 40 }}>
          <Spin />
        </Flex>
      ) : (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {/* 进度 */}
          {active && (
            <div>
              <Progress
                percent={Math.max(0, Math.min(100, detail.progress ?? 0))}
                status="active"
              />
              <Typography.Text type="secondary">
                {detail.stage || (detail.status === 'pending' ? '等待执行…' : '执行中…')}
                {' · 已用时 '}
                {durationText}
              </Typography.Text>
            </div>
          )}

          {/* 失败原因 */}
          {detail.status === 'failed' && (
            <Alert
              type="error"
              showIcon
              message="生成失败"
              description={detail.error_message || '未知错误，请查看执行日志'}
            />
          )}

          {/* 关键参数 */}
          <Descriptions
            size="small"
            bordered
            column={2}
            items={[
              { key: 'id', label: '任务 ID', children: <Typography.Text copyable>{detail.job_id}</Typography.Text> },
              { key: 'input', label: '输入方式', children: labelOf(options?.input_modes, detail.input_mode) },
              { key: 'route', label: '生成路线', children: labelOf(options?.routes, detail.route) },
              { key: 'profile', label: '生成档位', children: labelOf(options?.profiles, detail.profile) },
              { key: 'agent', label: 'Agent', children: labelOf(options?.agents, detail.agent) },
              { key: 'model', label: '模型', children: detail.model || '默认' },
              { key: 'canvas', label: '画布格式', children: labelOf(options?.canvas_formats, params.canvas) },
              { key: 'style', label: '视觉风格', children: labelOf(options?.styles, params.style) },
              { key: 'narrative', label: '叙事模式', children: labelOf(options?.narrative_modes, params.narrative_mode) },
              { key: 'reading', label: '阅读模式', children: labelOf(options?.reading_modes, params.reading_mode) },
              {
                key: 'pages',
                label: '页数',
                children:
                  detail.page_count != null
                    ? `${detail.page_count} 页${params.pages ? `（目标 ${strOf(params.pages)}）` : ''}`
                    : params.pages
                      ? `目标 ${strOf(params.pages)}`
                      : '由 Agent 决定',
              },
              { key: 'lang', label: '语言', children: labelOf(options?.languages, params.language) },
              { key: 'img', label: '图片素材', children: labelOf(options?.image_sources, params.image_source) },
              { key: 'flags', label: '增强选项', children: flagText || '无' },
              { key: 'size', label: '产物大小', children: formatBytes(detail.file_size) },
              { key: 'duration', label: '耗时', children: durationText },
              {
                key: 'usage',
                label: 'Agent 用量',
                children: detail.run
                  ? [
                      detail.run.cost_usd != null ? `费用 $${Number(detail.run.cost_usd).toFixed(2)}` : null,
                      detail.run.num_turns != null ? `${detail.run.num_turns} 轮` : null,
                      detail.run.returncode != null ? `退出码 ${detail.run.returncode}` : null,
                    ]
                      .filter(Boolean)
                      .join(' · ') || '—'
                  : '—',
              },
              { key: 'created', label: '创建时间', children: formatTime(detail.created_at, 'YYYY-MM-DD HH:mm:ss') },
              { key: 'finished', label: '完成时间', children: formatTime(detail.finished_at, 'YYYY-MM-DD HH:mm:ss') },
              ...(params.extra_instructions
                ? [
                    {
                      key: 'extra',
                      label: '附加要求',
                      span: 2,
                      children: (
                        <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                          {strOf(params.extra_instructions)}
                        </Typography.Paragraph>
                      ),
                    },
                  ]
                : []),
            ]}
          />

          {/* 源文件 / 模板 */}
          {(detail.source_files.length > 0 || detail.template_name) && (
            <Card size="small" title="输入文件">
              <Space direction="vertical" size={2}>
                {detail.source_files.map((f, i) => (
                  <Typography.Text key={i}>
                    {f.name}{' '}
                    <Typography.Text type="secondary">（{formatBytes(f.size)}）</Typography.Text>
                  </Typography.Text>
                ))}
                {detail.template_name && (
                  <Typography.Text>
                    <Tag color="blue" style={{ marginInlineEnd: 4 }}>
                      模板
                    </Tag>
                    {detail.template_name}
                  </Typography.Text>
                )}
              </Space>
            </Card>
          )}

          {/* 产物 */}
          {detail.outputs.length > 0 && (
            <Card size="small" title="产物下载">
              <Space wrap>
                {detail.outputs.map((o, i) => (
                  <Button
                    key={`${o.kind}-${i}`}
                    type={o.kind.startsWith('pptx') ? 'primary' : 'default'}
                    icon={<DownloadOutlined />}
                    href={o.download_url}
                    target="_blank"
                  >
                    {outputLabel(o)}
                  </Button>
                ))}
              </Space>
            </Card>
          )}

          {/* 页面预览 */}
          {detail.preview_pages > 0 && detail.preview_urls.length > 0 && (
            <Card size="small" title={`页面预览（${detail.preview_pages} 页，点击放大）`}>
              <Image.PreviewGroup>
                <Flex wrap gap={8}>
                  {detail.preview_urls.map((url, i) => (
                    <div
                      key={url}
                      style={{
                        width: 160,
                        border: '1px solid #f0f0f0',
                        borderRadius: 4,
                        overflow: 'hidden',
                        background: '#fafafa',
                      }}
                    >
                      <Image
                        src={url}
                        alt={`第 ${i + 1} 页`}
                        width={160}
                        style={{ display: 'block', objectFit: 'contain' }}
                      />
                      <Typography.Text
                        type="secondary"
                        style={{ display: 'block', textAlign: 'center', fontSize: 12 }}
                      >
                        第 {i + 1} 页
                      </Typography.Text>
                    </div>
                  ))}
                </Flex>
              </Image.PreviewGroup>
            </Card>
          )}

          {/* 执行日志 */}
          <Card
            size="small"
            title="执行日志"
            extra={
              detail.log_url && (
                <a href={detail.log_url} target="_blank" rel="noreferrer">
                  完整日志 <ExportOutlined />
                </a>
              )
            }
          >
            <pre
              ref={logRef}
              style={{
                margin: 0,
                maxHeight: 300,
                overflow: 'auto',
                background: '#1f1f1f',
                color: '#d4d4d4',
                padding: 12,
                borderRadius: 4,
                fontSize: 12,
                lineHeight: 1.5,
                fontFamily: 'Consolas, "Courier New", monospace',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              {detail.log_tail || (active ? '等待日志输出…' : '（无日志）')}
            </pre>
          </Card>

          {/* 提示词 */}
          {detail.prompt && (
            <Collapse
              size="small"
              items={[
                {
                  key: 'prompt',
                  label: '实际提示词',
                  children: (
                    <pre
                      style={{
                        margin: 0,
                        maxHeight: 360,
                        overflow: 'auto',
                        fontSize: 12,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                      }}
                    >
                      {detail.prompt}
                    </pre>
                  ),
                },
              ]}
            />
          )}
        </Space>
      )}
    </Drawer>
  );
}
