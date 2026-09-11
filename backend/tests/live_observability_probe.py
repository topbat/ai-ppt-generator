"""Opt-in real model/telemetry probe, executed inside the deployed container.

python /tmp/live_observability_probe.py pipeline|pptmaster
Consumes real model tokens. Does not create fictitious PPT jobs or seed metrics.
"""
import json
from pathlib import Path
import sys
import tempfile

from app.core.config import get_settings
from app.observability import flush


def main():
    engine = sys.argv[1]
    settings = get_settings()
    assert settings.langfuse_enabled, 'Langfuse must be enabled'
    if engine == 'pipeline':
        from app.ai.gateway import LLMGateway
        assert not settings.llm_mock, 'Real model is required'
        result = LLMGateway().chat_text(
            'doc_summary', 'fast', '请遵守用户要求，简短作答。',
            '这是观测链路验收。请仅回答：指标采集正常。', max_tokens=100)
        assert result.strip(), 'Empty model response'
        output = {'engine': engine, 'model': settings.llm_model_fast,
                  'response_nonempty': True}
    elif engine == 'pptmaster':
        from app.pptmaster.runner import ClaudeRunner, agent_env
        from app.pptmaster.service import _run_agent_observed
        model = settings.pptmaster_claude_model
        # Empty dedicated cwd avoids reading repository documents or writing artifacts.
        with tempfile.TemporaryDirectory(prefix='ppt-metrics-probe-') as work:
            runner = ClaudeRunner(binary=settings.pptmaster_claude_bin or None, model=model)
            result = _run_agent_observed(
                runner, None, 'claude', model, 1,
                prompt='这是观测链路验收。不要调用工具或读写任何文件，只回答：指标采集正常。',
                repo_dir=work, env=agent_env(work), log_path=str(Path(work)/'probe.log'), timeout_s=180)
            output = {'engine': engine, 'model': model, 'returncode': result.returncode,
                      'timed_out': result.timed_out, 'response_nonempty': bool(result.final_text),
                      'usage': result.extra.get('usage'), 'usage_source': result.extra.get('usage_source'),
                      'cost_usd': result.cost_usd}
            if result.returncode or result.error:
                flush()
                print(json.dumps(output, ensure_ascii=False))
                raise SystemExit('Real CLI probe failed; inspect private container logs.')
    else:
        raise SystemExit('Expected pipeline or pptmaster')
    flush()
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
