import { useState, useSyncExternalStore } from 'react';
import { Button, Input, Space, Typography } from 'antd';
import { readMetricsToken, setMetricsToken, subscribeMetricsToken } from '../api/metrics';

export function useMetricsToken() {
  return useSyncExternalStore(subscribeMetricsToken, readMetricsToken);
}

export default function MetricsAccess() {
  const token = useMetricsToken();
  const [draft, setDraft] = useState('');
  return token ? <Space wrap>
    <Typography.Text type="secondary">指标访问已解锁</Typography.Text>
    <Button size="small" onClick={() => setMetricsToken('')}>退出指标访问</Button>
  </Space> : <Space wrap>
    <Input.Password aria-label="指标访问令牌" placeholder="输入指标访问令牌" value={draft}
      onChange={e => setDraft(e.target.value)} onPressEnter={() => { setMetricsToken(draft); setDraft(''); }} />
    <Button type="primary" disabled={!draft.trim()} onClick={() => { setMetricsToken(draft); setDraft(''); }}>查看指标</Button>
    <Typography.Text type="secondary">令牌仅保存在当前页面，刷新后需重新输入。</Typography.Text>
  </Space>;
}
