// 仅供 Vite 开发模式手动验收，生产构建入口不引用此文件。
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ConfigProvider, Typography } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import JobUsage from '../src/components/JobUsage';
import { setMetricsToken } from '../src/api/metrics';

setMetricsToken('preview-only');
ReactDOM.createRoot(document.getElementById('root')!).render(
  <ConfigProvider locale={zhCN}><BrowserRouter><main style={{ padding: 24, maxWidth: 1000, margin: 'auto' }}>
    <Typography.Title level={2}>任务用量组件验收 · 示例数据</Typography.Title>
    <Typography.Paragraph>使用独立内存数据库，不连接业务系统或真实模型。</Typography.Paragraph>
    <JobUsage engine="pipeline" jobId="demo-ppt" />
    <JobUsage engine="pptmaster" jobId="demo-ppt" />
  </main></BrowserRouter></ConfigProvider>,
);
