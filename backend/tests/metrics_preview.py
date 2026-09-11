"""独立页面验收服务：只使用内存 SQLite 和明确的示例数据，不连接项目数据库。

运行 python backend/tests/metrics_preview.py，前端 VITE_API_TARGET=http://127.0.0.1:8017。
演示令牌 preview-only；服务仅监听 127.0.0.1。此文件不是生产启动入口。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import uvicorn

from app.api import metrics_api
from app.core.config import Settings
from app.core.database import get_db
from app.models.models import LLMObservation

metrics_api.get_settings = lambda: Settings(_env_file=None, metrics_access_token='preview-only')
engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
LLMObservation.__table__.create(engine)
with Session(engine) as db:
    for i in range(26):
        db.add(LLMObservation(id=f'preview-{i}', trace_id=f'{i:032x}', engine='pipeline' if i < 23 else 'pptmaster',
            kind='request' if i < 23 else 'agent_run', job_id=i, biz_id='demo-ppt',
            stage=['OUTLINE', 'CONTENT', 'QA'][i % 3], task_type='preview', provider='qwen',
            model=['qwen-demo', 'deepseek-demo'][i % 2], mode='standard', attempt=2 if i % 5 == 0 else 1,
            fallback=i % 5 == 0, input_tokens=None if i == 0 else 1200+i*12, output_tokens=400+i*8,
            cost_usd=None if i % 4 == 0 else .0042+i*.001, cost_source='unknown' if i % 4 == 0 else 'estimated',
            usage_source='partial' if i == 25 else 'reported', duration_ms=2200+i*350, queue_ms=40,
            status='failed' if i == 0 else 'success', created_at=datetime.now(timezone.utc)-timedelta(hours=i*4)))
    db.commit()

def db_dependency():
    with Session(engine) as db:
        yield db

app = FastAPI(title='LLM 指标示例验收（内存数据）')
app.include_router(metrics_api.router, prefix='/api/v1')
app.dependency_overrides[get_db] = db_dependency

@app.get('/healthz')
def health():
    return {'status': 'ok', 'mode': 'preview-only'}

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8017)
