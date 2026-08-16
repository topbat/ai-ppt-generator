import { useEffect, useState } from 'react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { Badge, Layout, Menu, Space, Typography } from 'antd';
import {
  AppstoreOutlined,
  HighlightOutlined,
  PlusCircleOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import { checkHealth } from './api/endpoints';
import JobsList from './pages/JobsList';
import JobNew from './pages/JobNew';
import JobDetail from './pages/job-detail/JobDetail';
import Templates from './pages/Templates';
import Beautify from './pages/Beautify';

const { Header, Content } = Layout;

const HEALTH_POLL_MS = 30_000; // 健康状态轮询间隔

/** 顶部导航 + 路由布局 */
export default function App() {
  const location = useLocation();
  const [healthy, setHealthy] = useState<boolean | null>(null);

  // 轮询 /healthz 展示系统状态点
  useEffect(() => {
    let disposed = false;
    const poll = async () => {
      const ok = await checkHealth();
      if (!disposed) setHealthy(ok);
    };
    void poll();
    const timer = window.setInterval(poll, HEALTH_POLL_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, []);

  // 根据路径高亮菜单项
  const selectedKey = location.pathname.startsWith('/templates')
    ? 'templates'
    : location.pathname.startsWith('/beautify')
      ? 'beautify'
      : location.pathname === '/jobs/new'
        ? 'new'
        : 'jobs';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          background: '#fff',
          borderBottom: '1px solid #f0f0f0',
          paddingInline: 24,
          position: 'sticky',
          top: 0,
          zIndex: 100,
        }}
      >
        <Typography.Title level={4} style={{ margin: 0, marginRight: 40, whiteSpace: 'nowrap' }}>
          AI PPT 生成系统
        </Typography.Title>
        <Menu
          mode="horizontal"
          selectedKeys={[selectedKey]}
          style={{ flex: 1, borderBottom: 'none' }}
          items={[
            { key: 'jobs', icon: <UnorderedListOutlined />, label: <Link to="/jobs">任务列表</Link> },
            { key: 'new', icon: <PlusCircleOutlined />, label: <Link to="/jobs/new">新建生成</Link> },
            { key: 'templates', icon: <AppstoreOutlined />, label: <Link to="/templates">模板库</Link> },
            { key: 'beautify', icon: <HighlightOutlined />, label: <Link to="/beautify">PPT美化</Link> },
          ]}
        />
        <Space>
          {healthy === null ? (
            <Badge status="default" text="检测中…" />
          ) : healthy ? (
            <Badge status="success" text="系统正常" />
          ) : (
            <Badge status="error" text="系统异常" />
          )}
        </Space>
      </Header>
      <Content style={{ padding: 24, maxWidth: 1440, width: '100%', margin: '0 auto' }}>
        <Routes>
          <Route path="/" element={<Navigate to="/jobs" replace />} />
          <Route path="/jobs" element={<JobsList />} />
          <Route path="/jobs/new" element={<JobNew />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/templates" element={<Templates />} />
          <Route path="/beautify" element={<Beautify />} />
          <Route path="*" element={<Navigate to="/jobs" replace />} />
        </Routes>
      </Content>
    </Layout>
  );
}
