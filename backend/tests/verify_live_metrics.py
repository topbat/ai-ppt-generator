"""Read-only acceptance against real containers after both real probes.

Run from repository root with a Python environment containing httpx:
python backend/tests/verify_live_metrics.py --output /path/to/live-results.json
Credentials are read locally and never included in the result.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    values = dict(line.split('=', 1) for line in (root/'deploy/langfuse/.env').read_text().splitlines()
                  if line and not line.startswith('#') and '=' in line)
    headers = {'Authorization': 'Bearer ' + values['METRICS_ACCESS_TOKEN']}
    auth = (values['LANGFUSE_PUBLIC_KEY'], values['LANGFUSE_SECRET_KEY'])
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': {}, 'engines': {}}
    # These are local endpoints; do not send credentials through a host HTTP proxy.
    with httpx.Client(timeout=30, trust_env=False) as client:
        for route in ('healthz', 'readyz'):
            response = client.get('http://localhost:8000/' + route)
            assert response.status_code == 200, route
            result['checks'][route] = response.json()
        path = 'http://localhost:8000/api/v1/metrics/'
        assert client.get(path+'summary').status_code == 401
        assert client.get(path+'summary', headers={'Authorization': 'Bearer wrong'}).status_code == 401
        assert client.get(path+'summary?days=999', headers=headers).status_code == 422
        result['checks']['auth_and_validation'] = 'passed'
        for engine in ('pipeline', 'pptmaster'):
            query = {'engine': engine, 'days': 1}
            summary = client.get(path+'summary', params=query, headers=headers).raise_for_status().json()['data']
            observations = client.get(path+'observations', params={**query, 'page_size': 100}, headers=headers).raise_for_status().json()['data']
            assert summary['summary']['count'] > 0, f'No real {engine} observations'
            candidates = [row for row in observations['items'] if row['status'] == 'success' and row['usage_source'] == 'reported']
            assert candidates, f'No successful reported usage for {engine}'
            row = candidates[0]
            deadline = time.monotonic() + 180
            while True:
                response = client.get('http://localhost:3000/api/public/v2/observations', auth=auth,
                    params={'traceId': row['trace_id'], 'type': 'GENERATION', 'fields': 'basic,usage,io,metadata,model', 'limit': 100})
                trace = response.json() if response.status_code == 200 else {}
                generations = [o for o in trace.get('data', []) if o.get('type') == 'GENERATION']
                if generations:
                    break
                assert time.monotonic() < deadline, f'Trace not ingested for {engine}'
                time.sleep(5)
            generation = generations[0]
            usage = generation.get('usageDetails') or {}
            # Both generic and classified input token keys are additive in Langfuse.
            remote_input = sum(v for key, v in usage.items() if key.startswith('input'))
            remote_output = sum(v for key, v in usage.items() if key.startswith('output'))
            assert remote_input == row['input_tokens'], (engine, 'input token mismatch')
            assert remote_output == row['output_tokens'], (engine, 'output token mismatch')
            assert generation.get('input') in (None, ''), 'Unexpected input content export'
            assert generation.get('output') in (None, ''), 'Unexpected output content export'
            deadline = time.monotonic() + 180
            while True:
                remote = client.get(path+'remote', params=query, headers=headers).raise_for_status().json()['data']
                if remote['status'] == 'ok' and remote['data']:
                    break
                assert time.monotonic() < deadline, f'Remote aggregation failed for {engine}'
                time.sleep(5)
            assert sum(int(r['count_count']) for r in remote['data']) == summary['summary']['count'], 'Remote count mismatch'
            filtered = client.get(path+'summary', params={**query, 'model': row['model']}, headers=headers).raise_for_status().json()['data']
            assert filtered['summary']['count'] > 0
            empty = client.get(path+'summary', params={**query, 'model': '__missing_acceptance_model__'}, headers=headers).raise_for_status().json()['data']
            assert empty['summary']['count'] == 0
            result['engines'][engine] = {'summary': summary, 'latest_observation': row,
                'langfuse_observation_id': generation['id'], 'remote_usage': usage,
                'remote': remote, 'privacy_and_model_filter': 'passed'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'passed', 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
